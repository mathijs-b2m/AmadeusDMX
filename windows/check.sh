#!/bin/bash
# Mac (or Linux): builds the whole Windows solution and runs the kit's tests. The apps are compiled without the
# Windows-only packaging steps (resources index, self-contained Windows App SDK), which is everything else.
# The tests that talk to the engine's own Python (Amadeus Link against amadeus/show/link.py) use the checkout's
# .venv, or AMADEUS_TEST_PYTHON; without one they skip themselves.
set -euo pipefail
cd "$(dirname "$0")"
DOTNET="${DOTNET:-$HOME/.dotnet/dotnet}"
command -v "$DOTNET" >/dev/null || DOTNET=dotnet

ROOT="$(cd .. && pwd)"
if [ -z "${AMADEUS_TEST_PYTHON:-}" ]; then
  for py in "$ROOT/.venv/bin/python" "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)/../.venv/bin/python"; do
    # one that can run the engine's Link receiver (a .venv being set up may not have its packages yet)
    if [ -x "$py" ] && (cd "$ROOT" && "$py" -c "import amadeus.show.link" 2>/dev/null); then export AMADEUS_TEST_PYTHON="$py"; break; fi
  done
fi

"$DOTNET" build AmadeusWindows.sln -c Debug -p:Platform=x64 -nologo -clp:"Summary;ErrorsOnly;WarningsOnly" \
  -p:WindowsAppSDKSelfContained=false -p:EnableCoreMrtTooling=false -p:AppxGeneratePriEnabled=false
"$DOTNET" test AmadeusKit.Tests/AmadeusKit.Tests.csproj -c Debug --no-build -nologo
