"""M7 host (tools/perkons/m7host.py): boot after wire_voices, config messages by name,
chained hooks. Needs arm-none-eabi-gcc."""
import os
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import catalog, m4host, m7host, ram, verify
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.patch import PatchError, Patcher

DEMO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'm7host_demo.c')


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestM7Host(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.s4, cls.s7 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json')), Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-m7host-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, extra=None):
        p = Patcher(self.stock)
        p.symbols = {'m7': self.s7, 'm4': self.s4}
        p.build_dir = tempfile.mkdtemp(dir=self.tmp)
        h = m7host.host(p)
        h.add([DEMO], init='pk7_demo_init')
        h.message('zz-demo', 'pk7_demo_msg')
        if extra:
            extra(p, h)
        return p, p.result(), p.cave_symbols['m7host']

    def test_boot_runs_inits_and_voices_are_stock(self):
        p, img, s = self.build()
        e = verify.boot(img, self.s7)
        self.assertEqual(e.r32(s['pk7_demo_inited']), 0x600d)
        self.assertEqual(verify.engine_map(img, self.s7), [0, 1, 2, 3])

    def test_messages_by_name(self):
        p, img, s = self.build(lambda p, h: h.message('aa-other', 'pk7_demo_msg'))
        self.assertEqual(m7host.message_types(p), {'aa-other': 4, 'zz-demo': 5})
        self.assertEqual(m7host.message_defines(p)['PK_MSG_ZZ_DEMO'], '5')
        e = verify.boot(img, self.s7)
        e.send(3, 5, b'\x2a\x00\x00')
        e.pump()
        self.assertEqual(e.r32(s['pk7_demo_got']), 0x2a | 3 << 8)

    def test_message_defines_reach_the_m4(self):
        def m4(p, h):
            hm = m4host.host(p)
            hm.add([os.path.join(os.path.dirname(DEMO), 'm4host_demo.c')], init='pk_demo_init')
        p, img, s = self.build(m4)
        self.assertEqual(p.m4host.defines.get('PK_MSG_ZZ_DEMO'), '4')

    def test_chained_render_hook(self):
        def hook(p, h):
            h.add([], defines={'PK7_DEMO_RENDER': '1'})
            h.redirect_call('cFourthSlot_render.call_crush_render', 'pk7_demo_render', 'demo')
        p, img, s = self.build(hook)
        stock = verify.render_output(self.stock, self.s7, 3, 1, 1, n=2000)     # algo 1 mode 1: noise crush
        mod = verify.render_output(img, self.s7, 3, 1, 1, n=2000)
        self.assertEqual(stock, mod)
        e = verify.boot(img, self.s7)
        e.send_voice_state([{'params': [2048] * 4}] * 3 + [{'params': verify.DEFAULT_PARAMS, 'algo': 1, 'mode': 1}])
        e.pump()
        e.send_triggers([o == 3 for o in range(4)], [(0, 0)] * 3 + [(1, 1)])
        e.audio(50)
        self.assertGreater(e.r32(s['pk7_demo_renders']), 0)

    def test_ordered_message_is_handled_before_the_triggers_after_it(self):
        p, img, s = self.build(lambda p, h: h.message('aa-ord', 'pk7_demo_msg', ordered=True))
        self.assertEqual(m7host.message_defines(p)['PK_STREAM_AA_ORD'], '2')
        self.assertEqual(m7host.message_defines(p)['PK_STREAM_ZZ_DEMO'], '3')
        e = verify.boot(img, self.s7)
        e.send(2, 4, b'\x07')
        e.send_triggers([1, 0, 0, 0], [(0, 0)] * 4)
        out = e.audio(2000)[0]
        self.assertEqual(e.r32(s['pk7_demo_got']), 7 | 1 << 8)
        self.assertGreater(max(map(abs, out)), 300, 'the trigger behind it still plays')

    def mod_source(self, name, words):
        """A mod's source with `words` words of RAM."""
        src = os.path.join(self.tmp, f'{name}.c')
        with open(src, 'w') as f:
            f.write(f'#include <stdint.h>\nvolatile uint32_t {name}_ram[{words}];\n'
                    f'void {name}_init(void) {{ {name}_ram[0] = 1; }}\n')
        return lambda p, h: h.add([src], init=f'{name}_init')

    def test_ram_of_two_mods_adds_up(self):
        def voice(extra=None):
            return {k: size for k, (_, size) in self.build(extra)[0].ram['voice'].items()}
        base, a, b = voice(), voice(self.mod_source('aa', 16)), voice(self.mod_source('bb', 32))
        memory = {'areas': {'voice': {}}, 'options': {'a': {'voice': a}, 'b': {'voice': b}}}
        self.assertEqual(catalog.ram_used(['a', 'b'], memory)['voice'], sum(base.values()) + 4 * (16 + 32))

    def test_ram_ranges_are_where_the_linker_put_them(self):
        p, _, s = self.build()
        own = p.ram['voice']
        magic = next(v for k, v in own.items() if k.endswith(':.bss.pk7_host_magic'))
        self.assertEqual(magic[0], s['pk7_host_magic'])
        self.assertIsNone(ram.check(p.ram, p.symbols))

    def test_fixed_range_over_the_hosts_ram_refused(self):
        def clash(p, h):
            p.ram_use('voice', 'clash', 4, ram.areas(p.symbols)['voice'][1] - m7host.HOST_RAM)
        with self.assertRaisesRegex(PatchError, 'overlap'):
            self.build(clash)

    def test_same_message_two_handlers_refused(self):
        with self.assertRaises(m7host.HostError):
            self.build(lambda p, h: h.message('zz-demo', 'pk7_demo_other'))
