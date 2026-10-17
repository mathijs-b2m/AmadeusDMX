#!/bin/bash
# Build "Amadeus DMX.app" (release, Apple Silicon) next to this script in build/.
#   ./build-app.sh             build the app for this checkout (it runs the engine from here, with its .venv)
#   ./build-app.sh --release   build the app people download: the engine and its Python inside (bundle-engine.sh)
#   ./build-app.sh --install   … and copy it to ~/Applications (a development build as "Amadeus DMX (dev)")
#   ./build-app.sh --dmg       … and make disk images (build/AmadeusDMX.dmg, build/AmadeusLink.dmg)
# Options combine (--release --dmg). VERSION=1.2.3 sets the version people see (default 0.1.<commits>); the build
# number is always the commit count, so every later build is newer (what Sparkle compares).
# Every build is signed with the best certificate on this Mac (~/.amadeus-release): Developer ID, else the
# release certificate (release-keys.sh), else ad hoc. A Developer ID release with --dmg is notarized too. FEED_URL=… turns on updates (Sparkle): the appcast Amadeus DMX checks;
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

# signing, the best there is on this Mac: the Developer ID certificate (Gatekeeper opens the app without asking,
# once it's notarized), else the release certificate (release-keys.sh), else ad hoc. Each in a keychain of its own,
# removed again at the end. DEVID_P12/DEVID_PASSWORD_FILE and SIGN_P12/SIGN_PASSWORD_FILE point elsewhere.
SIGN="-" KC="" DEVID=0
KEYS="$HOME/.amadeus-release"
DEVID_P12="${DEVID_P12:-$KEYS/developer-id.p12}"
DEVID_PASSFILE="${DEVID_PASSWORD_FILE:-$KEYS/developer-id-password.txt}"
P12="${SIGN_P12:-$KEYS/signing.p12}"
PASSFILE="${SIGN_PASSWORD_FILE:-$KEYS/signing-password.txt}"
# every build, a development one too: then macOS keeps the permissions you gave (Accessibility for djay) across
# rebuilds, instead of asking again for each new ad-hoc signature
if [ -s "$DEVID_P12" ]; then
  KC="$OUT/signing.keychain-db"
  ./signing-keychain.sh "$DEVID_P12" "$DEVID_PASSFILE" "$KC" >/dev/null
  SIGN="$(security find-identity -v -p codesigning "$KC" | sed -n 's/.*"\(Developer ID Application: .*\)"/\1/p' | head -1)"
  [ -n "$SIGN" ] || { echo "No Developer ID Application identity in $DEVID_P12" >&2; exit 1; }
  DEVID=1
elif [ -s "$P12" ]; then
  KC="$OUT/signing.keychain-db"
  ./signing-keychain.sh "$P12" "$PASSFILE" "$KC" >/dev/null
  SIGN="Amadeus DMX"
fi
[ -n "$KC" ] && trap 'security delete-keychain "$KC" 2>/dev/null || true' EXIT
# Developer ID: the hardened runtime and a secure timestamp, what notarization asks for
if [ "$DEVID" = 1 ]; then
  sign() { codesign --force --keychain "$KC" --sign "$SIGN" --options runtime --timestamp "$@"; }
elif [ -n "$KC" ]; then
  sign() { codesign --force --keychain "$KC" --sign "$SIGN" --timestamp=none "$@"; }
else
  sign() { codesign --force --sign - --timestamp=none "$@"; }
fi

# notarization (Developer ID releases with disk images): an App Store Connect API key, NOTARY_KEY_FILE (.p8),
# NOTARY_KEY_ID and NOTARY_ISSUER (none for an individual key); on this Mac from ~/.amadeus-release/notary.env
NOTARY_KEY_FILE="${NOTARY_KEY_FILE:-$KEYS/notary-key.p8}"
if [ -z "${NOTARY_KEY_ID:-}" ] && [ -s "$KEYS/notary.env" ]; then source "$KEYS/notary.env"; fi
notarize() {  # submit, wait for Apple's verdict, show why when it's no
  local out="$OUT/notary.plist"
  xcrun notarytool submit "$1" --key "$NOTARY_KEY_FILE" --key-id "$NOTARY_KEY_ID" \
    ${NOTARY_ISSUER:+--issuer "$NOTARY_ISSUER"} --wait --timeout 1h --output-format plist > "$out" || true
  local status id
  status="$(/usr/libexec/PlistBuddy -c "Print :status" "$out" 2>/dev/null || echo "no answer")"
  id="$(/usr/libexec/PlistBuddy -c "Print :id" "$out" 2>/dev/null || true)"
  rm -f "$out"
  if [ "$status" != Accepted ]; then
    echo "Notarization of $(basename "$1"): $status" >&2
    [ -n "$id" ] && xcrun notarytool log "$id" --key "$NOTARY_KEY_FILE" --key-id "$NOTARY_KEY_ID" \
      ${NOTARY_ISSUER:+--issuer "$NOTARY_ISSUER"} >&2
    exit 1
  fi
  echo "Notarized $(basename "$1")"
}

# Sparkle, the updater: in the app's Frameworks, where its executable looks for it
embed_sparkle() {
  mkdir -p "$1/Contents/Frameworks"
  cp -R "$(dirname "$BIN")/Sparkle.framework" "$1/Contents/Frameworks/"
  install_name_tool -add_rpath "@executable_path/../Frameworks" "$1/Contents/MacOS/$2"
}

# inside out: every binary in Resources (the engine's Python, the VirtualDJ plugin), Sparkle's helpers, Sparkle,
# the app. The Python runs with entitlements of its own: the optional packs it loads are not signed by us.
sign_app() {
  local res="$1/Contents/Resources" f
  if [ -d "$res/runtime" ]; then
    find "$res" -type f -not -path "*.bundle/*" \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) -print0 |
      while IFS= read -r -d "" f; do
        file -b "$f" | grep -q "Mach-O" || continue
        if [ "$(dirname "$f")" = "$res/runtime/bin" ]; then sign --entitlements python.entitlements "$f"
        else sign "$f"; fi
      done
  fi
  find "$res" -type d -name "*.bundle" -prune -print0 | while IFS= read -r -d "" f; do sign "$f"; done
  local spk="$1/Contents/Frameworks/Sparkle.framework/Versions/B"
  sign "$spk/XPCServices/Installer.xpc"
  sign --preserve-metadata=entitlements "$spk/XPCServices/Downloader.xpc"
  sign "$spk/Updater.app" "$spk/Autoupdate"
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
echo "Built $APP ($VERSION$([ "$RELEASE" = 1 ] && echo ", engine inside")$([ "$SIGN" != - ] && echo ", signed by $SIGN")$([ -n "$UPDATES" ] && echo ", updates from $FEED_URL"))"

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
  # notarized: a Developer ID release, with the API key at hand. The apps first (stapled, so a copy out of the
  # disk image opens offline too), then their disk images (what people and Sparkle download).
  NOTARIZE=0
  if [ "$RELEASE" = 1 ] && [ "$DEVID" = 1 ] && [ -s "$NOTARY_KEY_FILE" ] && [ -n "${NOTARY_KEY_ID:-}" ]; then NOTARIZE=1
  elif [ "$DEVID" = 1 ]; then echo "Not notarized: no API key (NOTARY_KEY_FILE, NOTARY_KEY_ID)" >&2; fi
  dmg() {  # dmg APP NAME VOLUME
    if [ "$NOTARIZE" = 1 ]; then
      ditto -c -k --keepParent "$1" "$OUT/notarize.zip"
      notarize "$OUT/notarize.zip"; rm -f "$OUT/notarize.zip"
      xcrun stapler staple -q "$1"
    fi
    rm -rf "$OUT/dmg" "$OUT/$2.dmg"
    mkdir -p "$OUT/dmg"
    cp -R "$1" "$OUT/dmg/"
    ln -s /Applications "$OUT/dmg/Applications"
    hdiutil create -volname "$3" -srcfolder "$OUT/dmg" -ov -format UDZO "$OUT/$2.dmg" >/dev/null
    rm -rf "$OUT/dmg"
    if [ "$SIGN" != - ]; then sign "$OUT/$2.dmg"; fi
    if [ "$NOTARIZE" = 1 ]; then notarize "$OUT/$2.dmg"; xcrun stapler staple -q "$OUT/$2.dmg"; fi
  }
  dmg "$APP" AmadeusDMX "Amadeus DMX"
  echo "Disk image: $OUT/AmadeusDMX.dmg$([ "$NOTARIZE" = 1 ] && echo ", notarized")"
  dmg "$LINK" AmadeusLink "Amadeus Link"
  echo "Disk image for the DJ: $OUT/AmadeusLink.dmg$([ "$NOTARIZE" = 1 ] && echo ", notarized")"
fi
