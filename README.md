# perkons-re

Reverse-engineering and modding framework for the **Erica Synths Pērkons HD-01** firmware:
unpack/repack update images, analyse both cores in Ghidra, run the real firmware code in
an emulator, and build patched firmware (byte patches or C code) with automatic
regression checks against stock.

> Unofficial. Not affiliated with Erica Synths. Flashing modified firmware is at your
> own risk; read [docs/process.md](docs/process.md) first (flashing, recovery, safety).
> No firmware binaries are distributed here: bring the official update files.

**Just want modded firmware for your Pērkons?** See [Mod Matrix](#mod-matrix): pick mods
with checkboxes and build from your own official image.

## What's here

| path | |
|---|---|
| `tools/fwtool.py` | inspect / unpack / repack / verify `.img` update files |
| `tools/thumbdis.py`, `tools/xref.py` | Thumb-2 disassembly with literal annotation; find references to an address |
| `tools/render_voices.py` | emulate the M7 DSP and render every stock voice/algo/mode to WAV |
| `tools/build.py` | apply patches → `.img`, then check every output against stock in the emulator |
| `tools/release.py` | versioned release: patches + `version_stamp`, regression, image + `RELEASE.md` with exact commits |
| `tools/check_symbols.py` | behavioural checks of a symbols file (each symbol does what we think, in the emulator) |
| `tools/port_symbols.py` | port symbols to another firmware version: matching + probes + checks + report |
| `tools/run_tests.py` | framework tests + mod tests |
| `tools/modmatrix.py`, `ui/modmatrix/` | **Mod Matrix**: pick mods with checkboxes, build modded firmware from your own official image in the browser |
| `tools/perkons/` | library: `fwimage` (container), `emu` (`M7Emu`, `M7System`, `M4Emu` + virtual SD card), `patch` (guarded byte patches), `cbuild` (C → code cave), `verify` (behavioural checks), `mods` (out-of-tree patches), `m4host` (shared M4 plumbing for mods), `catalog` (Mod Matrix options and image checks) |
| `include/m4`, `include/m7` | C headers describing the firmware for patch code |
| `patches/` | `tag_build` (string-only smoke test), `example_hook` (template C patch), `version_stamp` (identify a build in `INFO.TXT` + boot banner) |
| `symbols/` | per-version functions, globals, struct offsets and named patch sites; the only place addresses live (read by the emulator, C builds, patches and Ghidra) |
| `ghidra/` | headless import + analysis, decompile, and "who references X" query scripts |
| `docs/architecture.md` | what the firmware looks like inside (both cores, IPC, voice engine, banks/JSON, FX) |
| `docs/process.md` | the RE → patch → emulate → hardware workflow; flashing, recovery and safety |
| `docs/porting.md` | moving mods to a new official firmware: symbol porter, probes, checks, rehearsal results |
| `docs/writing-mods.md` | making a new mod, step by step |

## Setup

Prerequisites (macOS/Homebrew shown):

| tool | for | install |
|---|---|---|
| Python ≥ 3.9 | all tools | system / `brew install python` |
| Arm GNU GCC | compiling C patch code | `brew install arm-none-eabi-gcc arm-none-eabi-binutils` |
| Ghidra | interactive analysis, decompiler | `brew install ghidra` (brings its own Java) |

```sh
make setup          # .venv with pinned capstone + unicorn
make tools-check    # confirm everything is found
# put the official .img files in the repo root or firmware/ (they're gitignored)
make test           # ~10 s for the framework; skips tests whose firmware image is missing
make help           # everything else
```

## Quick start

```sh
make unpack                                   # firmware/unpacked/v1.3.0/{m4,m7}.bin
make ghidra                                   # analyze both cores (~40 s), then: ghidraRun
ghidra/query.sh v1.3.0 m4 samples 'str:SAMPLES'   # who uses this string? -> pseudo-C
make render                                   # out/stock/*.wav
make build PATCHES=example_hook               # builds/example_hook.img + regression check
```

## Writing a mod

Step by step, from RE to Mod Matrix to hardware: **[docs/writing-mods.md](docs/writing-mods.md)**.
The short version:

Start from `patches/example_hook.py` + `patches/src/m7/example_hook.c`. A patch module
declares `TARGET` (firmware version, or `None` for any), `SUMMARY`, `RISK` and
`apply(p, arg=None)`. Patch by **name**, never by address: `p.redirect_call(core, site,
...)`, `p.replace_with_call`, `p.replace_word`, with sites, offsets and constants from
`symbols/` (C code gets them as `SYM_`/`OFF_`/`CONST_` defines). Every write states the
bytes it expects to replace, so a patch can't apply to the wrong firmware, and a mod
written this way ports to a new firmware by porting its symbols (docs/porting.md).

Mods can live outside this repo. Point `PERKONS_MODS` at a mod directory (or a directory
of mods), e.g. in an untracked `local.mk`:

```make
PERKONS_MODS = ../my-mods
```

A mod has `patches/` (patch modules), optionally `src/<core>/` (C), `lib/` (Python
helpers) and `tests/` (picked up by `make test`). `make build PATCHES=my_patch:arg` finds
patches in either place. See `tools/perkons/mods.py`.

## Mod Matrix

A local app for building modded firmware: drop in the official `.img` you downloaded from
Erica Synths, tick the mods you want, press **SLOP IT UP**, and download the result. It
runs in your browser, served from your own computer (127.0.0.1 only); nothing is
uploaded anywhere.

### 1. Install the prerequisites

| | macOS | Linux (Debian/Ubuntu shown) | Windows |
|---|---|---|---|
| git | `xcode-select --install` | `sudo apt install git` | [git-scm.com](https://git-scm.com/) |
| Python ≥ 3.9 | included with the above, or `brew install python` | `sudo apt install python3 python3-venv` | [python.org](https://www.python.org/downloads/) (tick "Add to PATH") |
| Arm GCC (mods are compiled C) | `brew install arm-none-eabi-gcc arm-none-eabi-binutils` | `sudo apt install gcc-arm-none-eabi binutils-arm-none-eabi` | [Arm GNU Toolchain](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads) `arm-none-eabi` installer (tick "Add path to environment variable") |

Ghidra is not needed; it's only for reverse-engineering.

### 2. Get the framework and the mods, side by side

```sh
git clone https://github.com/kiteless/perkons-re
git clone https://github.com/kiteless/perkons-re-mods
cd perkons-re
```

### 3. Set up (once)

macOS / Linux:

```sh
make setup                                          # .venv with the pinned Python packages
echo 'PERKONS_MODS = ../perkons-re-mods' > local.mk  # where the mods are
make tools-check                                    # Python packages and Arm GCC found?
```

Windows (Command Prompt, no `make` needed):

```bat
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
arm-none-eabi-gcc --version
```

### 4. Run it

macOS / Linux:

```sh
make ui                         # opens http://127.0.0.1:6464/
make ui UI_ARGS=--no-intro      # skip the loader intro
```

Windows:

```bat
set PERKONS_MODS=..\perkons-re-mods
.venv\Scripts\python tools\modmatrix.py
```

Ctrl-C in the terminal stops it. Options: `--port N`, `--no-browser`, `--no-intro`.

### 5. Build and flash

1. Download the official firmware from Erica Synths (currently `perkons_v1.3.0-0-force.img`)
   and drop it on the page. Only an unmodified official image of a supported version
   unlocks the mods (it checks the header, the CRCs and the file's hash; see
   `symbols/official-images.json`).
2. Tick the mods. Each shows what it does and the firmware it needs.
3. **SLOP IT UP.** The build takes about a minute, most of it the emulator check that
   every voice still sounds exactly like stock.
4. Download `perkons_v1.3.0-0-force.img`, copy it to the root of the SD card under that
   name, and power on: the unit flashes itself. `INFO.TXT` on the card then shows the
   build tag (`1.3.0 - mm-…`). To go back, do the same with the official image.

Read [docs/process.md](docs/process.md) (flashing, recovery) before the first flash. A
built image contains Erica Synths' firmware: it's for your own device, don't share it.

### Adding a mod to it

Mods appear through a `mod.json` in the mod folder (see `tools/perkons/catalog.py`):
title, summary, the patch specs, a two-letter code for the build tag, and optional
`conflicts` (option ids that can't be combined). Target version and risk come from the
patch modules. Mods without a `mod.json` (and development patches not listed in one)
aren't offered.

## Releases

A release definition (JSON, see `tools/release.py`) names the base firmware, the patches
and a version tag. `make release REL=path/to/release.json` builds it with
`version_stamp`, runs the regression and writes `builds/releases/<name>-<version>/` with
the image (official file name) and a `RELEASE.md` recording the base firmware and the
exact commits used. A stamped unit shows the tag in `INFO.TXT` on its SD card
(`… version: 1.3.0 - <tag>`).

## License

MIT, see [LICENSE](LICENSE). Covers the code and documentation in this repository only.
