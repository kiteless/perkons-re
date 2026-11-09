"""A pretend GitHub for perkons.repos: repos as {path: bytes} trees, served through
repos.FETCH (raw files at a ref or commit, the commits and trees API), with a log of what was
fetched."""
import hashlib
import json

from perkons import repos


class FakeGitHub:
    def __init__(self, config, trees):
        """config: the repos.json object; trees: {owner/name: {path: bytes or str or obj}}."""
        self.config = config
        self.trees = {r: {p: self._bytes(v) for p, v in t.items()} for r, t in trees.items()}
        self.sha = {r: hashlib.sha1(r.encode()).hexdigest() for r in trees}
        self.log = []
        self.down = False

    @staticmethod
    def _bytes(v):
        if isinstance(v, bytes):
            return v
        return (v if isinstance(v, str) else json.dumps(v)).encode()

    CONFIG_URL = 'https://fake.test/repos.json'

    def fetch(self, url):
        self.log.append(url)
        if self.down:
            raise OSError('network down')
        if url == self.CONFIG_URL:
            return self._bytes(self.config)
        raw = 'https://raw.githubusercontent.com/'
        api = 'https://api.github.com/repos/'
        if url.startswith(raw):
            owner, name, ref, path = url[len(raw):].split('/', 3)
            tree = self.trees.get(f'{owner}/{name}', {})
            if path in tree and ref in ('main', self.sha[f'{owner}/{name}']):
                return tree[path]
        elif url.startswith(api):
            owner, name, what = url[len(api):].split('/', 2)
            repo = f'{owner}/{name}'
            if repo in self.trees and what == 'commits/main':
                return self._bytes({'sha': self.sha[repo]})
            if repo in self.trees and what == f'git/trees/{self.sha[repo]}?recursive=1':
                return self._bytes({'tree': [{'path': p, 'type': 'blob'} for p in sorted(self.trees[repo])],
                                    'truncated': False})
        raise OSError(f'404 {url}')

    def install(self, cache):
        """Serve this, with the fetched and downloaded files kept in `cache` (a temporary
        directory) instead of .cache/. Returns a function that puts things back."""
        saved = repos.FETCH, repos.CONFIG_URL, repos.CACHE
        repos.FETCH, repos.CONFIG_URL, repos.CACHE = self.fetch, self.CONFIG_URL, cache

        def restore():
            repos.FETCH, repos.CONFIG_URL, repos.CACHE = saved
        return restore

    def fetched(self, repo, path_prefix):
        return [u for u in self.log if f'/{repo}/' in u and path_prefix in u]
