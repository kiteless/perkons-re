#!/usr/bin/env python3
"""Pērkons Mod Matrix: a local web app that builds modded firmware from an official image.

  modmatrix.py [--port 6464] [--no-browser] [--no-intro]

Serves ui/modmatrix/ on 127.0.0.1 only (nothing leaves the machine) and opens it in the
browser. The user supplies their own official .img; the app reads only its header
(version), CRCs and hash, offers every option from the mods' mod.json files
(tools/perkons/catalog.py, mods from PERKONS_MODS), builds with tools/build.py, runs the
emulator regression on the voices, and hands back perkons_v<version>-0-force.img.

API (JSON unless noted):
  GET  /api/status             toolchain check, supported versions
  GET  /api/mods               options
  POST /api/inspect            body: the .img bytes -> {image id, version, official, ...}
  POST /api/build              {image, options: [ids], checks: bool} -> {job}
  GET  /api/job/<id>           {state: running|done|failed, log: [...], download}
  GET  /api/download/<id>      the built image (application/octet-stream)
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import traceback
import uuid
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, ROOT)
from build import build_image, regression  # noqa: E402
from perkons import catalog, cbuild  # noqa: E402

UI_DIR = os.path.join(ROOT, 'ui', 'modmatrix')
MAX_IMAGE = 16 * 1024 * 1024


class LineLog(io.TextIOBase):
    """stdout replacement: collects complete lines into a job's log."""

    def __init__(self, job):
        self.job, self.buf = job, ''

    def write(self, s):
        self.buf += s
        *lines, self.buf = self.buf.split('\n')
        for line in lines:
            self.job.say(line)
        return len(s)


class Job:
    def __init__(self, img, raw, chosen, specs, checks):
        self.id = uuid.uuid4().hex[:12]
        self.img, self.raw, self.chosen, self.specs, self.checks = img, raw, chosen, specs, checks
        self.state, self.log, self.out, self.name = 'running', [], None, None
        self.lock = threading.Lock()

    def say(self, line):
        with self.lock:
            self.log.append(line.rstrip())

    def snapshot(self, since=0):
        with self.lock:
            return {'state': self.state, 'log': self.log[since:], 'next': len(self.log),
                    'download': f'/api/download/{self.id}' if self.state == 'done' else None,
                    'name': self.name}


class App:
    def __init__(self, intro=True):
        self.images = {}                     # image id -> (Image, raw bytes, info)
        self.jobs = {}
        self.build_lock = threading.Lock()   # one build at a time (build output goes via stdout)
        self.work = tempfile.mkdtemp(prefix='modmatrix-')
        self.intro = intro

    def status(self):
        try:
            cbuild.tool('gcc')
            gcc = True
        except cbuild.BuildError:
            gcc = False
        return {'gcc': gcc, 'supported': catalog.supported_versions(), 'intro': self.intro}

    def inspect(self, raw):
        img, info = catalog.inspect(raw)
        image_id = info['sha256'][:16]
        self.images[image_id] = (img, raw, info)
        return {'image': image_id, **info}

    def start_build(self, req):
        if req.get('image') not in self.images:
            raise catalog.CatalogError('load a firmware image first')
        img, raw, info = self.images[req['image']]
        if not info['supported']:
            raise catalog.CatalogError(f'firmware {info["version"]} is not supported yet')
        chosen, specs = catalog.check_selection(list(req.get('options', [])), info['version'])
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
                    job.say(f'TAG: {tag}')
                    built, _ = build_image(job.img, out, specs, symbols, build_dir=os.path.join(d, 'obj'),
                                           extra_kwargs={'version_stamp': {'banner': f'+ mod matrix: {titles}'}})
                    if job.checks:
                        bad = regression(job.img, built, symbols)
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
            if path == '/api/mods':
                return self.guarded(lambda: {'options': catalog.options()})
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
    if not os.environ.get('PERKONS_MODS'):
        print('note: PERKONS_MODS is not set, so no mods will be offered (see local.mk)')
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
