#!/bin/bash
# Build "Decisive Lightning.app" (release, Apple Silicon) next to this script in build/.
#   ./build-app.sh             build the app
#   ./build-app.sh --install   … and copy it to ~/Applications
#   ./build-app.sh --dmg       … and make a disk image (build/DecisiveLightning.dmg)
# The engine folder (this repository) is baked in as the default; the app asks if it moves.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
APP="build/Decisive Lightning.app"
VERSION="0.1.$(git -C "$ROOT" rev-list --count HEAD 2>/dev/null || echo 0)"

swift build -c release --arch arm64
BIN="$(swift build -c release --arch arm64 --show-bin-path)/DecisiveLightning"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/DecisiveLightning"

if [ ! -f build/AppIcon.icns ]; then
  swift tools/make-icon.swift build/AppIcon.iconset
  iconutil -c icns build/AppIcon.iconset -o build/AppIcon.icns
fi
cp build/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>io.github.decisivelightning.app</string>
  <key>CFBundleName</key><string>Decisive Lightning</string>
  <key>CFBundleDisplayName</key><string>Decisive Lightning</string>
  <key>CFBundleExecutable</key><string>DecisiveLightning</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.music</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
  <key>NSLocalNetworkUsageDescription</key>
  <string>Decisive Lightning sends DMX to your lights over Art-Net and listens to VirtualDJ on this Mac.</string>
  <key>DLEngineRoot</key><string>${ROOT}</string>
</dict>
</plist>
PLIST

codesign --force --sign - --timestamp=none "$APP"
echo "Built $APP ($VERSION)"

# Decisive Link: the companion for the DJ's laptop (menu bar only)
LINK="build/Decisive Link.app"
rm -rf "$LINK"
mkdir -p "$LINK/Contents/MacOS" "$LINK/Contents/Resources"
cp "$(dirname "$BIN")/DecisiveLink" "$LINK/Contents/MacOS/DecisiveLink"
cp build/AppIcon.icns "$LINK/Contents/Resources/AppIcon.icns"
cat > "$LINK/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>io.github.decisivelightning.link</string>
  <key>CFBundleName</key><string>Decisive Link</string>
  <key>CFBundleExecutable</key><string>DecisiveLink</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>NSLocalNetworkUsageDescription</key>
  <string>Decisive Link passes VirtualDJ's mix to the lighting computer on your network.</string>
  <key>NSBonjourServices</key><array><string>_decisivelink._tcp</string></array>
</dict>
</plist>
PLIST
codesign --force --sign - --timestamp=none "$LINK"
echo "Built $LINK"

if [ "${1:-}" = "--install" ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Decisive Lightning.app"
  cp -R "$APP" "$HOME/Applications/"
  echo "Installed to ~/Applications"
elif [ "${1:-}" = "--dmg" ]; then
  rm -rf build/dmg build/DecisiveLightning.dmg
  mkdir -p build/dmg
  cp -R "$APP" build/dmg/
  ln -s /Applications build/dmg/Applications
  hdiutil create -volname "Decisive Lightning" -srcfolder build/dmg -ov -format UDZO build/DecisiveLightning.dmg >/dev/null
  rm -rf build/dmg
  echo "Disk image: build/DecisiveLightning.dmg"
  mkdir -p build/dmg && cp -R "$LINK" build/dmg/ && ln -s /Applications build/dmg/Applications
  hdiutil create -volname "Decisive Link" -srcfolder build/dmg -ov -format UDZO build/DecisiveLink.dmg >/dev/null
  rm -rf build/dmg
  echo "Disk image for the DJ: build/DecisiveLink.dmg"
fi
