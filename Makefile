PY      ?= .venv/bin/python
IMG     ?= perkons_v1.3.0-0-force.img
SYMS    ?= symbols/v1.3.0-m7.json
OUT     ?= out
PATCHES ?= tag_build
NAME    ?= $(subst :,-,$(subst $(space),+,$(PATCHES)))
VER     ?= v1.3.0
CORE    ?= m7
FN      ?= main
space   := $(subst ,, )

# Untracked per-machine settings, e.g. `PERKONS_MODS = ../my-mods`
-include local.mk
export PERKONS_MODS

.PHONY: help setup tools-check test test-fast test-framework render build release unpack ghidra decompile check-symbols port ui

help:
	@echo "make setup                          create .venv and install pinned deps"
	@echo "make tools-check                    show versions of external tools (Ghidra, Arm GCC)"
	@echo "make test                           framework tests + mod tests (needs official .img files)"
	@echo "make test-framework                 framework tests only"
	@echo "make test-fast                      container + patcher tests only"
	@echo "make unpack                         unpack \$$(IMG) to firmware/unpacked/\$$(VER)"
	@echo "make render                         render all stock voices of \$$(IMG) to \$$(OUT)/stock"
	@echo "make build PATCHES='a b:arg'        build builds/<patches>.img + emulator regression"
	@echo "make ui                             Mod Matrix: build modded firmware in the browser"
	@echo "make release REL=path/to/rel.json   versioned release folder (see tools/release.py)"
	@echo "make ghidra VER=v1.3.0              import + analyze both cores into ghidra/projects/"
	@echo "make check-symbols VER=v1.3.0       behavioural checks of symbols/<VER>-*.json"
	@echo "make port FROM=v1.3.0 TO=v1.4.0     port symbols to a new firmware (see docs/porting.md)"
	@echo "make decompile CORE=m7 FN='main 0x08023ea4'   pseudo-C into ghidra/out/"
	@echo
	@echo "mods (out-of-tree patches): PERKONS_MODS=$(PERKONS_MODS)"

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt

tools-check:
	@$(PY) --version
	@$(PY) -c "import capstone, unicorn; print('capstone', capstone.__version__, '| unicorn', unicorn.__version__)"
	@arm-none-eabi-gcc --version | head -1 || echo "arm-none-eabi-gcc: MISSING"
	@test -x "$$(command -v ghidraRun)" && echo "ghidra: $$(command -v ghidraRun)" || echo "ghidra: MISSING"
	@JH=$$(sed -n 's/.*JAVA_HOME:-\([^}]*\)}.*/\1/p' "$$(command -v ghidraRun)" 2>/dev/null); \
	  test -x "$$JH/bin/java" && echo "ghidra java: $$("$$JH/bin/java" -version 2>&1 | head -1)" || echo "ghidra java: MISSING"

test:
	$(PY) tools/run_tests.py

test-framework:
	$(PY) tools/run_tests.py --framework-only

test-fast:
	$(PY) tools/run_tests.py --fast

unpack:
	$(PY) tools/fwtool.py unpack $(IMG) firmware/unpacked/$(VER)

render:
	$(PY) tools/render_voices.py $(IMG) $(SYMS) $(OUT)/stock

build:
	@mkdir -p builds
	$(PY) tools/build.py $(IMG) builds/$(NAME).img $(PATCHES)

release:
	$(PY) tools/release.py $(REL)

ghidra:
	test -f firmware/unpacked/$(VER)/m7.bin || $(PY) tools/fwtool.py unpack $(IMG) firmware/unpacked/$(VER)
	ghidra/import.sh $(VER)

decompile:
	ghidra/decompile.sh $(VER) $(CORE) $(FN)

check-symbols:
	$(PY) tools/check_symbols.py $(IMG) --ver $(VER)

FROM ?= v1.3.0
port:
	$(PY) tools/port_symbols.py --from $(FROM) --to $(TO)

ui:
	$(PY) tools/modmatrix.py $(UI_ARGS)
