#!/bin/sh
# ghidra/query.sh <version> <core> <outname> <query>...   (see scripts/Query.java for query syntax)
#   ghidra/query.sh v1.3.0 m4 ipc addr:0x38000000 'str:SAMPLES'
set -e
VER=$1; CORE=$2; NAME=$3; shift 3
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HEADLESS=$(brew --prefix ghidra)/libexec/support/analyzeHeadless
[ -n "$JAVA_HOME" ] || export JAVA_HOME=$(sed -n 's/.*JAVA_HOME:-\([^}]*\)}.*/\1/p' "$(command -v ghidraRun)")
OUT="$ROOT/ghidra/out/$VER/$CORE/$NAME"
rm -rf "$OUT"
"$HEADLESS" "$ROOT/ghidra/projects" "perkons-$VER" -process "$CORE.bin" -noanalysis -readOnly \
  -scriptPath "$ROOT/ghidra/scripts" -postScript Query.java "$OUT" "$@" 2>&1 | grep -E "Query:|ERROR|Exception" || true
cat "$OUT/query.txt"
