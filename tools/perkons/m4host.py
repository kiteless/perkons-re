"""M4 host: shared plumbing for M4 mods, so features can be built alone or together.

Several M4 features need the same firmware hook points: the boot sequence, the config
page, settings saving, the FX process pointer, patch RAM. Each can be patched only
once, so instead of patching them, a mod registers with the host from its apply():

    from perkons import m4host

    def apply(p, arg=None):
        h = m4host.host(p)
        h.add([os.path.join(SRC, 'my_fx.c')], [SRC], init='pk_my_init')
        h.toggle(46, 'my-feature', 'pk_cfg_my_feature')   # config key, mods.json key, uint8_t var
        h.setting('my-number', 'pk_my_number')             # a number (uint8_t) in mods.json
        h.fx()                                              # take over the FX process function
        h.redirect_call('some_fn.call_site', 'pk_my_hook', 'why')   # resolved after the link
        h.on('track_clear', 'pk_my_cleared')               # a framework event: void f(void)
        h.add([...], on_save='pk_my_save')                 # run whenever the settings are saved

When every patch is applied (Patcher.finish / result), the host compiles all registered
sources with its own (src/m4/host/) in one link, appends the code, and patches each
hook point once. Toggles and settings are stored in their own file, system/mods.json,
loaded after and saved with the firmware's device.json, which stays stock. Mods talk to each other
through the weak hooks in include/m4/pk_host.h. p.cave_symbols['m4host'] gets the linked
symbols (functions and .bss variables).

Hooks chain: several mods may redirect the same site (a `bl`, a tail `b.w`, or a literal
holding a function pointer). The host links them in order (order, then symbol name):
the site goes to a guard, the guard to the first hook, and each hook continues with
PK_NEXT(itself) (include/m4/pk_host.h), the next hook or the stock function. Until the
host has booted (zeroed the mods' RAM) the guard goes straight to the stock function, so
no hook runs on power-on garbage. A hook used at several sites must have the same next
hook at all of them. Events (EVENTS, framework sites named event.<name>.*) are chain
links that call their subscribers, then go on.

RAM (both zeroed at boot, before the mods' inits):
* .bss goes in the D2 SRAM gap between the newlib heap and the M7's audio DMA buffer
  (0x10040000); the heap is capped below it by patching _sbrk's limit. Fast: for state
  the audio path touches.
* PK_AXI variables (include/m4/pk_host.h) go in the AXI SRAM no firmware code references
  (axi_gap()). Larger and a few cycles slower per access: settings, control-rate state,
  bulk data.
"""
import os

from . import cbuild, hooks
from .hooks import HostError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOST_SRC = os.path.join(ROOT, 'src', 'm4', 'host')
RAM_BASE, RAM_END = 0x1002ff00, 0x10040000    # v1.3.0: heap starts at bss_end 0x1002efb0
JSON_BOOL, JSON_U8 = 0x80, 0x81
PK_HOST_MAGIC = 0x54534f48                    # 'HOST': src/m4/host/pk_host.c
SAVE_SITES = ('cfg_exit_save.tail_device_json_save', 'page11_exit.tail_device_json_save',
              'page12_exit.tail_device_json_save')


# events mods can subscribe to (h.on); each is the framework sites named event.<name>.*
EVENTS = {
    'track_clear': 'a track is cleared (CLEAR + trigger)',
    'automation_clear': "a track's automation is cleared (SHIFT + CLEAR + trigger)",
    'pattern_clear': 'a pattern is cleared (PATTERN page: CLEAR + step)',
}



def axi_gap(sym, margin=0x100):
    """(start, end) of the AXI SRAM between the M4's last object (the JSON buffer) and the
    sample table, which no firmware code references; `margin` kept clear at each end."""
    lo = sym.g['json_buf'] + sym.const['json_buf_size'] + margin
    hi = sym.g['sample_table'] - margin
    return (lo + 0xff) & ~0xff, hi & ~0xff


def host(p):
    """The patcher's M4 host, created (and scheduled to build) on first use."""
    h = getattr(p, 'm4host', None)
    if h is None:
        h = p.m4host = Host(p)
        p.on_finish(h.finish)
    return h


class Host:
    def __init__(self, p):
        self.p = p
        self.sources, self.include_dirs, self.inits, self.savers = [], [], [], []
        self.defines = {}
        self.headers = {}                    # generated headers: name -> text or callable
        self.toggles = []                    # (config key, json key, var)
        self.settings = []                   # (json key, var): uint8_t numbers in mods.json
        self.use_fx = False
        self.hooks = []                      # (kind, site, symbol, why, order)
        self.events = {}                     # event -> [subscriber]
        self.stores = {'pattern': [], 'kit': []}   # (tag, save fn, load fn)
        self.syms = None

    # -- registration (from patch apply) -----------------------------------------------
    def add(self, sources, include_dirs=(), init=None, on_save=None, defines=None, headers=None):
        """C sources to link; init: a void(void) function run at boot, after .bss is
        zeroed and before the settings files load; on_save: a void(void) function run
        whenever the firmware saves its settings, after device.json (and mods.json);
        defines: {name: value} for every source in the link; headers: {name: text, or a
        function returning it, called at link time (e.g. built from other mods' registrations)}."""
        self.sources += [s for s in sources if s not in self.sources]
        self.include_dirs += [d for d in include_dirs if d not in self.include_dirs]
        if init and init not in self.inits:
            self.inits.append(init)
        if on_save and on_save not in self.savers:
            self.savers.append(on_save)
        for k, v in (defines or {}).items():
            if self.defines.get(k, v) != v:
                raise HostError(f'define {k}: {v} clashes with {self.defines[k]}')
            self.defines[k] = v
        for k, v in (headers or {}).items():
            if k in self.headers and self.headers[k] is not v:
                raise HostError(f'generated header {k} registered twice')
            self.headers[k] = v

    def toggle(self, key, json_key, var):
        """On/off setting: config-page key (LED shows it), a bool in system/mods.json, uint8_t var."""
        for k, j, v in self.toggles:
            if key == k or json_key == j or var == v:
                raise HostError(f'toggle {json_key} (key {key}, {var}) clashes with {j} (key {k}, {v})')
        self.toggles.append((key, json_key, var))

    def setting(self, json_key, var):
        """A number (uint8_t var, 0-255) stored in system/mods.json; the mod sets its default
        in its init (a missing key leaves it)."""
        for _, j, v in self.toggles + [(None, j, v) for j, v in self.settings]:
            if json_key == j or var == v:
                raise HostError(f'setting {json_key} ({var}) clashes with {j} ({v})')
        self.settings.append((json_key, var))

    def fx(self):
        self.use_fx = True

    def redirect_call(self, site, symbol, why, order=0):
        """Site is `bl <fn>`: the call goes to `symbol` (chained with other mods' hooks)."""
        self.hooks.append(('call', site, symbol, why, order))

    def redirect_branch(self, site, symbol, why, order=0):
        """Site is a tail call `b.w <fn>`: it goes to `symbol` (chained)."""
        self.hooks.append(('branch', site, symbol, why, order))

    def replace_word(self, site, symbol, why, order=0):
        """Site is a literal: a function pointer (odd) is chained like a call; a data
        pointer is replaced outright (one mod only)."""
        self.hooks.append(('word', site, symbol, why, order))

    def store(self, kind, tag, save, load):
        """Per-pattern or per-kit data in sidecar files (src/m4/host/pk_host_store.c):
        kind 'pattern' (BANKS/NN/PP.PAX) or 'kit' (BANKS/NN/KITS/PP.KIX); tag: 4 characters,
        the record's name; save: `uint32_t f(int bank, int idx, uint8_t *buf, uint32_t max)`
        returns the record's length (0: none); load: `void f(int bank, int idx, const
        uint8_t *rec, uint32_t len)`, after a bank load (every index) or a clear (len 0:
        no record)."""
        if kind not in self.stores:
            raise HostError(f'store kind {kind!r}: pattern or kit')
        if len(tag) != 4 or not tag.isascii():
            raise HostError(f'store tag {tag!r}: 4 ASCII characters')
        for k, entries in self.stores.items():
            for t, _, _ in entries:
                if k == kind and t == tag:
                    raise HostError(f'{kind} store tag {tag} used twice')
        self.stores[kind].append((tag, save, load))

    def on(self, event, fn):
        """Call `void fn(void)` when the firmware does `event` (EVENTS), before it does it."""
        if event not in EVENTS:
            raise HostError(f'unknown event {event!r} (known: {", ".join(sorted(EVENTS))})')
        subs = self.events.setdefault(event, [])
        if fn not in subs:
            subs.append(fn)

    # -- build (from Patcher.finish) -------------------------------------------------------
    def gen_source(self):
        lines = ['/* generated by tools/perkons/m4host.py -- do not edit */', '#include <stdint.h>',
                 'typedef struct { uint8_t key; uint8_t *var; } pk_toggle_t;']
        lines += [f'extern uint8_t {v};' for _, _, v in self.toggles] + [f'extern uint8_t {v};' for _, v in self.settings]
        rows = ''.join(f'{{{k}, &{v}}}, ' for k, _, v in self.toggles) or '{0, 0}'
        lines += [f'const pk_toggle_t pk_toggles[] = {{{rows}}};',
                  f'const int pk_n_toggles = {len(self.toggles)};']
        # system/mods.json: one bool per toggle; offsets are the variables' addresses
        # (loaded and saved with a NULL struct base)
        lines += ['typedef struct { const char *key; uint32_t offset, type; const void *e, *n; } pk_json_entry_t;',
                  'typedef struct { const pk_json_entry_t *entries; uint32_t count; } pk_json_schema_t;']
        keys = [(j, v, JSON_BOOL) for _, j, v in self.toggles] + [(j, v, JSON_U8) for j, v in self.settings]
        ents = ''.join(f'{{"{j}", (uint32_t)&{v}, 0x{ty:x}u, 0, 0}}, ' for j, v, ty in keys) or '{0, 0, 0, 0, 0}'
        lines += [f'static const pk_json_entry_t pk_mods_entries[] = {{{ents}}};',
                  f'const pk_json_schema_t pk_mods_schema = {{pk_mods_entries, {len(keys)}}};']
        lines.append('typedef struct { char tag[4]; void *save, *load; } pk_store_t;')
        for kind in ('pattern', 'kit'):
            entries = sorted(self.stores[kind])
            lines += [f'extern char {f}[];' for _, a, b in entries for f in (a, b)]
            rows = ''.join('{{' + ', '.join(f"'{c}'" for c in t) + f'}}, {a}, {b}}}, ' for t, a, b in entries) \
                or '{{0}, 0, 0}'
            lines += [f'const pk_store_t pk_store_{kind}[] = {{{rows}}};',
                      f'const int pk_n_store_{kind} = {len(entries)};']
        lines += [f'void {f}(void);' for f in self.inits + self.savers]
        lines.append('void pk_host_run_inits(void) {' + ''.join(f' {f}();' for f in self.inits) + ' }')
        lines.append('void pk_host_run_savers(void) {' + ''.join(f' {f}();' for f in self.savers) + ' }')
        return '\n'.join(lines) + '\n'

    def finish(self):
        p, sym = self.p, self.p.symbols['m4']
        # the same image whatever order the patches were applied in
        self.sources.sort()
        self.inits.sort()
        self.savers.sort()
        self.toggles.sort()
        self.settings.sort()
        if self.stores['pattern'] or self.stores['kit']:
            for site in ('patpage.call_save_a', 'patpage.call_save_b'):
                self.redirect_call(site, 'pk4_store_pat_save', 'pattern save: mods\' sidecar records', order=-2000)
            self.redirect_call('patpage.call_clear', 'pk4_store_pat_clear', 'pattern clear: sidecar too', order=-2000)
            for site in ('switch_bank.call_bank_prepare', 'boot_load_last_bank.call_bank_prepare'):
                self.redirect_call(site, 'pk4_store_bank_load', 'bank load: mods\' sidecar records', order=-2000)
            for site in sorted(k for k in self.p.symbols['m4'].sites if k.startswith('kits.save.')):
                self.redirect_call(site, 'pk4_store_kit_save', 'kit save: mods\' sidecar records', order=-2000)
        from .m7host import message_defines
        self.defines.update(message_defines(p))     # M7 config message types: PK_MSG_<NAME>
        sym4 = self.p.symbols['m4']
        chains, data, nxt = hooks.collect(sym4, self.hooks, (0x08100000, 0x08200000),
                                          hooks.event_links(sym4, self.events))
        if sym.mem['bss_end'] >= RAM_BASE:
            raise HostError(f'patch RAM {RAM_BASE:#x} overlaps the firmware .bss (ends {sym.mem["bss_end"]:#x})')
        srcs = [os.path.join(HOST_SRC, 'pk_host.c')]
        if self.stores['pattern'] or self.stores['kit']:
            srcs.append(os.path.join(HOST_SRC, 'pk_host_store.c'))
        if self.use_fx:
            srcs += [os.path.join(HOST_SRC, 'pk_host_fx.c'), os.path.join(HOST_SRC, 'pk_host_fx_defaults.c')]
        origin = p.cave_origin('m4')
        lo, hi = axi_gap(sym)
        try:
            blob, self.syms = cbuild.build('m4', srcs + self.sources, self.include_dirs,
                                           os.path.join(p.build_dir, 'm4host'), origin, 'pk4_boot', sym,
                                           ram=(RAM_BASE, RAM_END - RAM_BASE), axi=(lo, hi - lo),
                                           defines=self.defines,
                                           extra_headers={k: v() if callable(v) else v
                                                          for k, v in sorted(self.headers.items())},
                                           extra_sources={'pk_host_gen.c': self.gen_source(),
                                                          'pk_host_chains.c': hooks.gen_source(
                                                              chains, nxt, self.events, 'pk_host_magic', PK_HOST_MAGIC)})
        except cbuild.BuildError as e:
            unreg = hooks.unregistered(e)
            if unreg:
                raise HostError(f'{", ".join(unreg)}: call PK_NEXT but are not registered as hooks '
                                '(h.redirect_call / redirect_branch / replace_word)') from None
            raise
        for v in [v for _, _, v in self.toggles] + [v for _, v in self.settings]:
            if v not in self.syms:
                raise HostError(f'setting variable {v} is not defined (uint8_t {v}; in a mod source)')
        assert p.append('m4', blob, f'M4 host + mods ({len(blob)} B)', align=16) == origin
        for (src, section), size in cbuild.ram_sections(os.path.join(p.build_dir, 'm4host')).items():
            owner = f'{os.path.relpath(src, ROOT)}:{section}'
            p.ram_use('store' if section.startswith('.pk_axi') else 'main', owner, (size + 3) & ~3)   # placed by the linker

        s = self.syms
        p.redirect_call('m4', 'boot_init.call_config_files_init', s['pk4_boot'],
                        'boot: zero patch RAM, mod inits, load device.json, then system/mods.json')
        p.replace_word('m4', 'sbrk.limit_literal', RAM_BASE + int(sym.raw['heap']['min_stack'], 16),
                       '_sbrk: cap M4 heap below patch RAM')
        if self.toggles or self.settings or self.savers:
            for site in SAVE_SITES:
                p.redirect_branch('m4', site, s['pk4_device_json_save'],
                                  f'{site.split(".")[0]}: save device.json, then the mods\' settings')
        if self.toggles:
            p.replace_word('m4', 'cfg_page.event_word', s['pk4_cfg_event'] | 1, 'config page events -> toggles')
            p.replace_word('m4', 'cfg_page.render_word', s['pk4_cfg_render'] | 1, 'config page LEDs -> toggles')
        if self.use_fx:
            proc = s['pk4_fx_process'] | 1
            p.replace_word('m4', 'fx.fnptr_initial', proc, 'FX process pointer (initial) -> pk4_fx_process')
            p.replace_word('m4', 'fx_set_processor.normal_literal', proc,
                           'FX process pointer (normal mode) -> pk4_fx_process')
        hooks.apply(p, 'm4', chains, data, s)
        p.cave_symbols = getattr(p, 'cave_symbols', {})
        p.cave_symbols['m4host'] = s
