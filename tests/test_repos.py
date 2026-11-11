"""Mod repos (perkons.repos): the repo list, manifests, namespaced ids, downloads of only
the mods a build needs, and RAM owners named the same on every machine."""
import json
import os
import shutil
import tempfile
import unittest

from fake_github import FakeGitHub
from perkons import catalog, repos

BASE = 'kiteless/perkons-re-mods'
EXTRA = 'someone/engines'


def manifest(repo, mods, **kw):
    return {'format': 1, 'repo': repo, 'description': f'{repo} mods', 'mods': mods, **kw}


def mod(i, d, **kw):
    return {'id': i, 'dir': d, 'title': i.upper(), 'summary': f'{i}.', 'patches': [i.replace('-', '_')],
            'code': i[:2], 'kind': 'mod', 'requires': [], 'conflicts': [], 'target': '1.3.0',
            'memory': {}, **kw}


class TestRepos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pk-repos-')
        self.gh = FakeGitHub(
            {'repos': [{'repo': BASE, 'default': True, 'note': 'Read me.'}, {'repo': EXTRA}, {'repo': BASE.upper()}]},
            {BASE: {'perkons-mods.json': manifest(BASE, [mod('voice-map', 'voice-map'), mod('shared', 'shared')]),
                    'perkons-repo.json': {'repo': BASE}, 'README.md': 'base',
                    'shared/mod.json': '{}', 'shared/patches/shared.py': '#',
                    'fx-reverb/patches/fx_reverb.py': '#'},
             EXTRA: {'perkons-mods.json': manifest(EXTRA, [
                 mod('engine', 'engine', kind='voice', requires=[f'{BASE}:voice-map', f'{BASE}:shared', 'helper'],
                     readme='engine/README.md'),
                 mod('helper', 'helper')])}})
        self.restore = self.gh.install(os.path.join(self.tmp, 'cache'))

    def tearDown(self):
        self.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_config(self):
        self.assertEqual(repos.config(), [{'repo': BASE, 'ref': 'main', 'default': True, 'note': 'Read me.'},
                                          {'repo': EXTRA, 'ref': 'main', 'default': False, 'note': ''}],
                         'the same repo once')
        self.gh.config = {'repos': [{'repo': 'not a repo'}]}
        with self.assertRaises(repos.RepoError):
            repos.config()

    def test_the_last_list_and_manifests_are_used_offline(self):
        repos.config()
        repos.manifest(EXTRA)
        self.gh.down = True
        self.assertEqual(len(repos.config()), 2)
        self.assertEqual(repos.manifest(EXTRA)['repo'], EXTRA)
        with self.assertRaises(repos.RepoError):
            repos.manifest('never/fetched')

    def test_a_manifest_must_be_its_repos(self):
        self.gh.trees['bad/one'] = {'perkons-mods.json': self.gh.trees[EXTRA]['perkons-mods.json']}
        self.gh.sha['bad/one'] = 'f' * 40
        with self.assertRaisesRegex(repos.RepoError, 'is for'):
            repos.manifest('bad/one')
        self.gh.trees['old/format'] = {'perkons-mods.json': json.dumps(dict(manifest('old/format', []), format=99)).encode()}
        self.gh.sha['old/format'] = 'e' * 40
        with self.assertRaisesRegex(repos.RepoError, 'format'):
            repos.manifest('old/format')

    def test_ids_are_namespaced_and_requires_cross_repos(self):
        opts = {o['id']: o for o in repos.options(repos.manifest(EXTRA))}
        self.assertEqual(set(opts), {f'{EXTRA}:engine', f'{EXTRA}:helper'})
        e = opts[f'{EXTRA}:engine']
        self.assertEqual(e['requires'], [f'{BASE}:shared', f'{EXTRA}:helper'], 'voice-map: the platform')
        self.assertEqual((e['author'], e['readme']), ('someone', f'https://github.com/{EXTRA}/blob/main/engine/README.md'))

    def test_a_repo_doesnt_offer_what_is_now_the_platform(self):
        self.assertEqual([o['id'] for o in repos.options(repos.manifest(BASE))], [f'{BASE}:shared'])

    def test_selection_across_repos(self):
        offered = repos.options(repos.manifest(BASE)) + repos.options(repos.manifest(EXTRA))
        with self.assertRaisesRegex(catalog.CatalogError, 'needs'):
            catalog.check_selection([f'{EXTRA}:helper'], '1.3.0', voices=[f'{EXTRA}:engine'], offered=offered)
        chosen, specs = catalog.check_selection([f'{BASE}:shared', f'{EXTRA}:helper'], '1.3.0',
                                                voices=[f'{EXTRA}:engine'], offered=offered)
        self.assertEqual(specs, ['voice_map', 'shared', 'helper', 'engine:5'], 'the platform first')

    def test_one_patch_name_from_two_repos_is_refused(self):
        twin = repos.options(manifest('other/fork', [mod('shared', 'shared')]))
        with self.assertRaisesRegex(catalog.CatalogError, 'two repos'):
            catalog.check_selection([f'{BASE}:shared', 'other/fork:shared'], '1.3.0',
                                    offered=repos.options(repos.manifest(BASE)) + twin)

    def test_download_fetches_only_the_dirs_asked_for(self):
        root = repos.download(BASE, 'main', ['shared'])
        self.assertTrue(os.path.exists(os.path.join(root, 'shared', 'patches', 'shared.py')))
        self.assertTrue(os.path.exists(os.path.join(root, 'perkons-repo.json')), 'the root files too')
        self.assertFalse(os.path.exists(os.path.join(root, 'fx-reverb')))
        self.assertFalse(self.gh.fetched(BASE, 'fx-reverb/'))
        n = len(self.gh.log)
        self.assertEqual(repos.download(BASE, 'main', ['shared']), root)
        self.assertEqual([u for u in self.gh.log[n:] if 'raw.githubusercontent' in u], [], 'kept: not fetched again')
        self.assertEqual(repos.repo_root(os.path.join(root, 'shared')), (root, BASE))

    def test_download_refuses_paths_outside_the_repo(self):
        self.gh.trees[BASE]['shared/../../escape'] = b'x'
        with self.assertRaisesRegex(repos.RepoError, 'bad path'):
            repos.download(BASE, 'main', ['shared'])

    def test_ram_owners_are_named_by_repo(self):
        root = repos.download(BASE, 'main', ['shared'])
        src = os.path.relpath(os.path.join(root, 'shared', 'src', 'm7', 'shared.c'), catalog.ROOT)
        self.assertEqual(catalog.canonical_owner(f'{src}:.bss.x'), f'{BASE}:shared/src/m7/shared.c:.bss.x')
        self.assertEqual(catalog.canonical_owner('src/m4/host/pk_host.c:.bss'), 'src/m4/host/pk_host.c:.bss')
        self.assertEqual(catalog.canonical_owner('voice_map'), 'voice_map')


if __name__ == '__main__':
    unittest.main()
