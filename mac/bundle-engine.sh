#!/bin/bash
# Put the engine and a Python of its own into an app (a release: nothing to install, no checkout needed).
#   ./bundle-engine.sh "build/Amadeus DMX.app"
# Contents/Resources/runtime   a relocatable CPython (python-build-standalone, via uv) with requirements-app.txt
# Contents/Resources/engine    the package, the web UI, fixtures, examples, the Mixxx mapping, the VirtualDJ plugin
# Your data is not in the app: the app gives the engine ~/Library/Application Support/Amadeus DMX (amadeus/paths.py).
# Needs uv (brew install uv). PYTHON_VERSION picks the Python (default 3.14, as in CI).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
APP="$1"
RES="$APP/Contents/Resources"
PY="${PYTHON_VERSION:-3.14}"
CACHE="build/python"

command -v uv >/dev/null || { echo "uv is needed: brew install uv" >&2; exit 1; }

# the runtime: a standalone CPython, without what the engine never uses
uv python install "$PY" --install-dir "$CACHE" --no-bin >/dev/null
SRC="$(find "$CACHE" -maxdepth 1 -type d -name "cpython-$PY*-macos-aarch64-none" | sort -V | tail -1)"
[ -n "$SRC" ] || { echo "No Python $PY in $CACHE" >&2; exit 1; }
rm -rf "$RES/runtime"
cp -R "$SRC" "$RES/runtime"
LIB="$(echo "$RES"/runtime/lib/python3.*)"
rm -rf "$LIB"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3} "$RES"/runtime/lib/{tcl*,tk*,itcl*,thread*} \
  "$RES"/runtime/share "$RES"/runtime/include
rm -f "$LIB/EXTERNALLY-MANAGED"
uv pip install --quiet --python "$RES/runtime/bin/python3" -r "$ROOT/requirements-app.txt"
find "$RES/runtime" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$LIB/site-packages" -type d -name tests -prune -exec rm -rf {} +  # numpy's and scipy's own test suites
rm -rf "$LIB"/site-packages/{pip,setuptools,PyObjCTest}* "$LIB"/config-* "$RES"/runtime/lib/lib{tcl,tk}*

# the engine: what a checkout ships, without the caches, tests and your own data
rm -rf "$RES/engine"
mkdir -p "$RES/engine"
rsync -a --exclude "__pycache__" --exclude ".DS_Store" \
  "$ROOT"/{amadeus,web,fixtures,examples,mixxx,licenses,LICENSE,THIRD_PARTY_NOTICES.md} "$RES/engine/"
if [ ! -d "$ROOT/vdj/build/AmadeusLink.bundle" ]; then "$ROOT/vdj/build.sh" >/dev/null; fi
mkdir -p "$RES/engine/vdj/build"
cp -R "$ROOT/vdj/build/AmadeusLink.bundle" "$RES/engine/vdj/build/"

# compiled once here: the signed app is never written to (the engine runs with PYTHONDONTWRITEBYTECODE), and
# "unchecked-hash" keeps the .pyc files valid whatever the files' dates become after copying
"$RES/runtime/bin/python3" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$LIB" "$RES/engine/amadeus" >/dev/null

# every binary of the runtime signed on its own (ad hoc: Apple Silicon needs a signature; the VirtualDJ plugin is
# signed as a bundle by vdj/build.sh), the app itself after this script
find "$RES/runtime" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) -print0 |
  while IFS= read -r -d "" f; do
    if file -b "$f" | grep -q "Mach-O"; then codesign --force --sign - --timestamp=none "$f" 2>/dev/null; fi
  done

"$RES/runtime/bin/python3" -c "import numpy, scipy, soundfile, sounddevice, websockets, openai, serial, rtmidi, aalink"
echo "Bundled the engine ($(du -sh "$RES/runtime" | cut -f1) runtime, $(du -sh "$RES/engine" | cut -f1) engine, Python $("$RES/runtime/bin/python3" -c 'import platform; print(platform.python_version())'))"
