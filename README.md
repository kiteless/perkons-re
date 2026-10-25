# perkons-re

Reverse-engineering and modding framework for the **Erica Synths Pērkons HD-01** firmware:
unpack/repack update images, analyse both cores in Ghidra, run the real firmware code in
an emulator, and build patched firmware (byte patches or C code) with automatic
regression checks against stock.

> Unofficial. Not affiliated with Erica Synths. Flashing modified firmware is at your
> own risk; read [docs/process.md](docs/process.md) first (flashing, recovery, safety).
> No firmware binaries are distributed here: bring the official update files.

## What's here

| path | |
|---|---|
| `tools/fwtool.py` | inspect / unpack / repack / verify `.img` update files |
| `tools/thumbdis.py`, `tools/xref.py` | Thumb-2 disassembly with literal annotation; find references to an address |
| `tools/render_voices.py` | emulate the M7 DSP and render every stock voice/algo/mode to WAV |
| `tools/build.py` | apply patches → `.img`, then check every output against stock in the emulator |
| `tools/release.py` | versioned release: patches + `version_stamp`, regression, image + `RELEASE.md` with exact commits |
| `tools/run_tests.py` | framework tests + mod tests |
| `tools/perkons/` | library: `fwimage` (container), `emu` (`M7Emu`, `M7System`, `M4Emu` + virtual SD card), `patch` (guarded byte patches), `cbuild` (C → code cave), `verify` (behavioural checks), `mods` (out-of-tree patches) |
| `include/m4`, `include/m7` | C headers describing the firmware for patch code |
| `patches/` | `tag_build` (string-only smoke test), `example_hook` (template C patch), `version_stamp` (identify a build in `INFO.TXT` + boot banner) |
| `symbols/` | per-version addresses and structures (read by the emulator, C builds and Ghidra) |
| `ghidra/` | headless import + analysis, decompile, and "who references X" query scripts |
| `docs/architecture.md` | what the firmware looks like inside (both cores, IPC, voice engine, banks/JSON, FX) |
| `docs/process.md` | the RE → patch → emulate → hardware workflow; flashing, recovery and safety |

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

Start from `patches/example_hook.py` + `patches/src/m7/example_hook.c`. A patch module
declares `TARGET` (firmware version), `SUMMARY`, `RISK` and `apply(p, arg=None)`; every
byte it changes states the bytes it expects to replace, so it can't apply to the wrong
firmware. C code is compiled into a cave after the segment by `perkons.cbuild`.

Mods can live outside this repo. Point `PERKONS_MODS` at a mod directory (or a directory
of mods), e.g. in an untracked `local.mk`:

```make
PERKONS_MODS = ../my-mods
```

A mod has `patches/` (patch modules), optionally `src/<core>/` (C), `lib/` (Python
helpers) and `tests/` (picked up by `make test`). `make build PATCHES=my_patch:arg` finds
patches in either place. See `tools/perkons/mods.py`.

## Releases

A release definition (JSON, see `tools/release.py`) names the base firmware, the patches
and a version tag. `make release REL=path/to/release.json` builds it with
`version_stamp`, runs the regression and writes `builds/releases/<name>-<version>/` with
the image (official file name) and a `RELEASE.md` recording the base firmware and the
exact commits used. A stamped unit shows the tag in `INFO.TXT` on its SD card
(`… version: 1.3.0 - <tag>`).

## License

MIT, see [LICENSE](LICENSE). Covers the code and documentation in this repository only.
