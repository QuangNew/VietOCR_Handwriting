"""Image batches and assistant states, independent of the desktop toolkit."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from uuid import uuid4

from PIL import Image, ImageOps

MAX_IMAGE_SIDE = 2800
MAX_IMAGE_PIXELS = 40_000_000


class BatchFullError(ValueError):
    pass


class AssistantState(str, Enum):
    AWAKE = "awake"
    RECEIVED = "received"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    SLEEP = "sleep"


@dataclass
class ImageItem:
    name: str
    image_path: Path
    source: str = "Camera"
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "ready"
    text: str = ""
    error: str = ""
    seconds: float = 0.0
    version: int = 0
    _thumbnail: Image.Image | None = field(default=None, repr=False)
    original_path: Path | None = field(default=None, repr=False)

    @property
    def image(self) -> Image.Image:
        return load_image(self.image_path)

    def thumbnail(self):
        if self._thumbnail is None:
            thumb = self.image
            thumb.thumbnail((54, 53), Image.Resampling.LANCZOS)
            self._thumbnail = thumb
        return self._thumbnail.copy()

    def rotate(self) -> None:
        image = self.image.transpose(Image.Transpose.ROTATE_90)
        self.replace_image(image)

    def replace_image(self, image: Image.Image) -> None:
        if self.original_path is None:
            self.original_path = self.image_path.with_name(self.image_path.stem + '.original' + self.image_path.suffix)
            copyfile(self.image_path, self.original_path)
        prepared = prepare_image(image)
        target = self.image_path.with_suffix('.png')
        temporary = target.with_suffix('.edit.png')
        prepared.save(temporary, format='PNG')
        temporary.replace(target)
        self.image_path = target
        self.version += 1
        self._thumbnail = None
        self.status, self.text, self.error, self.seconds = "ready", "", "", 0.0

    def export(self, destination: str | Path, *, original: bool = False) -> None:
        source = (self.original_path or self.image_path) if original else self.image_path
        destination = Path(destination)
        if source.resolve() == destination.resolve():
            return
        with Image.open(source) as image:
            same_format = (destination.suffix.lower() in ('.jpg', '.jpeg') and image.format == 'JPEG') or (
                destination.suffix.lower() == '.png' and image.format == 'PNG')
            if not same_format:
                options = {'quality': 100, 'subsampling': 0} if destination.suffix.lower() in ('.jpg', '.jpeg') else {}
                image.convert('RGB').save(destination, **options)
                return
        # Original OV5640 JPEG export is byte-for-byte, with no recompression.
        copyfile(source, destination)


def prepare_image(image: Image.Image) -> Image.Image:
    """Apply phone orientation and bound memory use before adding to a batch."""
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise ValueError("Ảnh quá lớn. Vui lòng chọn ảnh dưới 40 megapixel.")
    oriented = ImageOps.exif_transpose(image)
    if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
        rgba = oriented.convert("RGBA")
        result = Image.new("RGB", rgba.size, "white")
        result.paste(rgba, mask=rgba.getchannel("A"))
    else:
        result = oriented.convert("RGB")
    result.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    return result


def load_image(path: str | Path) -> Image.Image:
    with Image.open(path) as image:
        return prepare_image(image)


class ImageBatch:
    def __init__(self) -> None:
        self.items: list[ImageItem] = []
        self._directory = TemporaryDirectory(prefix='vietocr_queue_')

    @property
    def remaining(self) -> int:
        # Compatibility for the retired webcam helper: no image-count cap.
        return 2147483647 - len(self.items)

    def check_capacity(self, count: int) -> None:
        if count < 0:
            raise ValueError('Số ảnh không hợp lệ.')

    def add(self, image: Image.Image, name: str, source: str = "Camera") -> ImageItem:
        self.check_capacity(1)
        image_id = uuid4().hex
        path = Path(self._directory.name) / f'{image_id}.png'
        prepared = prepare_image(image)
        prepared.save(path, format='PNG')
        item = ImageItem(name=name, image_path=path, source=source, id=image_id)
        prepared.thumbnail((54, 53), Image.Resampling.LANCZOS)
        item._thumbnail = prepared
        self.items.append(item)
        return item

    def get(self, item_id: str | None) -> ImageItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def add_jpeg(self, jpeg: bytes, name: str, source: str = 'OV5640 Wi-Fi') -> ImageItem:
        import io
        image_id = uuid4().hex
        original = Path(self._directory.name) / f'{image_id}.jpg'
        with Image.open(io.BytesIO(jpeg)) as image:
            if image.format != 'JPEG' or image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError('Ảnh JPEG không hợp lệ hoặc quá lớn.')
            image.load()
            thumb = image.copy()
            thumb.thumbnail((54, 53), Image.Resampling.LANCZOS)
        # Keep JPEG as the OCR input until edited. Recompressing every full
        # frame as PNG here made Skip/capture pause the UI unnecessarily.
        original.write_bytes(jpeg)
        item = ImageItem(name, original, source, id=image_id, original_path=original, _thumbnail=thumb)
        self.items.append(item)
        return item

    def remove(self, item_id: str) -> None:
        item = self.get(item_id)
        if item:
            item.image_path.unlink(missing_ok=True)
            if item.original_path:
                item.original_path.unlink(missing_ok=True)
        self.items[:] = [item for item in self.items if item.id != item_id]

    def clear(self):
        for item in self.items:
            item.image_path.unlink(missing_ok=True)
            if item.original_path:
                item.original_path.unlink(missing_ok=True)
        self.items.clear()

    def combined_text(self) -> str:
        return "\n\n".join(
            f"--- Ảnh {index}: {item.name} ---\n{item.text.strip()}"
            for index, item in enumerate(self.items, 1)
            if item.text.strip()
        )
