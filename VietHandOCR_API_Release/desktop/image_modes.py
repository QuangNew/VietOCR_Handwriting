"""Optional document derivatives. The source JPEG is never overwritten."""
from PIL import Image, ImageOps, ImageFilter, ImageChops


def black_white(image: Image.Image) -> Image.Image:
    # Local luminance threshold tolerates uneven light better than a single
    # global cutoff. Keep resolution and accent strokes; don't sharpen noise.
    gray = ImageOps.grayscale(image)
    background = gray.filter(ImageFilter.BoxBlur(15))
    difference = ImageChops.subtract(gray, background, offset=128)
    return difference.point(lambda value: 0 if value < 120 else 255).convert('RGB')
