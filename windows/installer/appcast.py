# /// script
# requires-python = ">=3.10"
# dependencies = ["cryptography>=42"]
# ///
"""The Windows update feeds: a Sparkle-format appcast with the installer as its enclosure, Ed25519-signed with the
same update key as the Mac apps (mac/release-keys.sh), for NetSparkleUpdater.

  uv run windows/installer/appcast.py feed INSTALLER -o appcast-windows.xml --version 0.3.0 --build 412 \
      --url-prefix https://github.com/OWNER/REPO/releases/download/v0.3.0/ [--notes-url URL] [--title "Amadeus DMX"]
  uv run windows/installer/appcast.py sign FILE            the signature (base64) of any file
  uv run windows/installer/appcast.py verify FILE SIG      check a signature against the public key

The private key comes from $SPARKLE_PRIVATE_KEY or --key-file: what Sparkle's key files hold, base64 of the 32-byte
seed (release-keys.sh, Sparkle 2's generate_keys -x), or of the seed and the public key (64 bytes). Every signature
is checked against mac/Resources/sparkle-public-key.txt (--public-key) before it's written, so a wrong key fails
here and not on the computers out there.

`feed` also writes FEED.signature (the appcast's own signature): NetSparkle's strict security mode reads it.
"""

from __future__ import annotations

import argparse
import base64
import email.utils
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_KEY = ROOT / "mac" / "Resources" / "sparkle-public-key.txt"
SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def raw_public(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def load_private(args) -> Ed25519PrivateKey:
    text = Path(args.key_file).read_text() if args.key_file else os.environ.get("SPARKLE_PRIVATE_KEY", "")
    if not text.strip():
        sys.exit("No update key: set SPARKLE_PRIVATE_KEY or pass --key-file")
    try:
        raw = base64.b64decode("".join(text.split()), validate=True)
    except ValueError:
        sys.exit("The update key is not base64")
    if len(raw) not in (32, 64):
        # 96 bytes is Sparkle 1's export (an expanded secret key): no seed in it to sign with here
        sys.exit(f"The update key has {len(raw)} bytes: expected 32 (the seed) or 64 (seed + public key)")
    key = Ed25519PrivateKey.from_private_bytes(raw[:32])
    if len(raw) == 64 and raw[32:] != raw_public(key.public_key()):
        sys.exit("The update key's public half doesn't match its seed")
    return key


def load_public(path: str) -> Ed25519PublicKey:
    raw = base64.b64decode("".join(Path(path).read_text().split()))
    if len(raw) != 32:
        sys.exit(f"{path}: expected a 32-byte public key, got {len(raw)} bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def verify(public: Ed25519PublicKey, data: bytes, signature: str) -> bool:
    try:
        public.verify(base64.b64decode(signature), data)
        return True
    except (InvalidSignature, ValueError):
        return False


def sign_checked(args, data: bytes) -> str:
    key = load_private(args)
    signature = base64.b64encode(key.sign(data)).decode()
    if not verify(load_public(args.public_key), data, signature):
        sys.exit(f"The update key doesn't belong to {args.public_key}: the apps would refuse this update")
    return signature


def item_xml(args, installer: Path, signature: str) -> str:
    url = args.url_prefix + installer.name
    title = f"{args.title} {args.version}"
    notes = f"\n      <sparkle:releaseNotesLink>{escape(args.notes_url)}</sparkle:releaseNotesLink>" if args.notes_url else ""
    return f"""    <item>
      <title>{escape(title)}</title>
      <pubDate>{email.utils.formatdate(usegmt=True)}</pubDate>{notes}
      <sparkle:version>{escape(args.build)}</sparkle:version>
      <sparkle:shortVersionString>{escape(args.version)}</sparkle:shortVersionString>
      <enclosure url={quoteattr(url)} length="{installer.stat().st_size}" type="application/octet-stream"
        sparkle:os="windows" sparkle:version={quoteattr(args.build)} sparkle:shortVersionString={quoteattr(args.version)}
        sparkle:edSignature={quoteattr(signature)}/>
    </item>"""


def cmd_feed(args) -> None:
    installer = Path(args.installer)
    if not args.build.isdigit():
        sys.exit(f"--build must be the build number (the commit count), not {args.build!r}: the apps compare it")
    signature = sign_checked(args, installer.read_bytes())
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="{SPARKLE_NS}">
  <channel>
    <title>{escape(args.title)}</title>
{item_xml(args, installer, signature)}
  </channel>
</rss>
"""
    out = Path(args.output)
    out.write_text(xml, encoding="utf-8", newline="\n")
    Path(f"{out}.signature").write_text(sign_checked(args, out.read_bytes()) + "\n", newline="\n")
    print(f"Wrote {out} (+ .signature): {installer.name}, {args.version} (build {args.build})")


def cmd_sign(args) -> None:
    print(sign_checked(args, Path(args.file).read_bytes()))


def cmd_verify(args) -> None:
    signature = Path(args.signature).read_text().strip() if Path(args.signature).is_file() else args.signature
    ok = verify(load_public(args.public_key), Path(args.file).read_bytes(), signature)
    print("valid" if ok else "INVALID")
    sys.exit(0 if ok else 1)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--key-file", help="the private update key (default: $SPARKLE_PRIVATE_KEY)")
    p.add_argument("--public-key", default=str(PUBLIC_KEY), help="the public key the apps check with")
    sub = p.add_subparsers(dest="command", required=True)
    f = sub.add_parser("feed", help="write an appcast for one installer")
    f.add_argument("installer")
    f.add_argument("-o", "--output", required=True)
    f.add_argument("--version", required=True, help="the version people see (0.3.0)")
    f.add_argument("--build", required=True, help="the build number, what the apps compare (the commit count)")
    f.add_argument("--url-prefix", required=True, help="where the installer is downloaded from (ends with /)")
    f.add_argument("--notes-url", help="the release notes")
    f.add_argument("--title", default="Amadeus DMX")
    s = sub.add_parser("sign", help="print the signature of a file")
    s.add_argument("file")
    v = sub.add_parser("verify", help="check a signature (base64, or a file holding it)")
    v.add_argument("file")
    v.add_argument("signature")
    args = p.parse_args(argv)
    {"feed": cmd_feed, "sign": cmd_sign, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    main()
