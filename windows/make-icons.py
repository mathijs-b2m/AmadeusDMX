"""The apps' icons (AmadeusDMX/Assets, AmadeusLink/Assets) from the logo in docs/logo. Run it after the logo changes:

    python3 windows/make-icons.py      (needs Pillow: pip install pillow)

The .ico files are committed, so a build needs neither Python nor Pillow.
"""

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
LOGO = HERE.parent / "docs" / "logo" / "amadeus-dmx-1024.png"
SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]

img = Image.open(LOGO).convert("RGBA")
for app in ("AmadeusDMX", "AmadeusLink"):  # the same logo, like the Mac apps
    out = HERE / app / "Assets" / f"{app}.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, sizes=SIZES)
    print(out.relative_to(HERE.parent), out.stat().st_size, "bytes")
