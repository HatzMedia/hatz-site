#!/usr/bin/env python3
"""Makes the share picture, the phone home-screen icon and the small header logo from the full-size logo.
Run once, or again if the logo changes. Needs Pillow (pip install pillow)."""
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

A = Path(__file__).resolve().parent.parent / "assets"
src = A / "hatz-brand-full.webp"
if not src.exists():  # first run: keep the original at full size under a new name
    Image.open(A / "hatz-brand.webp").save(src, quality=90, method=6)
logo = Image.open(src).convert("RGBA")

# share picture for Facebook, iMessage, etc. (1200x630)
W, H = 1200, 630
og = Image.new("RGB", (W, H), (11, 12, 17))
d = ImageDraw.Draw(og)
lg = logo.resize((470, 470), Image.LANCZOS)
og.paste(lg, (70, 80), lg)
bold = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 78)
small = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 30)
x = 600
d.text((x, 150), "Good food.", font=bold, fill=(255, 255, 255))
d.text((x, 245), "Great people.", font=bold, fill=(255, 255, 255))
d.text((x, 340), "Local stories.", font=bold, fill=(255, 57, 213))
d.rectangle((x, 440, x + 40, 444), fill=(0, 174, 255))
d.text((x + 56, 428), "HATZMEDIA.COM  ·  CINCINNATI & BEYOND", font=small, fill=(199, 204, 218))
og.save(A / "og-home.jpg", quality=86, optimize=True)

# phone home-screen icon
ic = Image.new("RGB", (180, 180), (11, 12, 17))
l2 = logo.resize((172, 172), Image.LANCZOS)
ic.paste(l2, (4, 4), l2)
ic.save(A / "apple-touch-icon.png", optimize=True)

# header logo at 168px (three times the 56px it is shown at, for sharp screens)
logo.resize((168, 168), Image.LANCZOS).save(A / "hatz-brand.webp", quality=88, method=6)

for f in ["og-home.jpg", "apple-touch-icon.png", "hatz-brand.webp", "hatz-brand-full.webp"]:
    print("%-22s %s %d KB" % (f, Image.open(A / f).size, os.path.getsize(A / f) // 1024))
