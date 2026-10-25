# Porting to a new official firmware

When Erica Synths releases a new firmware, mods built on this framework need a symbols
file for it. Patches and C code refer only to *names* (functions, globals, struct
offsets, patch sites; see `symbols/`), so a port is mostly producing
`symbols/<new>-{m4,m7}.json`. The tooling does most of that and tells you exactly what's left.

## Workflow

```sh
# 1. get the official image into the repo root (gitignored), then
make unpack IMG=perkons_vX.Y.Z-0-force.img VER=vX.Y.Z
make ghidra VER=vX.Y.Z                # analysis + function list export
make ghidra VER=v1.3.0                # (once) the version you port from

# 2. port and check
make port FROM=v1.3.0 TO=vX.Y.Z       # writes symbols/vX.Y.Z-*.json + ghidra/out/vX.Y.Z/port-report.md
                                      # then runs the behavioural checks on the result

# 3. fix what's left (report lists every UNPORTED value and every failed check), in Ghidra
make check-symbols IMG=perkons_vX.Y.Z-0-force.img VER=vX.Y.Z

# 4. mods: build against the new base and run their tests
make build IMG=perkons_vX.Y.Z-0-force.img SYMS=symbols/vX.Y.Z-m7.json PATCHES=...
```

Then the usual hardware steps: `tag_build` first, then the mod (see process.md).

## How the porter works (`tools/perkons/port.py`, `probes.py`)

**Function matching**, strongest evidence first:

1. **Fingerprints**: each function's instruction stream with addresses abstracted
   (branch targets, literal-pool addresses), strings kept *as text*, constants kept.
   Unique exact matches between the two images.
2. **Anchors**: C++ RTTI (class name → vtable → methods by index) and the vector table.
3. **Propagation**: inside each matched pair, instructions in blocks that match token
   for token (register-agnostic, since compilers allocate registers differently) vote on
   callees and on the addresses they load. Votes are weighted by how long the matching
   block around them is. Function-pointer literals in the same order, and tables of
   function pointers at corresponding addresses (`.init_array`), also vote.
4. **Fuzzy**: best remaining similarity, with a clear margin over the runner-up.

Functions Ghidra didn't create (reached only through data pointers, or merged with a
neighbour) are created on demand by decoding from the entry point.

**Values**:

* functions: from the function map
* globals / memory / data: from literal-pool votes; else "same literal value in the
  matched function" (unchanged); else nearest literal + same offset (a guess the probes
  and checks then verify)
* sites and main_points: aligned instruction in the matched function, else a coarse
  instruction window searched inside the counterpart function, else across the image.
  A site is **rejected** unless the instruction there is what the site promises
  (`bl <fn>`, exact bytes, literal value), so a wrong site can't slip through.

**Probes** (`probes.py`) then *measure* what the emulator can observe instead of trusting
the guesses: the slots array, `params`, `cVoice.*` offsets (call each setter, see which
byte changes), sub-object offsets (find their vtable pointers), P2-config and
sample-pointer offsets (send the real config messages through `main`), slot extents.

**Checks** (`symcheck.py`, `make check-symbols`) are the acceptance test: each runs
firmware code in the emulator and verifies the effect: wiring produces the four voice
classes, setters change the right byte, every voice renders, `main` runs from its entry
and handles messages, the M4 IPC/JSON/snprintf work, every patch site holds what it should.

## Rehearsal on real version differences

Porting the hand-made 1.3.0 symbols *backwards* exercises the porter against real
compiler and code changes (1.3.0 was built with GCC 15, 1.2.1 with GCC 12):

| port | checks | what fails, and why |
|---|---|---|
| 1.3.0 → 1.3.0 | 14/14 | n/a (reproduces every value exactly) |
| 1.3.0 → 1.2.1 | 11/14 | runtime sample loading + the patch sites that hook it: 1.2.1 has no per-bank samples |
| 1.3.0 → 1.1.1 | 10/14 | the same, plus "Sampler P2 config", which 1.1.1 doesn't have |
| 1.3.0 → 1.2.2 | 11/14 | as 1.2.1 (bug-fix release of 1.2). First port to a release the tooling had never seen: 12 s, P2-config offset found by probe at +0x2c59 |

Along the way the probes caught real layout changes the matcher alone would have got
wrong (`slots` at 0x200001e0 in 1.1.1, `params` and the voice-4 sub-objects moved in
1.2.1). `tests/test_port.py` keeps the self-port and the 1.2.1 port honest.

## When the porter can't help

If a new release *rewrites* the code a mod hooks (rather than recompiling it), the
report will show those sites as rejected and the checks as failing. That's where manual
reverse engineering starts: `ghidra/query.sh` and `ghidra/decompile.sh` on the new
version, comparing with the old one.
