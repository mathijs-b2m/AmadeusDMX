#!/bin/bash
# Build "Amadeus DMX.app" (release, Apple Silicon) next to this script in build/.
#   ./build-app.sh             build the app for this checkout (it runs the engine from here, with its .venv)
#   ./build-app.sh --release   build the app people download: the engine and its Python inside (bundle-engine.sh)
#   ./build-app.sh --install   … and copy it to ~/Applications (a development build as "Amadeus DMX (dev)")
#   ./build-app.sh --dmg       … and make disk images (build/AmadeusDMX.dmg, build/AmadeusLink.dmg)
# Options combine (--release --dmg). VERSION=1.2.3 sets the version people see (default 0.1.<commits>); the build
# number is always the commit count, so every later build is newer (what Sparkle compares).
# Every build is signed with the release certificate when it's on this Mac (release-keys.sh; SIGN_P12 and
# SIGN_PASSWORD_FILE, default ~/.amadeus-release), else ad hoc. FEED_URL=… turns on updates (Sparkle): the appcast Amadeus DMX checks;
# Amadeus Link checks appcast-link.xml next to it.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
OUT="${OUT:-build}"  # OUT=… builds elsewhere (e.g. while an app built here is running)
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
APP="$OUT/Amadeus DMX.app"
BUILD="$(git -C "$ROOT" rev-list --count HEAD 2>/dev/null || echo 0)"
VERSION="${VERSION:-0.1.$BUILD}"
RELEASE=0 INSTALL=0 DMG=0
for arg in "$@"; do
  case "$arg" in
    --release) RELEASE=1 ;;
    --install) INSTALL=1 ;;
    --dmg) DMG=1 ;;
    *) echo "Unknown option $arg" >&2; exit 1 ;;
  esac
done
# a development build runs the engine from this checkout; a release has its own inside
ENGINE_ROOT=""
[ "$RELEASE" = 1 ] || ENGINE_ROOT="  <key>AmadeusEngineRoot</key><string>${ROOT}</string>"

# updates: only a release with a feed and the public update key (Sparkle stays off otherwise). Each app has its
# feed: FEED_URL for Amadeus DMX, appcast-link.xml next to it for Amadeus Link (LINK_FEED_URL=… elsewhere).
updates_plist() {
  if [ "$RELEASE" = 1 ] && [ -n "$1" ] && [ -s Resources/sparkle-public-key.txt ]; then
    echo "  <key>SUFeedURL</key><string>$1</string>
  <key>SUPublicEDKey</key><string>$(tr -d '\n' < Resources/sparkle-public-key.txt)</string>
  <key>SUVerifyUpdateBeforeExtraction</key><true/>"
  fi
}
FEED_URL="${FEED_URL:-}"
LINK_FEED_URL="${LINK_FEED_URL:-${FEED_URL:+${FEED_URL%/*}/appcast-link.xml}}"
UPDATES="$(updates_plist "$FEED_URL")"
LINK_UPDATES="$(updates_plist "$LINK_FEED_URL")"

# signing: the release certificate in a keychain of its own (removed again at the end), else ad hoc
SIGN="-"
P12="${SIGN_P12:-$HOME/.amadeus-release/signing.p12}"
PASSFILE="${SIGN_PASSWORD_FILE:-$HOME/.amadeus-release/signing-password.txt}"
# every build, a development one too: then macOS keeps the permissions you gave (Accessibility for djay) across
# rebuilds, instead of asking again for each new ad-hoc signature
if [ -s "$P12" ]; then
  KC="$OUT/signing.keychain-db"
  ./signing-keychain.sh "$P12" "$PASSFILE" "$KC" >/dev/null
  trap 'security delete-keychain "$KC" 2>/dev/null || true' EXIT
  SIGN="Amadeus DMX"
fi
sign() { codesign --force --sign "$SIGN" --timestamp=none "$@"; }

# Sparkle, the updater: in the app's Frameworks, where its executable looks for it
embed_sparkle() {
  mkdir -p "$1/Contents/Frameworks"
  cp -R "$(dirname "$BIN")/Sparkle.framework" "$1/Contents/Frameworks/"
  install_name_tool -add_rpath "@executable_path/../Frameworks" "$1/Contents/MacOS/$2"
}

# inside out: Sparkle's helpers, Sparkle, the app
sign_app() {
  local spk="$1/Contents/Frameworks/Sparkle.framework/Versions/B"
  for helper in "$spk"/XPCServices/*.xpc "$spk/Updater.app" "$spk/Autoupdate"; do sign "$helper"; done
  sign "$1/Contents/Frameworks/Sparkle.framework"
  sign "$1"
}

swift build -c release --arch arm64
BIN="$(swift build -c release --arch arm64 --show-bin-path)/AmadeusDMX"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/AmadeusDMX"
embed_sparkle "$APP" AmadeusDMX

cp Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>io.github.amadeusdmx.app</string>
  <key>CFBundleName</key><string>Amadeus DMX</string>
  <key>CFBundleDisplayName</key><string>Amadeus DMX</string>
  <key>CFBundleExecutable</key><string>AmadeusDMX</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${BUILD}</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.music</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
  <key>NSLocalNetworkUsageDescription</key>
  <string>Amadeus DMX sends DMX to your lights over Art-Net and listens to VirtualDJ on this Mac.</string>
${ENGINE_ROOT}
${UPDATES}
</dict>
</plist>
PLIST

[ "$RELEASE" = 1 ] && ./bundle-engine.sh "$APP"
sign_app "$APP"
echo "Built $APP ($VERSION$([ "$RELEASE" = 1 ] && echo ", engine inside")$([ "$SIGN" != - ] && echo ", signed as $SIGN")$([ -n "$UPDATES" ] && echo ", updates from $FEED_URL"))"

# Amadeus Link: the companion for the DJ's laptop (menu bar only)
LINK="$OUT/Amadeus Link.app"
rm -rf "$LINK"
mkdir -p "$LINK/Contents/MacOS" "$LINK/Contents/Resources"
cp "$(dirname "$BIN")/AmadeusLink" "$LINK/Contents/MacOS/AmadeusLink"
embed_sparkle "$LINK" AmadeusLink
# the VirtualDJ plugin, for Link to install on the DJ laptop (signed ad hoc by vdj/build.sh, as Amadeus DMX's copy)
[ -d "$ROOT/vdj/build/AmadeusLink.bundle" ] || "$ROOT/vdj/build.sh" >/dev/null
cp -R "$ROOT/vdj/build/AmadeusLink.bundle" "$LINK/Contents/Resources/"
# the Mixxx mapping, for Link to put in Mixxx's controllers folder
mkdir -p "$LINK/Contents/Resources/mixxx"
cp "$ROOT"/mixxx/*.xml "$ROOT"/mixxx/*.js "$LINK/Contents/Resources/mixxx/"
cp Resources/AppIcon.icns "$LINK/Contents/Resources/AppIcon.icns"
cat > "$LINK/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>io.github.amadeusdmx.link</string>
  <key>CFBundleName</key><string>Amadeus Link</string>
  <key>CFBundleExecutable</key><string>AmadeusLink</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${BUILD}</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>NSLocalNetworkUsageDescription</key>
  <string>Amadeus Link passes VirtualDJ's mix to the lighting computer on your network.</string>
  <key>NSBonjourServices</key><array><string>_amadeuslink._tcp</string></array>
${LINK_UPDATES}
</dict>
</plist>
PLIST
sign_app "$LINK"
echo "Built $LINK$([ -n "$LINK_UPDATES" ] && echo ", updates from $LINK_FEED_URL")"

if [ "$INSTALL" = 1 ]; then
  # a development build as "Amadeus DMX (dev)", so it isn't mistaken for a release in /Applications
  NAME="Amadeus DMX$([ "$RELEASE" = 1 ] || echo " (dev)").app"
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/$NAME"
  cp -R "$APP" "$HOME/Applications/$NAME"
  echo "Installed to ~/Applications/$NAME"
fi
if [ "$DMG" = 1 ]; then
  rm -rf "$OUT/dmg" "$OUT/AmadeusDMX.dmg"
  mkdir -p "$OUT/dmg"
  cp -R "$APP" "$OUT/dmg/"
  ln -s /Applications "$OUT/dmg/Applications"
  hdiutil create -volname "Amadeus DMX" -srcfolder "$OUT/dmg" -ov -format UDZO "$OUT/AmadeusDMX.dmg" >/dev/null
  rm -rf "$OUT/dmg"
  echo "Disk image: $OUT/AmadeusDMX.dmg"
  mkdir -p "$OUT/dmg" && cp -R "$LINK" "$OUT/dmg/" && ln -s /Applications "$OUT/dmg/Applications"
  hdiutil create -volname "Amadeus Link" -srcfolder "$OUT/dmg" -ov -format UDZO "$OUT/AmadeusLink.dmg" >/dev/null
  rm -rf "$OUT/dmg"
  echo "Disk image for the DJ: $OUT/AmadeusLink.dmg"
fi
