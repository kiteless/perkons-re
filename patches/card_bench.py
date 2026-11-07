"""Card bench: a test image measuring what a sampler streaming from the SD card needs to
know. Built with other mods, it measures them too (their saves and loads are timed with
the firmware's).

* D3 canary: the D3 SRAM no firmware code references (D3_GAP, 256 B clear of each
  neighbour) is filled with a pattern at power-on; the report says what changed since.
* How long the M4 is held by every pattern save, kit save, bank switch and sample load,
  and how often its main loop comes round (where streaming would refill its buffers).
* The card's speed: a large file (BENCH.WAV in the card root, else SAMPLES/1.wav) read in
  4 KB chunks straight through and at random places, and how long a file takes to open.

Whenever the firmware saves its settings (change any setting on a settings page and leave
it), BENCH.TXT on the card root has the results. Nothing else changes.
"""
import os

from perkons import m4host

TARGET = 'v1.3.0'
SUMMARY = 'Test image: D3 canary, save/load timing, SD card speed (BENCH.TXT)'
RISK = 'low'

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src', 'm4')

# D3 SRAM (0x38000000-0x3800ffff): the inter-core channels end at 0x38004500, the ADC DMA
# buffer starts at 0x3800fc00; 256 B clear of each
D3_GAP = (0x38004600, 0x3800fb00)
FIRST = -3000                       # before every other link: the timings cover the whole chain


def apply(p, arg=None):
    h = m4host.host(p)
    p.ram_borrow('store', 'json_buf', 'card_bench')                # the report goes out through it
    lo, hi = D3_GAP
    h.add([os.path.join(SRC, 'card_bench.c')], init='pk_bench_init', on_save='pk_bench_report',
          defines={'PK_D3_START': f'0x{lo:08x}u', 'PK_D3_END': f'0x{hi:08x}u'})
    sym = p.symbols['m4']
    for site in ('patpage.call_save_a', 'patpage.call_save_b'):
        h.redirect_call(site, 'pk_bench_pat_save', 'card bench: pattern save timed', order=FIRST)
    for site in sorted(k for k in sym.sites if k.startswith('kits.save.')):
        h.redirect_call(site, 'pk_bench_kit_save', 'card bench: kit save timed', order=FIRST)
    h.redirect_call('bank_menu.call_switch_bank', 'pk_bench_switch_bank', 'card bench: bank switch timed', order=FIRST)
    h.redirect_call('main.call_key_poll', 'pk_bench_loop', 'card bench: main loop passes timed', order=FIRST)
    for site in ('boot_init.call_load_samples', 'switch_bank.call_load_samples',
                 'boot_load_last_bank.call_load_samples'):
        h.redirect_call(site, 'pk_bench_load_samples', 'card bench: sample load timed', order=FIRST)
