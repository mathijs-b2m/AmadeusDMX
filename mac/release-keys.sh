#!/bin/bash
# Make the two release secrets, once (they must stay the same for every release after it):
#   signing.p12 + signing-password.txt   a self-signed code-signing certificate ("Amadeus DMX"). Every build signed
#                                        with it is the same app to macOS: permissions you gave it (Accessibility for
#                                        djay, the local network) survive an update, and Sparkle accepts the update.
#   sparkle-private-key.txt              the EdDSA key that signs each update; the app only installs updates signed
#                                        with it (its public half is Resources/sparkle-public-key.txt, in git).
#   ./release-keys.sh            into ~/.amadeus-release (KEYS_DIR=… elsewhere); never overwrites
# Keep a copy somewhere safe (a password manager): lose them and people can't update to the next release from
# within the app. Put them into GitHub (Settings › Secrets › Actions) for release.yml:
#   SIGNING_P12_BASE64   base64 < signing.p12      SIGNING_P12_PASSWORD   signing-password.txt
#   SPARKLE_PRIVATE_KEY  sparkle-private-key.txt
set -euo pipefail
cd "$(dirname "$0")"
DIR="${KEYS_DIR:-$HOME/.amadeus-release}"
OPENSSL="$(brew --prefix openssl@3 2>/dev/null)/bin/openssl"
[ -x "$OPENSSL" ] || { echo "OpenSSL 3 is needed: brew install openssl@3" >&2; exit 1; }
mkdir -p "$DIR"; chmod 700 "$DIR"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

if [ -e "$DIR/signing.p12" ]; then
  echo "Signing certificate: kept ($DIR/signing.p12)"
else
  "$OPENSSL" req -x509 -newkey rsa:3072 -nodes -days 7300 -subj "/CN=Amadeus DMX" \
    -addext "basicConstraints=critical,CA:false" -addext "keyUsage=critical,digitalSignature" \
    -addext "extendedKeyUsage=critical,codeSigning" -keyout "$TMP/key.pem" -out "$TMP/cert.pem" 2>/dev/null
  "$OPENSSL" rand -hex 24 > "$DIR/signing-password.txt"
  # -legacy: the encryption macOS's `security import` reads
  "$OPENSSL" pkcs12 -export -legacy -name "Amadeus DMX" -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
    -passout "file:$DIR/signing-password.txt" -out "$DIR/signing.p12"
  chmod 600 "$DIR/signing.p12" "$DIR/signing-password.txt"
  echo "Signing certificate: made ($DIR/signing.p12, valid 20 years)"
fi

if [ -e "$DIR/sparkle-private-key.txt" ]; then
  echo "Update key: kept ($DIR/sparkle-private-key.txt)"
else
  # Sparkle's key files are base64 of the raw 32 bytes: the seed (private), the point (public)
  "$OPENSSL" genpkey -algorithm ed25519 -outform DER -out "$TMP/ed.der"
  tail -c 32 "$TMP/ed.der" | base64 > "$DIR/sparkle-private-key.txt"
  chmod 600 "$DIR/sparkle-private-key.txt"
  "$OPENSSL" pkey -inform DER -in "$TMP/ed.der" -pubout -outform DER | tail -c 32 | base64 > Resources/sparkle-public-key.txt
  echo "Update key: made ($DIR/sparkle-private-key.txt); public key in mac/Resources/sparkle-public-key.txt (commit it)"
fi
