"""Image batches and assistant states, independent of the desktop toolkit."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

MAX_IMAGES = 10
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
    image: Image.Image
    source: str = "Camera"
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "ready"
    text: str = ""
    error: str = ""
    seconds: float = 0.0

    def rotate(self) -> None:
        self.image = self.image.transpose(Image.Transpose.ROTATE_90)
        self.status, self.text, self.error, self.seconds = "ready", "", "", 0.0


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

    @property
    def remaining(self) -> int:
        return MAX_IMAGES - len(self.items)

    def check_capacity(self, count: int) -> None:
        if count > self.remaining:
            raise BatchFullError(
                f"Mỗi lượt tối đa {MAX_IMAGES} ảnh. Bạn còn có thể thêm "
                f"{self.remaining} ảnh; đã chọn {count} ảnh."
            )

    def add(self, image: Image.Image, name: str, source: str = "Camera") -> ImageItem:
        self.check_capacity(1)
        item = ImageItem(name=name, image=prepare_image(image), source=source)
        self.items.append(item)
        return item

    def get(self, item_id: str | None) -> ImageItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def remove(self, item_id: str) -> None:
        self.items[:] = [item for item in self.items if item.id != item_id]

    def combined_text(self) -> str:
        return "\n\n".join(
            f"--- Ảnh {index}: {item.name} ---\n{item.text.strip()}"
            for index, item in enumerate(self.items, 1)
            if item.text.strip()
        )
