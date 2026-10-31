# Writing a mod

How to go from an idea to a mod that builds, passes the emulator, shows up in the Mod
Matrix and can be flashed. Mods live in their own repository (here: `perkons-re-mods`),
one folder per mod; this framework holds no mod specifics.

This repo doesn't document the firmware's internals: find what you need with the tools
below (Ghidra, the emulator) and record it as symbols.

## 0. Ground rules

* **Emulator first, hardware last**, one small change per hardware step. Every build must
  pass the voice regression (`make build` does it) before it goes near the unit.
* **No addresses outside `symbols/`.** Patches name functions, globals, sites, offsets and
  constants; C code gets them as `SYM_` / `OFF_` / `CONST_` / `SITE_` defines. That's what
  makes a mod portable to the next firmware ([porting.md](porting.md)).
* **No RAM allocation decisions without asking the owner** (area, fixed ranges, buffers).
* **No Erica content in git**: no `.img`, decompiled output, built images, renders or samples.
* Supported base firmware: **1.3.0** (the only `symbols/v*-m7.json`).

## 1. Find the hook (RE)

```sh
make unpack && make ghidra                          # once per firmware version
ghidra/query.sh v1.3.0 m4 myname 'str:SOME STRING'  # who uses it? -> pseudo-C in ghidra/out/
ghidra/query.sh v1.3.0 m4 myname addr:0x<address>   # who reads/writes this address?
ghidra/query.sh v1.3.0 m4 myname fn:0x<address>     # decompile one function
```

Which core: **M7** = the voice engines; **M4** = UI, sequencer, SD card, config, MIDI
and the FX section. The M4 sends the M7 messages.

Record what you find in `symbols/v1.3.0-<core>.json`:

| section | for | example |
|---|---|---|
| `functions` | calling firmware code | `"fx_lfo_led_pwm": "0x…"` |
| `globals` | firmware RAM / tables | `"cfg_dirty": "0x…"` |
| `sites` | patch points: a `bl` (`call`), a literal (`word`, an expression over the symbols such as `"seq_tick\|1"`) or instructions by their text (`insn`, e.g. `"strb.w r3, [r2, #0xc6d]"`) | `"fx_lfo.call_led_pwm": {"addr": ..., "call": "fx_lfo_led_pwm"}` |
| `offsets` | struct fields | `"fx_bbd.feedback": "0x7c"` |
| `constants` | magic numbers (decimal unless `0x`) | `"fx_block_frames": "16"` |

Never store firmware bytes: a site names what it expects (a function, a symbol
expression, an instruction's text), and the bytes are read from the user's own image and
checked at build time (`perkons/insn.py`).

Firmware facts (functions, globals, offsets, and sites any mod could use) go in the
framework's file. A mod's own hook sites go in **its** `symbols/<version>-<core>.json`
(`sites` only, named `<mod>.<hook>.<addr>`): `perkons.emu.Symbols` merges every mod's file
into the framework's (an entry may add a name, never change one), and `make port` ports
them with it. Add a C declaration to `include/<core>/fw_<core>.h` (M4 panel, sequencer,
pattern and LFO layouts: `include/m4/fw_m4_seq.h`) for anything C will touch, and a
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
```

`make test`, `make build` and `make ui` find it through `PERKONS_MODS` (in the
framework's untracked `local.mk`: `PERKONS_MODS = ../perkons-re-mods`).

## 3. Write the patch module

```python
"""my-mod: one line on what it does."""
TARGET = 'v1.3.0'        # firmware it's written for (None = any)
SUMMARY = 'What it does, in one line'
RISK = 'medium'          # none | low | medium | high

def apply(p, arg=None):  # arg: text after ':' in `my_mod:arg`
    ...
```

### Both cores: hosts and hook chains

M4 and M7 mods register with their core's **host** (`m4host.py`, `m7host.py`), which links
every mod of a build in one cave and patches each hook point once. Several mods may hook
the same site: the host chains them (`tools/perkons/hooks.py`). A hook continues with
`PK_NEXT(itself)`, the next mod's hook or the stock function, declared with its own
prototype:

```c
int PK_NEXT(pk_my_key_event)(const uint8_t *evt);

int pk_my_key_event(const uint8_t *evt)
{
    if (evt[0] == FW_KEY_SHIFT && evt[1] == FW_EV_DOWN)
        ...;
    return PK_NEXT(pk_my_key_event)(evt);
}
```

Order: `order=` (default 0), then the hook's name. A hook used at several sites must have
the same next hook at each (the build says so otherwise). **Hooks only run once the host
has booted** (its RAM zeroed, the inits run); before that every hooked site goes straight
to stock, so nothing runs on power-on garbage (some firmware callbacks run before the
host boots, and without an SD card the M4 host never boots: then the unit is stock).

### M4 mods: use the M4 host

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
    h.redirect_call('fx_update.call_read_switch', 'pk_my_hook', 'why')   # hook points (chained)
    h.on('track_clear', 'pk_my_cleared')      # an event: void f(void), before the firmware does it
    h.store('pattern', 'MYMD', 'pk_my_save', 'pk_my_load')   # per-pattern data, sidecar file
```

Events (`m4host.EVENTS`): `track_clear`, `automation_clear`, `pattern_clear`; each is the
framework's `event.<name>.*` sites. **Per-pattern and per-kit data** (`h.store('pattern' |
'kit', tag, save, load)`) lives in sidecar files beside the stock ones, which stay stock:
`BANKS/NN/PP.PAX` and `BANKS/NN/KITS/PP.KIX`, one record per mod (`"PKX1"`, then `{tag[4],
u32 length, data}`; unknown tags skipped). `uint32_t save(int bank, int idx, uint8_t *buf,
uint32_t max)` gives the record when the pattern/kit is saved (0: none); `void load(int
bank, int idx, const uint8_t *rec, uint32_t len)` gets it after a bank load, for every
index, and after a clear (len 0: none). A record is at most 4 KB (the firmware's JSON
buffer is the file buffer).

In C, use ordinary globals: both RAM areas are zeroed at boot. Where they go:

| RAM | how | size, speed | for |
|---|---|---|---|
| **MAIN** | plain globals (`.bss`) | 64 KB + 256 B, half of it the shared 32 KB FX buffer; fast | what the audio path touches per sample: buffers, positions, filter states |
| **STORE** | `PK_AXI uint8_t pk_cfg_my_mod;` | ~111 KB; a few cycles slower per access | settings, control-rate state, bulk data |

The Mod Matrix shows these (and the M7's **VOICE**, below) as memory meters:
the M4 host records every RAM variable it links, a combination that doesn't fit can't be
ticked, and the build refuses it (`tools/perkons/ram.py`). VOICE is the M7's (the M4
can't reach it); never share `PK_AXI` data with the M7 (its cache may not see M4
writes): send it a config message. FX mods override weak hooks (`pk_fx_engine`, `pk_fx_delay`,
`pk_fx_freeze_engaged`, `pk_fx_switch_is_freeze`, `pk_fx_reset`) and share the 32 KB
`pk_fx_buf`. See `fx-reverb` and `fx-freeze` for a pair that builds alone or together.

Config keys in use: **row 3 step 15 (key 46)** fx-reverb, **step 16 (key 47)** fx-freeze.
Free keys (v1.3.0): row 1 steps 4, 13; row 2 steps 14–16; row 3 steps 10–14; row 4 steps 2–14.
Clashing keys or setting names fail the build. Toggles are saved in `system/mods.json`,
never in the stock `device.json`: new settings go in new files, so deleting them gives
stock behaviour.

### M7 mods: use the M7 host

```python
from perkons import m7host

def apply(p, arg=None):
    h = m7host.host(p)
    h.add([os.path.join(SRC, 'my_engine.c')], [SRC], init='pk_my_init')   # at boot
    h.message('my-msg', 'pk_my_msg')          # config message: void f(const uint8_t *, uint32_t)
    h.redirect_call('some.site', 'pk_my_hook', 'why')                      # chained
```

The host owns the M7's boot step (once the stock voices are set up: the M7 mods' RAM
zeroed, then their inits), the config messages the firmware doesn't know (dispatched by
type) and the heap cap. Message types are given out by name (`m7host.message_types`) and
are `PK_MSG_<NAME>` in both cores' builds, so the M4 side sends what the M7 side
expects. `.bss` goes in a 4 KB part of the **VOICE** area; a mod with a fixed range
records it with `p.ram_use('voice', 'my_mod', size, addr)`. Include `pk7_host.h`.

### A new voice engine: add it to voice-map

A voice engine for any output is an extra voice-map engine, like `voice-slinks`: a
`cVoice`-compatible C object (the stock field offsets, a 4-method vtable) built in an
output's arena by a `build(obj, out)` function your patch registers by name,
`p.shared['voice_map']['engines']['my-engine'] = {'sources': [...], 'include_dirs': [...],
'build': 'pk_my_build'}`; users select it by that name in `voices.json` (`"voice3":
"my-engine"`), and voice-map numbers the engines itself. Mark it `"requires":
["voice-map"]` in mod.json.

### C rules (both cores)

`-Os`, freestanding, no libc. Functions named `pk*` are kept as hook targets. Call
firmware functions through the `fw_*` macros in `fw_<core>.h`. Keep per-sample work
small; measure with the emulator (`count_insns`).

## 4. Test in the emulator

`tests/fixtures.py` (framework) gives `require_image('v1.3.0')` and
`build_patched(stock, ['my_mod'], build_dir)` → `(image, patcher)`; the M4 host's
symbols are in `patcher.cave_symbols['m4host']`. Harnesses in `tools/perkons/emu.py`:

| class | runs | use for |
|---|---|---|
| `M7Emu` | one voice engine, `render()` per sample | voice DSP |
| `M7System` | the M7 program's own start-up, message loop and audio callback | M7 patches |
| `M4Emu` | M4 code with a virtual SD card (`sd={'system/device.json': b'...'}`) | config, JSON, boot hooks |
| `M4FX` | the M4's FX path as on the unit; knobs + switch from Python | FX mods (fails on writes outside the output block) |
| `rig.M4Rig` | a booted M4 (sequencer set up, host booted) with a virtual panel: held keys and steps, knobs and their moved flags, LEDs, key events | UI / sequencer mods |

The emulated SD card (`sd={path: bytes}`) has folders (implied by the files in them),
`f_opendir` / `f_readdir`, `f_unlink`; `rig.stub_hardware(e, sym)` gives any harness the
hardware stubs (SD card present, copies done directly, analog outputs silent).

Minimum tests for a mod: **off = bit-identical to stock**, the feature does what it says,
extremes don't clip or blow up, settings load from their file, and (if it can be combined
with others) a build with them. If a hook reads firmware state that isn't a call argument
(a register kept across the call, a stack slot), test that the stock code still does it,
so a port to new firmware catches a change. `make test-fast` applies every mod's options
together without building (`tests/test_mod_clashes.py`): clashing ids, build codes, config
keys, settings, messages or engine names fail there. `make test` runs everything (~5 minutes; emulator-heavy).

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

`code` is two letters for the build tag in `INFO.TXT` (taken: vm, rv, fz, sl, et, lf). `requires` lists option ids that must be in the same build (the Mod Matrix ticks
them along). Only list user-facing options; development patches stay out. `make ui` to check it appears.

Give the mod a user-facing `README.md`: what it does, how to use it, and a "Getting it"
section pointing to perkons-re's [Get modded firmware](../README.md#get-modded-firmware)
guide (no firmware files are ever provided).

## 7. Hardware

Keep the official firmware ready as the way back, flash the build
(`perkons_v1.3.0-0-force.img` in the SD root, as in the README), one change at a time.

## 8. Release

A release definition in `perkons-re-mods/releases/*.json` (see `tools/release.py`) names
the patches and a tag; `make release REL=...` builds, stamps and records the commits.
