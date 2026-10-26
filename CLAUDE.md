# perkons-re: notes for Claude Code

Reverse-engineering / modding framework for the Erica Synths Pērkons HD-01 (STM32H7:
M7 = voice engines, M4 = UI/SD/config/MIDI/FX). Owner: Will Baker (GitHub `kiteless`).
Mods live in the sibling repo `../perkons-re-mods` (see its CLAUDE.md), linked by the
untracked `local.mk` (`PERKONS_MODS = ../perkons-re-mods`).

## Rules from the owner

* **Ask before installing any software** (brew, pip, toolchains), with the reason.
* **No Claude attribution** in commits or PRs: no `Co-Authored-By: Claude`, no
  "Generated with Claude Code". Plain messages, the owner's git identity only.
* **Commit and push only when asked.**
* **Never commit Erica content**: `.img` files, manuals/PDFs, `ghidra/out/` (decompiled),
  `builds/`, `out/` (renders), samples. Built images must not be shared (Erica's site T&C);
  hashes of official images are fine (`symbols/official-images.json`).
* Both repos are **private**; don't make them public unless asked.
* **This repo holds no mod specifics**: mod code goes in perkons-re-mods.
* Cautious phases: emulator first, hardware last, one small change per hardware step;
  reflash official firmware before any warranty service.
* Don't search outside `~/Projects` (a home-folder `find` triggered macOS privacy prompts).

## Where things are

* `README.md`: setup, Mod Matrix install/use, overview of tools
* `docs/writing-mods.md`: **start here for a new mod**
* `docs/architecture.md`: firmware internals (cores, IPC, voices, banks/JSON, config
  menu, FX/BBD, FX LFO); `docs/process.md`: workflow, emulators, flashing, recovery;
  `docs/porting.md`: moving to a new firmware version
* `symbols/v1.3.0-{m4,m7}.json`: the only place addresses live
* `tools/perkons/`: `fwimage`, `emu` (M7Emu, M7System, M4Emu, M4FX), `patch`, `cbuild`,
  `m4host` (shared M4 plumbing), `catalog` + `tools/modmatrix.py` + `ui/modmatrix/` (Mod
  Matrix web app), `port`, `verify`, `mods`

## Commands

```sh
make test          # framework + all mods, ~5 min (emulator-heavy; a sleeping Mac stalls it)
make test-fast     # container + patcher only
make build PATCHES='fx_reverb fx_freeze'   # builds/<name>.img + voice regression
make ui            # Mod Matrix at http://127.0.0.1:6464/ (UI_ARGS=--no-intro)
make release REL=../perkons-re-mods/releases/<name>.json
ghidra/query.sh v1.3.0 m4 <outname> addr:0x... | fn:0x... | 'str:...'
```

The Python is `.venv/bin/python` (capstone, unicorn); Arm GCC is `arm-none-eabi-gcc`
from Homebrew. Long runs: start them in the background and wait for the notification.

## State (2026-10-25)

* Supported base: firmware 1.3.0 only (porter rehearsed on 1.2.2 / 1.2.1 / 1.1.1).
* Mod Matrix: working on macOS (browser). Ideas, not started: native window via pywebview
  (needs install approval), packaged app (PyInstaller), shipping pre-compiled mod code so
  users need no compiler; equaliser to be driven by a MOD file the owner will supply
  (`EQ.source` hook in `ui/modmatrix/app.js`); Latvian letters (Ā Ē Ī Ū Č Š Ž Ķ Ļ Ņ Ģ)
  could be added to `font.js`. Linux/Windows untested.
* Mod status and open hardware tests: see `../perkons-re-mods/CLAUDE.md`.
