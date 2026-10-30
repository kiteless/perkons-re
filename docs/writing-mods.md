# Writing a mod

How to go from an idea to a mod that builds, passes the emulator, shows up in the Mod
Matrix and can be flashed. Mods live in their own repository (here: `perkons-re-mods`),
one folder per mod; this framework holds no mod specifics.

Read first: [architecture.md](architecture.md) (what the firmware looks like inside),
[process.md](process.md) (RE → patch → emulate → hardware; flashing and recovery).

## 0. Ground rules

* **Emulator first, hardware last**, one small change per hardware step. Every build must
  pass the voice regression (`make build` does it) before it goes near the unit.
* **No addresses outside `symbols/`.** Patches name functions, globals, sites, offsets and
  constants; C code gets them as `SYM_` / `OFF_` / `CONST_` / `SITE_` defines. That's what
  makes a mod portable to the next firmware ([porting.md](porting.md)).
* **No Erica content in git**: no `.img`, decompiled output, built images, renders or samples.
* Supported base firmware: **1.3.0** (the only `symbols/v*-m7.json`).

## 1. Find the hook (RE)

```sh
make unpack && make ghidra                          # once per firmware version
ghidra/query.sh v1.3.0 m4 myname 'str:SOME STRING'  # who uses it? -> pseudo-C in ghidra/out/
ghidra/query.sh v1.3.0 m4 myname addr:0x1000080c    # who reads/writes this address?
ghidra/query.sh v1.3.0 m4 myname fn:0x08107dc0      # decompile one function
```

Which core: **M7** = voice engines and the audio DMA for the voices; **M4** = UI, keys,
LEDs, pots, SD card, JSON config, MIDI, the FX (BBD) path. They talk through IPC rings
(architecture.md).

Record what you find in `symbols/v1.3.0-<core>.json`:

| section | for | example |
|---|---|---|
| `functions` | calling firmware code | `"fx_lfo_led_pwm": "0x08107dc0"` |
| `globals` | firmware RAM / tables | `"cfg_dirty": "0x1002c7e4"` |
| `sites` | patch points: a `bl` (`call`), a literal (`word`) or a 4-byte instruction (`bytes`) | `"fx_lfo.call_led_pwm": {"addr": ..., "call": "fx_lfo_led_pwm"}` |
| `offsets` | struct fields | `"fx_bbd.feedback": "0x7c"` |
| `constants` | magic numbers (decimal unless `0x`) | `"fx_block_frames": "16"` |

Add a C declaration to `include/<core>/fw_<core>.h` for anything C will touch, and a
behavioural check to `tools/perkons/symcheck.py` where cheap (`make check-symbols`).
These are framework changes: commit them to this repo.

## 2. Create the mod folder

```
perkons-re-mods/my-mod/
  mod.json                 what the Mod Matrix offers (step 6)
  patches/my_mod.py        patch module(s)
  src/m4/my_mod.c          C (src/m7/ for the M7)
  lib/                     Python helpers shared by patches and tests (optional)
  tests/test_my_mod.py     emulator tests, run by `make test`
  README.md                what it does and how to use it (for users)
  docs/design.md           how it works, controls, RE findings
```

`make test`, `make build` and `make ui` find it through `PERKONS_MODS` (in the
framework's untracked `local.mk`: `PERKONS_MODS = ../perkons-re-mods`).

## 3. Write the patch module

```python
"""my-mod: one line on what it does. See docs/design.md."""
TARGET = 'v1.3.0'        # firmware it's written for (None = any)
SUMMARY = 'What it does, in one line'
RISK = 'medium'          # none | low | medium | high

def apply(p, arg=None):  # arg: text after ':' in `my_mod:arg`
    ...
```

### M4 mods: use the M4 host (preferred)

Boot, the config page, settings saving, the FX process pointer and patch RAM can each be
patched only once, so M4 mods **register with the host** instead of patching them
(`tools/perkons/m4host.py`, `include/m4/pk_host.h`). The host links all M4 mods in one
build, whatever order they're applied in, so features can be combined freely:

```python
import os
from perkons import m4host

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'm4')

def apply(p, arg=None):
    h = m4host.host(p)
    h.add([os.path.join(SRC, 'my_mod.c')], [SRC], init='pk_my_mod_init')  # init runs at boot
    h.toggle(45, 'my-mod', 'pk_cfg_my_mod')   # config key (LED shows it), mods.json bool, uint8_t
    h.fx()                                    # only if it takes part in the FX chain
    h.redirect_call('fx_update.call_read_switch', 'pk_my_hook', 'why')   # own hook points
```

In C, use ordinary globals: both RAM areas are zeroed at boot. Where they go:

| RAM | how | size, speed | for |
|---|---|---|---|
| patch RAM (D2 SRAM) | plain globals (`.bss`) | 64 KB + 256 B, half of it the shared 32 KB FX buffer; fast | what the audio path touches per sample: buffers, positions, filter states |
| AXI SRAM gap | `PK_AXI uint8_t pk_cfg_my_mod;` | ~111 KB; a few cycles slower per access | settings, control-rate state, bulk data |

The Mod Matrix shows these as **MAIN** and **STORE** (and the M7's as **VOICE**, below):
the M4 host records every RAM variable it links, a combination that doesn't fit can't be
ticked, and the build refuses it (`tools/perkons/ram.py`). Never M7 DTCM (the M4 can't reach it), and never share `PK_AXI` data with the M7 (its
data cache may not see M4 writes); use the IPC streams. FX mods override weak hooks (`pk_fx_engine`, `pk_fx_delay`,
`pk_fx_freeze_engaged`, `pk_fx_switch_is_freeze`, `pk_fx_reset`) and share the 32 KB
`pk_fx_buf`. See `fx-reverb` and `fx-freeze` for a pair that builds alone or together.

Config keys in use: **row 3 step 15 (key 46)** fx-reverb, **step 16 (key 47)** fx-freeze.
Free keys (v1.3.0): row 1 steps 4, 13; row 2 steps 14–16; row 3 steps 10–14; row 4 steps 2–14.
Clashing keys or setting names fail the build. Toggles are saved in `system/mods.json`,
never in the stock `device.json`: new settings go in new files, so deleting them gives
stock behaviour.

### M7 mods: direct patching (no host yet)

Compile with `cbuild.build('m7', ...)` at `p.cave_origin('m7')`, `p.append()` the blob,
then `p.redirect_call` / `p.replace_with_call` / `p.replace_word` at named sites. State
lives at fixed RAM addresses (the cave has no startup code; `.data`/`.bss` are refused)
in the **VOICE** area (`ram.areas()`: v1.3.0 0x2000c000–0x2001f000, M7 DTCM between the
newlib heap cap and a 4 KB stack reserve). Record the range with
`p.ram_use('voice', 'my_mod', size, addr)`: the build refuses ranges outside the area or
overlapping another mod's, and the Mod Matrix counts it. voice-map takes 64.25 KB of it.
See `voice-map` and `patches/example_hook.py`. Only one M7 mod can claim the `_sbrk` cap
today (voice-map does).

### A new voice engine: add it to voice-map

A voice engine for any output is an extra voice-map engine, like `zibens`: a
`cVoice`-compatible C object (the stock field offsets, a 4-method vtable) built in an
output's arena by a `build(obj, out)` function your patch registers in
`p.shared['voice_map']['engines'][N]` with a free engine number N (5-15) and a `name`;
users select it by that name in `voices.json` (`"voice3": "my-engine"`). Mark it `"requires": ["voice-map"]` in mod.json.

### C rules (both cores)

`-Os`, freestanding, no libc. Functions named `pk*` are kept as hook targets. Call
firmware functions through the `fw_*` macros in `fw_<core>.h`. Keep per-sample work
small: the M4 FX path has ~5000 cycles per frame and the stock delay uses 75–490
instructions; measure with the emulator (`count_insns`).

## 4. Test in the emulator

`tests/fixtures.py` (framework) gives `require_image('v1.3.0')` and
`build_patched(stock, ['my_mod'], build_dir)` → `(image, patcher)`; the M4 host's
symbols are in `patcher.cave_symbols['m4host']`. Harnesses in `tools/perkons/emu.py`:

| class | runs | use for |
|---|---|---|
| `M7Emu` | one voice engine, `render()` per sample | voice DSP |
| `M7System` | `main()`'s wiring, message loop, audio DMA callback | M7 patches |
| `M4Emu` | M4 code with a virtual SD card (`sd={'system/device.json': b'...'}`) | config, JSON, boot hooks |
| `M4FX` | `fx_init`, SAI3 DMA callbacks, `fx_update`; knobs + switch from Python | FX mods (fails on writes outside the output block) |

Minimum tests for a mod: **off = bit-identical to stock**, the feature does what it says,
extremes don't clip or blow up, settings load from their file, and (if it can be combined
with others) a build with them. `make test` runs everything (~5 minutes; emulator-heavy).

## 5. Build and listen

```sh
make build PATCHES='my_mod'               # builds/my_mod.img + voice regression (36 renders)
make build PATCHES='fx_reverb my_mod'     # combinations
```

Render audio from tests or a scratch script (`verify.render_output`, `M4FX.process`) and
write WAVs to `out/` (gitignored) to listen before hardware.

## 6. Offer it in the Mod Matrix

`my-mod/mod.json` (format in `tools/perkons/catalog.py`):

```json
{
  "options": [
    {
      "id": "my-mod",
      "title": "MY MOD",
      "summary": "What the user gets, in one or two sentences.",
      "patches": ["my_mod"],
      "code": "mm",
      "conflicts": [],
      "requires": []
    }
  ]
}
```

`code` is two letters for the build tag in `INFO.TXT` (taken: vm, rv, fz, zb). `requires` lists option ids that must be in the same build (the Mod Matrix ticks
them along). Only list user-facing options; development patches stay out. `make ui` to check it appears.

Give the mod a user-facing `README.md`: what it does, how to use it, and a "Getting it"
section pointing to perkons-re's [Get modded firmware](../README.md#get-modded-firmware)
guide (no firmware files are ever provided).

## 7. Hardware

Follow process.md: official firmware on the card as the way back, flash the build
(`perkons_v1.3.0-0-force.img` in the SD root), one change at a time.

## 8. Release

A release definition in `perkons-re-mods/releases/*.json` (see `tools/release.py`) names
the patches and a tag; `make release REL=...` builds, stamps and records the commits.
