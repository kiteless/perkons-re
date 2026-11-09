#!/usr/bin/env python3
"""Pērkons Mod Matrix: a local web app that builds modded firmware from an official image.

  modmatrix.py [--port 6464] [--no-browser] [--no-intro]   (no-intro: no start-screen animation)

Serves ui/modmatrix/ on 127.0.0.1 only (nothing leaves the machine) and opens it in the
browser. The user supplies their own official .img; the app reads only its header
(version), CRCs and hash, offers every option from the mods' mod.json files
(tools/perkons/catalog.py, mods from PERKONS_MODS), builds with tools/build.py, runs the
emulator regression on the voices, and hands back perkons_v<version>-0-force.img.

API (JSON unless noted):
  GET  /api/status             toolchain check, supported versions, stale (the code or mods
                               changed on disk since this server started: restart it)
  GET  /api/mods               options
  POST /api/inspect            body: the .img bytes -> {image id, version, official, ...}
  GET  /api/memory/<image>     RAM per option, measured in the background after inspect:
                               {state: measuring|done, areas: {main|voice|store: {start, size: the
                                mods' part, block: {name, start, size, ranges: [{owner, start,
                                size}]}: the physical block, stock's ranges and 'mods'}},
                                options: {id: {area: {owner: bytes}}},
                                takeovers: {id: {area: {stock range: owner}}},
                                borrows: {id: {area: {firmware buffer: [owners]}}}, errors: {id: text}}
  POST /api/build              {image, options: [mod ids], voices: [voice ids, slot order],
                               checks: bool} -> {job}
  GET  /api/job/<id>           {state: running|done|failed, log: [...], partial: the line being
                               written (progress dots), download}
  GET  /api/download/<id>      the built image (application/octet-stream)
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import traceback
import urllib.parse
import uuid
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, ROOT)
from build import build_image, m7_code, regression  # noqa: E402
from perkons import catalog, cbuild, mods, ram, repos, srchash  # noqa: E402
from perkons.emu import Symbols  # noqa: E402
from perkons.mods import mod_dirs  # noqa: E402

UI_DIR = os.path.join(ROOT, 'ui', 'modmatrix')
MEMORY_FORMAT = 3          # the shape of a measurement (/api/memory): part of its cache key
MAX_IMAGE = 16 * 1024 * 1024


class LineLog(io.TextIOBase):
    """stdout replacement: complete lines go into a job's log; the line being written (e.g.
    the renders' progress dots) is the job's partial line."""

    def __init__(self, job):
        self.job, self.buf = job, ''

    def write(self, s):
        self.buf += s
        *lines, self.buf = self.buf.split('\n')
        for line in lines:
            self.job.say(line)
        self.job.partial = self.buf
        return len(s)


class Job:
    def __init__(self, img, raw, chosen, specs, checks):
        self.id = uuid.uuid4().hex[:12]
        self.img, self.raw, self.chosen, self.specs, self.checks = img, raw, chosen, specs, checks
        self.state, self.log, self.out, self.name = 'running', [], None, None
        self.partial = ''                    # the line being written, not yet in log
        self.lock = threading.Lock()

    def say(self, line):
        with self.lock:
            self.log.append(line.rstrip())

    def snapshot(self, since=0):
        with self.lock:
            return {'state': self.state, 'log': self.log[since:], 'next': len(self.log), 'partial': self.partial,
                    'download': f'/api/download/{self.id}' if self.state == 'done' else None,
                    'name': self.name}


def code_stamp():
    """What the running server's code and catalog were loaded from: every framework, UI and
    mod file's name, size and time. A server whose stamp no longer matches the disk is
    stale (its Python is older than the page and mods it would serve)."""
    files = [os.path.join(ROOT, 'tools', f) for f in os.listdir(os.path.join(ROOT, 'tools')) if f.endswith('.py')]
    for top in [os.path.join(ROOT, d) for d in srchash.FRAMEWORK] + [UI_DIR] + mod_dirs():
        files += list(srchash._files(top)) + [os.path.join(top, f) for f in os.listdir(top)
                                              if f.endswith(('.js', '.css', '.html'))]
    h = hashlib.sha256()
    for f in sorted(set(files)):
        st = os.stat(f)
        h.update(f'{f}\0{st.st_size}\0{st.st_mtime_ns}\0'.encode())
    return h.hexdigest()


class App:
    def __init__(self, intro=True):
        self.images = {}                     # image id -> (Image, raw bytes, info)
        self.memory = {}                     # image id -> measurement (see /api/memory)
        self.jobs = {}
        self.build_lock = threading.Lock()   # one build at a time (build output goes via stdout)
        self.work = tempfile.mkdtemp(prefix='modmatrix-')
        self.intro = intro
        self.code = code_stamp()
        self.local = catalog.options()       # mods on disk (PERKONS_MODS)
        self.repo_list, self.offered, self.repo_error = None, [], None
        self.repos_lock = threading.Lock()
        threading.Thread(target=self.load_repos, daemon=True).start()

    def status(self):
        try:
            cbuild.tool('gcc')
            gcc = True
        except cbuild.BuildError:
            gcc = False
        return {'gcc': gcc, 'supported': catalog.supported_versions(), 'intro': self.intro,
                'stale': code_stamp() != self.code}

    def inspect(self, raw):
        img, info = catalog.inspect(raw)
        image_id = info['sha256'][:16]
        self.images[image_id] = (img, raw, info)
        if info['official'] and info['supported'] and image_id not in self.memory:
            self.memory[image_id] = {'state': 'measuring'}
            threading.Thread(target=self.measure, args=(image_id,), daemon=True).start()
        return {'image': image_id, **info}

    # -- repos: where the mods come from (perkons.repos) ---------------------------------
    def load_repos(self):
        """The configured repos and their manifests, fetched once (in the background at
        start); a repo whose mods are on disk (PERKONS_MODS: a developer's clone) is read
        from there instead."""
        with self.repos_lock:
            if self.repo_list is not None:
                return
            local = {}
            for o in self.local:
                if o.get('repo'):
                    local.setdefault(o['repo'].lower(), []).append(o)
            out, offered = [], [o for o in self.local if not o.get('repo')]
            try:
                configured = repos.config()
            except repos.RepoError as e:
                configured, self.repo_error = [], str(e)
            names = {r['repo'].lower() for r in configured}
            for name in sorted(set(local) - names):     # on disk but not in the list: offered too
                configured.append({'repo': local[name][0]['repo'], 'ref': 'main', 'default': True, 'note': ''})
            for r in configured:
                row = {'repo': r['repo'], 'author': r['repo'].split('/')[0], 'default': r['default'],
                       'description': '', 'note': r['note'], 'mods': 0, 'local': r['repo'].lower() in local, 'error': None}
                if row['local']:
                    opts = local[r['repo'].lower()]
                    root = opts[0]['local']
                    with open(os.path.join(root, repos.REPO_FILE)) as f:
                        row['description'] = json.load(f).get('description', '')
                else:
                    try:
                        m = repos.manifest(r['repo'], r['ref'])
                        opts = repos.options(m, r['ref'])
                        row['description'] = m.get('description', '')
                    except (repos.RepoError, KeyError, TypeError) as e:
                        opts, row['error'] = [], str(e)
                row['mods'] = len(opts)
                offered += opts
                out.append(row)
            out.sort(key=lambda r: (r['repo'].lower() != repos.HOME, r['repo'].lower()))   # the main one, then A-Z
            self.repo_list, self.offered = out, offered

    def repos(self):
        self.load_repos()
        return {'repos': self.repo_list, 'error': self.repo_error}

    def options(self, ticked=None):
        """The options from the ticked repos (all of them if None), and those of mods on
        disk outside any repo."""
        self.load_repos()
        ticked = None if ticked is None else {r.lower() for r in ticked}
        return [o for o in self.offered if not o.get('repo') or ticked is None or o['repo'].lower() in ticked]

    def measure(self, image_id):
        """Build every option on disk alone (with what it requires, no image written) and
        record the RAM it takes, for the MAIN / VOICE / STORE meters; a downloadable mod's
        comes from its repo's manifest (memory_for). Kept in .cache/memory/ by a hash of the
        image and every build input, so a restart with nothing changed is instant."""
        img, _, info = self.images[image_id]
        cache = srchash.path('memory', srchash.key(info['sha256'], MEMORY_FORMAT), '.json')
        if os.path.exists(cache):
            with open(cache) as f:
                self.memory[image_id] = json.load(f)
            return
        symbols = os.path.join(ROOT, 'symbols', f'v{info["version"]}-m7.json')
        syms = {'m7': Symbols(symbols), 'm4': Symbols(symbols.replace('-m7.json', '-m4.json'))}
        blocks = ram.blocks(syms)
        areas = {a: {'start': lo, 'size': hi - lo,
                     'block': {'name': blocks[a]['name'], 'start': blocks[a]['start'],
                               'size': blocks[a]['end'] - blocks[a]['start'],
                               'ranges': [{'owner': o, 'start': s, 'size': e - s}
                                          for o, s, e in blocks[a]['ranges']]}}
                 for a, (lo, hi) in ram.areas(syms).items()}
        opts, takeovers, borrows, errors = {}, {}, {}, {}
        with self.build_lock:
            by_id = {o['id']: o for o in self.local}
            for o in by_id.values():
                if o['target'] not in (None, info['version']):
                    continue
                specs = list(dict.fromkeys(s for i in catalog.with_requires([o['id']], by_id)
                                           for s in by_id[i]['patches']))
                try:
                    got = catalog.measure(img, specs, symbols, os.path.join(self.work, 'measure', o['id'].replace('/', '_')))
                    opts[o['id']] = got['ram']
                    if got['takeovers']:
                        takeovers[o['id']] = got['takeovers']
                    if got['borrows']:
                        borrows[o['id']] = got['borrows']
                except BaseException as e:   # also sys.exit from a target mismatch
                    errors[o['id']] = str(e)
        self.memory[image_id] = m = {'state': 'done', 'version': info['version'], 'areas': areas, 'options': opts,
                                     'takeovers': takeovers, 'borrows': borrows, 'errors': errors}
        if not errors:
            with open(cache, 'w') as f:
                json.dump(m, f)

    def memory_for(self, image_id):
        """The measurement, with every downloadable mod's RAM from its repo's manifest."""
        m = self.memory.get(image_id)
        if not m or m.get('state') != 'done':
            return m
        m = dict(m, options=dict(m['options']), takeovers=dict(m['takeovers']), borrows=dict(m['borrows']),
                 errors=dict(m['errors']))
        for o in self.options():
            if o['id'] in m['options'] or o.get('local'):
                continue
            if o['target'] not in (None, m['version']):
                continue
            mem = o['memory'].get(f'v{m["version"]}')
            if not mem:
                m['errors'][o['id']] = f'{o["repo"]} has no memory figures for firmware {m["version"]}'
                continue
            m['options'][o['id']] = mem.get('ram', {})
            for key in ('takeovers', 'borrows'):
                if mem.get(key):
                    m[key][o['id']] = mem[key]
        return m

    def fetch_mods(self, chosen):
        """The chosen downloadable mods, each repo's at the commit it's at now: their
        directories, for the build."""
        dirs = []
        by_repo = {}
        for o in chosen:
            if not o.get('local'):
                by_repo.setdefault((o['repo'], o['ref']), []).append(o['dir'])
        for (repo, ref), want in by_repo.items():
            root = repos.download(repo, ref, sorted(set(want)))
            dirs += [os.path.join(root, *d.split('/')) for d in sorted(set(want))]
        return dirs

    def start_build(self, req):
        if req.get('image') not in self.images:
            raise catalog.CatalogError('load a firmware image first')
        img, raw, info = self.images[req['image']]
        if not info['supported']:
            raise catalog.CatalogError(f'firmware {info["version"]} is not supported yet')
        chosen, specs = catalog.check_selection(list(req.get('options', [])), info['version'],
                                                voices=list(req.get('voices', [])), offered=self.options())
        mem = self.memory_for(req['image']) or {}
        if mem.get('state') == 'done':
            catalog.check_memory([o['id'] for o in chosen], mem)
        job = Job(img, raw, chosen, specs, bool(req.get('checks', True)))
        self.jobs[job.id] = job
        threading.Thread(target=self.run, args=(job,), daemon=True).start()
        return {'job': job.id}

    def run(self, job):
        with self.build_lock:
            d = os.path.join(self.work, job.id)
            os.makedirs(d)
            tag = catalog.build_tag(job.chosen)
            titles = ', '.join(o['title'].lower() for o in job.chosen)
            specs = job.specs + [f'version_stamp:{tag}']
            symbols = os.path.join(ROOT, 'symbols', f'v{job.img.version}-m7.json')
            out = os.path.join(d, 'out.img')
            try:
                with contextlib.redirect_stdout(LineLog(job)):
                    job.say(f'MODS: {titles}')
                    if any(not o.get('local') for o in job.chosen):
                        job.say('DOWNLOADING THE MODS...')
                    mods.EXTRA[:] = self.fetch_mods(job.chosen)     # (one build at a time)
                    job.say(f'TAG: {tag}')
                    built, p = build_image(job.img, out, specs, symbols, build_dir=os.path.join(d, 'obj'),
                                           extra_kwargs={'version_stamp': {'banner': f'+ mod matrix: {titles}'}})
                    if job.checks:
                        bad = regression(job.img, built, symbols, renders=m7_code(p))
                        if bad:
                            raise RuntimeError(f'{len(bad)} voice renders differ from stock: not safe to flash')
                job.out, job.name = out, f'perkons_v{job.img.version}-0-force.img'
                job.say('READY.')
                job.state = 'done'
            except Exception as e:
                job.say(f'?BUILD ERROR: {e}')
                for line in traceback.format_exc().splitlines()[-6:]:
                    job.say(line)
                job.state = 'failed'
            finally:
                mods.EXTRA[:] = []


def make_handler(app):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=UI_DIR, **kw)

        def log_message(self, fmt, *args):
            pass

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

        def send_json(self, obj, status=HTTPStatus.OK):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            n = int(self.headers.get('Content-Length', 0))
            if n > MAX_IMAGE:
                raise catalog.CatalogError('file too large for a firmware image')
            return self.rfile.read(n)

        def guarded(self, fn):
            try:
                self.send_json(fn())
            except (catalog.CatalogError, ValueError) as e:
                self.send_json({'error': str(e)}, HTTPStatus.BAD_REQUEST)
            except Exception as e:
                traceback.print_exc()
                self.send_json({'error': f'internal error: {e}'}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/api/status':
                return self.guarded(app.status)
            if path == '/api/repos':
                return self.guarded(app.repos)
            if path == '/api/mods':
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query, keep_blank_values=True)
                ticked = [r for r in q.get('repos', [''])[0].split(',') if r] if 'repos' in q else None
                return self.guarded(lambda: {'options': app.options(ticked)})
            if path.startswith('/api/memory/'):
                mem = app.memory_for(path.rsplit('/', 1)[1])
                if not mem:
                    return self.send_json({'error': 'load a firmware image first'}, HTTPStatus.NOT_FOUND)
                return self.send_json(mem)
            if path.startswith('/api/job/'):
                job = app.jobs.get(path.rsplit('/', 1)[1])
                if not job:
                    return self.send_json({'error': 'no such job'}, HTTPStatus.NOT_FOUND)
                since = int((self.path.split('since=') + ['0'])[1].split('&')[0] or 0)
                return self.send_json(job.snapshot(since))
            if path.startswith('/api/download/'):
                job = app.jobs.get(path.rsplit('/', 1)[1])
                if not job or job.state != 'done':
                    return self.send_json({'error': 'not built'}, HTTPStatus.NOT_FOUND)
                with open(job.out, 'rb') as f:
                    data = f.read()
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', f'attachment; filename="{job.name}"')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith('/api/'):
                return self.send_json({'error': 'not found'}, HTTPStatus.NOT_FOUND)
            return super().do_GET()

        def do_POST(self):
            path = self.path.split('?')[0]
            if path == '/api/inspect':
                return self.guarded(lambda: app.inspect(self.body()))
            if path == '/api/build':
                return self.guarded(lambda: app.start_build(json.loads(self.body() or b'{}')))
            return self.send_json({'error': 'not found'}, HTTPStatus.NOT_FOUND)

    return Handler


def serve(port=6464, intro=True):
    """Start the server (port 0 = any free port). Returns (server, App)."""
    app = App(intro=intro)
    try:
        server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(app))
    except OSError:
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
    return server, app


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--port', type=int, default=6464)
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--no-intro', action='store_true')
    a = ap.parse_args()
    server, app = serve(a.port, intro=not a.no_intro)
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    print(f'PERKONS MOD MATRIX at {url}  (ctrl-c to quit)')
    if not a.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        shutil.rmtree(app.work, ignore_errors=True)


if __name__ == '__main__':
    main()
