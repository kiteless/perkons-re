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
* Both repos are **public** (since 2026-10-30): nothing copied from the firmware goes in
  them, not even single instructions or literals (sites name what they expect; the bytes
  come from the user's image at build time).
* **No testing details in anything pushed**: docs, READMEs, mod.json, commit messages and
  release notes never say how or whether something was tested (no status fields, hardware
  logs, "verified" notes, test counts). Pushed means tested.
* **This repo holds no mod specifics**: mod code goes in perkons-re-mods.
* **No RAM allocation decisions without asking**: which area (MAIN / VOICE / STORE) code
  uses, fixed ranges, reservations, buffer sizes, reusing firmware buffers. Propose with
  the numbers first.
* Cautious phases: emulator first, hardware last, one small change per hardware step;
  reflash official firmware before any warranty service.
* Don't search outside `~/Projects` (a home-folder `find` triggered macOS privacy prompts).

## Where things are

* `README.md`: setup, Mod Matrix install/use, overview of tools
* `docs/writing-mods.md`: **start here for a new mod**
* Firmware internals, process notes and the mods' design notes are **not** in this public
  repo: they live in the private sibling repo `../perkons-re-docs` (`architecture.md`,
  `process.md`, `porting-rehearsal.md`, `mods/<mod>/`). Keep public docs free of
  architectural detail (addresses, internal functions, layouts, RE findings).
* `docs/porting.md`: moving to a new firmware version
* `symbols/v1.3.0-{m4,m7}.json`: the only place addresses live (plus each mod's own
  `symbols/` file of hook sites, merged in by `Symbols`, ported with them)
* `tools/perkons/`: `fwimage`, `emu` (M7Emu, M7System, M4Emu with an SD card that has
  folders, M4FX), `patch`, `cbuild`, `m4host` / `m7host` (each core's shared plumbing:
  boot, settings, FX chain, events, sidecar storage, config messages) on `hooks` (chained
  hook points, `PK_NEXT`, boot guards), `rig` (M4Rig: a booted M4 with a virtual panel),
  `catalog` + `tools/modmatrix.py` + `ui/modmatrix/` (Mod Matrix web app), `port`,
  `verify`, `mods`
* `include/m4/fw_m4.h`, `fw_m4_seq.h` (panel, sequencer, patterns, LFO), `pk_host.h`;
  `include/m7/fw_m7.h`, `pk7_host.h`

## Commands

```sh
make test          # framework + all mods, ~5 min (emulator-heavy; a sleeping Mac stalls it)
make test-fast     # container + patcher + every mod registered together (clashes)
make build PATCHES='fx_reverb fx_freeze'   # builds/<name>.img + voice regression
make ui            # Mod Matrix at http://127.0.0.1:6464/ (UI_ARGS=--no-intro)
python3 start_modmatrix.py   # end users: sets up .venv, finds/clones the mods, starts the Mod Matrix
make release REL=../perkons-re-mods/releases/<name>.json
ghidra/query.sh v1.3.0 m4 <outname> addr:0x... | fn:0x... | 'str:...'
```

The Python is `.venv/bin/python` (capstone, unicorn); Arm GCC is `arm-none-eabi-gcc`
from Homebrew. Long runs: start them in the background and wait for the notification.

## State (2026-10-30)

* Supported base: firmware 1.3.0 only (porter rehearsed on 1.2.2 / 1.2.1 / 1.1.1).
* Mod Matrix: working on macOS (browser). MEMORY pane: MAIN / VOICE / STORE meters
  (`tools/perkons/ram.py`), out-of-memory mods can't be ticked. Ideas, not started: native window via pywebview
  (needs install approval), packaged app (PyInstaller), shipping pre-compiled mod code so
  users need no compiler; Latvian letters (Ā Ē Ī Ū Č Š Ž Ķ Ļ Ņ Ģ)
  could be added to `font.js`.
* Mods overview: see `../perkons-re-mods/CLAUDE.md`.
* Hosts on both cores: hook points chain (`PK_NEXT`), every hook is stock until its host
  has booted; M4 events (`track_clear`, `automation_clear`, `pattern_clear`), sidecar
  storage (`BANKS/NN/PP.PAX`, `KITS/PP.KIX`); M7 host owns boot, config messages, the
  heap cap and 4 KB of VOICE.
* After flashing, `INFO.TXT` on the card shows the build's `version_stamp` tag
  (`gd5b5810` = the official image).
