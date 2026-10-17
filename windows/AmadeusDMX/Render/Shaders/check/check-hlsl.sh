#!/bin/bash
# Mac (or Linux): a syntax and type check of the stage's HLSL with clang's HLSL front end, which needs no Windows.
# D3DCompiler compiles them for real at startup (and `AmadeusDMX.exe -renderSelfTest` draws with them); this catches
# typos, undeclared names, wrong swizzles and type mismatches before that. The semantics, registers and `discard`
# are stripped first (clang's HLSL support doesn't know them all yet), and hlsl.h here stands in for the intrinsics.
# Skips itself when the clang on the PATH has no HLSL front end.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
shaders="$here/.."
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir "$work/probe"
probe="$work/probe/probe.hlsl"
echo 'float4 f(float4 p) { return p; }' > "$probe"
if ! clang --driver-mode=dxc -T lib_6_3 -I "$here" "$probe" -fsyntax-only >/dev/null 2>&1; then
  echo "check-hlsl: no clang with an HLSL front end here, skipped"
  exit 0
fi
python3 - "$shaders" "$work" <<'PY'
import glob, os, re, sys
src, out = sys.argv[1], sys.argv[2]
common = open(os.path.join(src, "Common.hlsli")).read()
for f in sorted(glob.glob(os.path.join(src, "*.hlsl"))):
    s = open(f).read().replace('#include "Common.hlsli"', common)
    s = re.sub(r"\s*:\s*(SV_\w+|POSITION|NORMAL|COLOR\d*|TEXCOORD\d*)\b", "", s)
    s = re.sub(r"\s*:\s*register\(\w+\)", "", s)
    s = re.sub(r"cbuffer\s+\w+\s*\{([^}]*)\};", lambda m: m.group(1).replace("column_major ", ""), s)
    s = s.replace("[loop]", "").replace("discard;", "return (float4)0;")
    open(os.path.join(out, os.path.basename(f)), "w").write(s)
PY
status=0
for f in "$work"/*.hlsl; do
  if ! clang --driver-mode=dxc -T lib_6_3 -I "$here" "$f" -fsyntax-only 2>"$work/log" || grep -q "error" "$work/log"; then
    echo "check-hlsl: $(basename "$f")"; grep -v "argument unused" "$work/log" || true
    status=1
  fi
done
[ $status -eq 0 ] && echo "check-hlsl: $(ls "$work"/*.hlsl | wc -l | tr -d ' ') shader files OK"
exit $status
