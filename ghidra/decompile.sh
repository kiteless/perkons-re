#!/bin/sh
# Decompile functions from an analyzed project to ghidra/out/<version>/<core>/.
#   ghidra/decompile.sh v1.3.0 m7 wire_voices 0x08023ea4 ...    ("all" = every function)
set -e
VER=$1; CORE=$2; shift 2
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HEADLESS=$(brew --prefix ghidra)/libexec/support/analyzeHeadless
[ -n "$JAVA_HOME" ] || export JAVA_HOME=$(sed -n 's/.*JAVA_HOME:-\([^}]*\)}.*/\1/p' "$(command -v ghidraRun)")
OUT="$ROOT/ghidra/out/$VER/$CORE"
"$HEADLESS" "$ROOT/ghidra/projects" "perkons-$VER" -process "$CORE.bin" -noanalysis -readOnly \
  -scriptPath "$ROOT/ghidra/scripts" -postScript Decompile.java "$OUT" "$@" 2>&1 \
  | grep -E "Decompile|ERROR|Exception" || true
