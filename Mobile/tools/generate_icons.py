"""Render the app's geometric assistant icon at Android launcher sizes."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def icon(size):
    image = Image.new("RGB", (1024, 1024), "#101410")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((170, 210, 854, 814), radius=190, fill="#88d577")
    draw.rounded_rectangle((225, 270, 799, 734), radius=140, fill="#19251a")
    for x in (390, 635):
        draw.rounded_rectangle((x-35, 365, x+35, 500), radius=35, fill="#a7eb98")
    draw.arc((395, 460, 629, 642), 5, 175, fill="#a7eb98", width=25)
    draw.line((512, 140, 512, 220), fill="#88d577", width=28)
    draw.ellipse((480, 100, 544, 164), fill="#a7eb98")
    return image.resize((size, size), Image.Resampling.LANCZOS)


for density, size in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
    icon(size).save(ROOT / f"android/app/src/main/res/mipmap-{density}/ic_launcher.png")
print("Generated Android VietOCR launcher icons.")
