"""Bounded format/dimension verification, no Torch import or model allocation."""
import json
import sys
import warnings
from PIL import Image

Image.MAX_IMAGE_PIXELS = int(sys.argv[2])
warnings.simplefilter("error", Image.DecompressionBombWarning)
try:
    with Image.open(sys.argv[1]) as image:
        width, height = image.size
        if width < 2 or height < 2 or width * height > Image.MAX_IMAGE_PIXELS:
            raise ValueError("image_dimensions")
        if image.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError("image_format")
        media = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[image.format]
        image.verify()
    print(json.dumps({"width": width, "height": height, "mediaType": media}))
except Exception:
    print(json.dumps({"error": "invalid_image"}))
    sys.exit(2)
