#!/bin/sh
# Import + auto-analyze both cores of a firmware version into a Ghidra project.
#   ghidra/import.sh v1.3.0          (expects firmware/unpacked/v1.3.0/{m4,m7}.bin; run `make unpack` first)
# Open afterwards with: ghidraRun  → File > Open Project > ghidra/projects/perkons-<version>.gpr
set -e
VER=${1:-v1.3.0}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HEADLESS=${GHIDRA_HEADLESS:-$(brew --prefix ghidra)/libexec/support/analyzeHeadless}
# Homebrew's ghidraRun wrapper pins the JDK; reuse it for headless runs
if [ -z "$JAVA_HOME" ]; then
  JAVA_HOME=$(sed -n 's/.*JAVA_HOME:-\([^}]*\)}.*/\1/p' "$(command -v ghidraRun)")
  export JAVA_HOME
fi
mkdir -p "$ROOT/ghidra/projects"
for CORE in m7 m4; do
  case $CORE in m7) BASE=0x08020000;; m4) BASE=0x08100000;; esac
  "$HEADLESS" "$ROOT/ghidra/projects" "perkons-$VER" \
    -import "$ROOT/firmware/unpacked/$VER/$CORE.bin" -overwrite \
    -processor ARM:LE:32:Cortex -loader BinaryLoader -loader-baseAddr $BASE \
    -scriptPath "$ROOT/ghidra/scripts" \
    -preScript PerkonsSetup.java "$ROOT/symbols/$VER-$CORE.json" \
    -max-cpu 8 2>&1 | grep -E "PerkonsSetup|ERROR|Exception|Import succeeded|Analysis" || true
done
