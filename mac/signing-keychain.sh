#!/bin/bash
# A keychain of its own with the release signing certificate (release-keys.sh), for codesign: your login keychain
# is left alone. Prints the keychain's path; build-app.sh signs with "Amadeus DMX" from it.
#   ./signing-keychain.sh P12 PASSWORD_FILE KEYCHAIN
set -euo pipefail
P12="$1" PASSFILE="$2" KC="$3"
PW="$(openssl rand -hex 16)"
security delete-keychain "$KC" 2>/dev/null || true
security create-keychain -p "$PW" "$KC"
security set-keychain-settings "$KC"  # no auto-lock during a long build
security unlock-keychain -p "$PW" "$KC"
security import "$P12" -k "$KC" -P "$(cat "$PASSFILE")" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$PW" "$KC" >/dev/null
# codesign finds the private key only in a keychain on the search list: add this one, keep the others
security list-keychains -d user -s "$KC" $(security list-keychains -d user | tr -d '"')
echo "$KC"
