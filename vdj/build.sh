#!/bin/bash
# Build the DecisiveLink VirtualDJ plugin for Apple Silicon and (with --install) copy it into VirtualDJ.
# The SDK headers are downloaded from virtualdj.com (not stored in this repository).
set -euo pipefail
cd "$(dirname "$0")"
SDK_URL="https://www.virtualdj.com/developers/VirtualDJ8_SDK_20211003.zip"
mkdir -p sdk build
if [ ! -f sdk/vdjDsp8.h ]; then
  echo "Downloading VirtualDJ SDK headers …"
  curl -fsSL "$SDK_URL" -o sdk/sdk.zip
  unzip -o -j -q sdk/sdk.zip '*.h' -d sdk
fi
B=build/DecisiveLink.bundle
rm -rf "$B"; mkdir -p "$B/Contents/MacOS"
clang++ -std=c++17 -O2 -arch arm64 -bundle -fvisibility=hidden -Isdk \
  -framework CoreFoundation -o "$B/Contents/MacOS/DecisiveLink" DecisiveLink.cpp
cat > "$B/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>DecisiveLink</string>
  <key>CFBundleIdentifier</key><string>io.github.decisivelightning.vdjplugin</string>
  <key>CFBundleName</key><string>DecisiveLink</string>
  <key>CFBundlePackageType</key><string>BNDL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
</dict></plist>
PLIST
codesign --force --sign - "$B" >/dev/null 2>&1   # ad-hoc signature (required on Apple Silicon)
nm -gU "$B/Contents/MacOS/DecisiveLink" | grep -q DllGetClassObject && echo "Built $B (exports DllGetClassObject)"
if [ "${1:-}" = "--install" ]; then
  DEST="$HOME/Library/Application Support/VirtualDJ/PluginsMacArm/SoundEffect"
  mkdir -p "$DEST"; rm -rf "$DEST/DecisiveLink.bundle"; cp -R "$B" "$DEST/"
  echo "Installed to $DEST — restart VirtualDJ, then enable 'DecisiveLink' as a master effect."
fi
