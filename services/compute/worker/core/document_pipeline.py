"""Adapt the Native–ML_s44 handoff to the persistent CPU/CUDA/DirectML worker."""
from collections.abc import Iterator
import math

import numpy as np
from PIL import Image

from native import viethandocr_application as native


MAX_LINES = 200
# Native builds several full-size masks and label arrays. Cap its working image
# so several workers can handle phone photos without exhausting host RAM.
MAX_WORK_PIXELS = 4_000_000
MAX_WORK_SIDE = 4096


def read_document(path, max_pixels: int) -> Image.Image:
    with Image.open(path) as source:
        if source.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Chỉ hỗ trợ ảnh JPEG, PNG và WebP.")
        if min(source.size) < 2 or source.width * source.height > max_pixels:
            raise ValueError("Ảnh vượt giới hạn kích thước. Hãy cắt vùng chữ trước khi gửi.")
        return native.decode_image(source)


def _working_image(image: Image.Image) -> Image.Image:
    scale = min(
        1.0,
        math.sqrt(MAX_WORK_PIXELS / (image.width * image.height)),
        MAX_WORK_SIDE / max(image.size),
    )
    if scale == 1:
        return image
    return image.resize(
        (max(2, int(image.width * scale)), max(2, int(image.height * scale))),
        Image.Resampling.LANCZOS,
        reducing_gap=3.0,
    )


def _crops(image: Image.Image, layout: str):
    config = native.APPLICATION_AUTO_SCANNER_CONFIG
    document = native.preprocess_document(_working_image(image), config, mode="auto")
    if not document["foreground"].any():
        raise ValueError("Không phát hiện nét chữ. Hãy chọn ảnh rõ hơn hoặc cắt vùng chữ.")
    scanner = document["route"] == "scanner"
    if layout == "line":
        # A user chose an already cropped line. Keep it together, including marks.
        crops = [
            {"image": document["ink_image"], "mask": document["ink_mask"]}
            if scanner else {"image": document["native_gray"]}
        ]
    elif layout == "auto":
        result = native.segment_native_adaptive(document["native_gray"], keep_branches=False)["result"]
        if result is None:
            raise ValueError("Không tách được dòng chữ. Hãy cắt một dòng và chọn Một dòng.")
        crops = native.document_line_crops(document, result) if scanner else result["crops"]
    else:
        raise ValueError("Chế độ đọc không hợp lệ.")
    if not crops:
        raise ValueError("Không tách được dòng chữ. Hãy cắt một dòng và chọn Một dòng.")
    if len(crops) > MAX_LINES:
        raise ValueError(f"Tối đa {MAX_LINES} dòng mỗi ảnh. Hãy chia trang thành nhiều ảnh.")
    return crops, scanner, config.line_render


def prepare_lines(image: Image.Image, layout: str) -> tuple[int, Iterator[Image.Image]]:
    crops, scanner, render = _crops(image, layout)

    def prepared():
        for crop in crops:
            if scanner:
                yield native.prepare_scanner_line(crop, render)[1]
            else:
                rgb = Image.fromarray(np.asarray(crop["image"])).convert("RGB")
                yield native.prepare_image(rgb, "v2c")[0]

    return len(crops), prepared()
