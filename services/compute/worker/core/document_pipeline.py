"""Adapt the Native–ML_s44 handoff to the persistent CPU/CUDA/DirectML worker."""
import base64
from collections.abc import Iterator
import io
import math
import time

import cv2
import numpy as np
from PIL import Image

from native import viethandocr_application as native


MAX_LINES = 200
# Native builds several full-size masks and label arrays. Cap its working image
# so several workers can handle phone photos without exhausting host RAM.
MAX_WORK_PIXELS = 4_000_000
MAX_WORK_SIDE = 4096
PREVIEW_MAX_SIDE = 720
LINE_THUMB_MAX_W = 420
LINE_THUMB_HEIGHT = 48


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


def _encode_jpeg_data_url(image: Image.Image, max_side: int = PREVIEW_MAX_SIDE, quality: int = 72) -> str:
    rgb = image.convert("RGB")
    if max(rgb.size) > max_side:
        scale = max_side / max(rgb.size)
        rgb = rgb.resize(
            (max(2, round(rgb.width * scale)), max(2, round(rgb.height * scale))),
            Image.Resampling.LANCZOS,
        )
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def encode_line_thumb(prepared: Image.Image) -> str:
    rgb = prepared.convert("RGB")
    h = LINE_THUMB_HEIGHT
    w = max(24, min(LINE_THUMB_MAX_W, round(rgb.width * h / max(1, rgb.height))))
    thumb = rgb.resize((w, h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=70, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _order_quad(pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float64).reshape(4, 2)
    s = pts.sum(axis=1)
    d = pts[:, 1] - pts[:, 0]
    tl = pts[int(np.argmin(s))]
    br = pts[int(np.argmax(s))]
    tr = pts[int(np.argmin(d))]
    bl = pts[int(np.argmax(d))]
    return np.array([tl, tr, br, bl], dtype=np.float64)


def _scale_polygon(poly, sx: float, sy: float, orig_w: int, orig_h: int) -> list[list[float]]:
    out = []
    for pt in poly:
        x = max(0.0, min(float(orig_w), float(pt[0]) * sx))
        y = max(0.0, min(float(orig_h), float(pt[1]) * sy))
        out.append([round(x, 1), round(y, 1)])
    return out


def _poly_bbox(poly: list[list[float]]) -> list[float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]


def _extract_paper_quad(
    source_paper: np.ndarray,
    route: str,
    orig_w: int,
    orig_h: int,
    work_w: int,
    work_h: int,
    line_polys: list[list[list[float]]],
) -> tuple[bool, list[list[float]]]:
    sx = orig_w / max(1, work_w)
    sy = orig_h / max(1, work_h)
    if route == "scanner" and source_paper is not None and source_paper.any():
        mask = (source_paper.astype(np.uint8) * 255)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            hull = cv2.convexHull(largest)
            hull_area = max(1.0, cv2.contourArea(hull))
            peri = cv2.arcLength(hull, True)
            quad = None
            for eps in (0.02, 0.03, 0.04, 0.055):
                approx = cv2.approxPolyDP(hull, eps * peri, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    if cv2.contourArea(approx) >= 0.72 * hull_area:
                        quad = approx.reshape(4, 2)
                        break
            if quad is None:
                rect = cv2.minAreaRect(largest)
                quad = cv2.boxPoints(rect)
            ordered = _order_quad(quad)
            return True, _scale_polygon(ordered, sx, sy, orig_w, orig_h)

    if line_polys:
        xs = [p[0] for poly in line_polys for p in poly]
        ys = [p[1] for poly in line_polys for p in poly]
        pad_x = max(8.0, orig_w * 0.035)
        pad_y = max(8.0, orig_h * 0.035)
        x0 = max(0.0, min(xs) - pad_x)
        y0 = max(0.0, min(ys) - pad_y)
        x1 = min(float(orig_w), max(xs) + pad_x)
        y1 = min(float(orig_h), max(ys) + pad_y)
        return False, [[round(x0, 1), round(y0, 1)], [round(x1, 1), round(y0, 1)], [round(x1, 1), round(y1, 1)], [round(x0, 1), round(y1, 1)]]

    mx = round(orig_w * 0.02, 1)
    my = round(orig_h * 0.02, 1)
    return False, [[mx, my], [round(orig_w - mx, 1), my], [round(orig_w - mx, 1), round(orig_h - my, 1)], [mx, round(orig_h - my, 1)]]


def _build_previews(work: Image.Image, document: dict, paper_quad_work: np.ndarray | None) -> dict[str, str]:
    overlay = np.array(work.convert("RGB"), dtype=np.float32)
    outside = ~document["source_paper"]
    discarded = document["source_discarded"]
    if outside.any():
        overlay[outside] = overlay[outside] * 0.52 + np.array([235.0, 68.0, 56.0], dtype=np.float32) * 0.48
    if discarded.any():
        overlay[discarded] = overlay[discarded] * 0.68 + np.array([245.0, 168.0, 42.0], dtype=np.float32) * 0.32
    overlay_u8 = np.clip(overlay, 0, 255).astype(np.uint8)
    if paper_quad_work is not None:
        pts = np.round(paper_quad_work).astype(np.int32).reshape((-1, 1, 2))
        thickness = max(2, int(round(max(work.size) / 360.0)))
        cv2.polylines(overlay_u8, [pts], True, (114, 230, 138), thickness, cv2.LINE_AA)

    ink_only = Image.fromarray(document["ink_image"]).convert("RGB")
    ink_mask_arr = np.where(document["ink_mask"], 22, 248).astype(np.uint8)
    ink_mask_img = Image.fromarray(ink_mask_arr).convert("RGB")
    return {
        "paperOverlay": _encode_jpeg_data_url(Image.fromarray(overlay_u8)),
        "inkOnly": _encode_jpeg_data_url(ink_only),
        "inkMask": _encode_jpeg_data_url(ink_mask_img),
    }


def _crops(image: Image.Image, layout: str):
    config = native.APPLICATION_AUTO_SCANNER_CONFIG
    work = _working_image(image)
    t_pre = time.perf_counter()
    document = native.preprocess_document(work, config, mode="auto")
    preprocess_ms = (time.perf_counter() - t_pre) * 1000.0
    if not document["foreground"].any():
        raise ValueError("Không phát hiện nét chữ. Hãy chọn ảnh rõ hơn hoặc cắt vùng chữ.")
    scanner = document["route"] == "scanner"
    t_seg = time.perf_counter()
    if layout == "line":
        # A user chose an already cropped line. Keep it together, including marks.
        box = document.get("ink_bbox") or [0, 0, work.width, work.height]
        poly = native.scanner_source_polygon(box, document["source_to_working"])
        crops = [
            {"line_id": 1, "image": document["ink_image"], "mask": document["ink_mask"], "bbox": box, "source_polygon": poly}
            if scanner else {"line_id": 1, "image": document["native_gray"], "bbox": box, "source_polygon": poly}
        ]
    elif layout == "auto":
        result = native.segment_native_adaptive(document["native_gray"], keep_branches=False)["result"]
        if result is None:
            raise ValueError("Không tách được dòng chữ. Hãy cắt một dòng và chọn Một dòng.")
        crops = native.document_line_crops(document, result) if scanner else result["crops"]
    else:
        raise ValueError("Chế độ đọc không hợp lệ.")
    segment_ms = (time.perf_counter() - t_seg) * 1000.0
    if not crops:
        raise ValueError("Không tách được dòng chữ. Hãy cắt một dòng và chọn Một dòng.")
    if len(crops) > MAX_LINES:
        raise ValueError(f"Tối đa {MAX_LINES} dòng mỗi ảnh. Hãy chia trang thành nhiều ảnh.")
    return crops, scanner, config.line_render, work, document, preprocess_ms, segment_ms


def prepare_lines(image: Image.Image, layout: str) -> tuple[int, Iterator[Image.Image]]:
    crops, scanner, render, *_ = _crops(image, layout)

    def prepared():
        for crop in crops:
            if scanner:
                yield native.prepare_scanner_line(crop, render)[1]
            else:
                rgb = Image.fromarray(np.asarray(crop["image"])).convert("RGB")
                yield native.prepare_image(rgb, "v2c")[0]

    return len(crops), prepared()


def prepare_document_bundle(image: Image.Image, layout: str) -> dict:
    """Run Native preprocessing + line segmentation and expose Lens & Pipeline metadata."""
    orig_w, orig_h = image.size
    crops, scanner, render, work, document, preprocess_ms, segment_ms = _crops(image, layout)
    work_w, work_h = work.size
    sx = orig_w / max(1, work_w)
    sy = orig_h / max(1, work_h)

    line_metas = []
    line_polys = []
    for idx, crop in enumerate(crops, 1):
        if "source_polygon" in crop and crop["source_polygon"] is not None:
            raw_poly = crop["source_polygon"]
        else:
            box = crop.get("bbox") or [0, 0, work_w, work_h]
            raw_poly = native.scanner_source_polygon(box, document["source_to_working"])
        scaled_poly = _scale_polygon(raw_poly, sx, sy, orig_w, orig_h)
        line_polys.append(scaled_poly)
        line_metas.append(
            {
                "lineId": int(crop.get("line_id", idx)),
                "polygon": scaled_poly,
                "bbox": _poly_bbox(scaled_poly),
            }
        )

    paper_detected, paper_quad = _extract_paper_quad(
        document["source_paper"], document["route"], orig_w, orig_h, work_w, work_h, line_polys
    )
    paper_quad_work = np.array([[p[0] / sx, p[1] / sy] for p in paper_quad], dtype=np.float64)
    previews = _build_previews(work, document, paper_quad_work)

    def prepared():
        for crop, meta in zip(crops, line_metas):
            if scanner:
                img = native.prepare_scanner_line(crop, render)[1]
            else:
                rgb = Image.fromarray(np.asarray(crop["image"])).convert("RGB")
                img = native.prepare_image(rgb, "v2c")[0]
            yield meta, img

    return {
        "total": len(crops),
        "lines": prepared(),
        "sourceWidth": orig_w,
        "sourceHeight": orig_h,
        "workWidth": work_w,
        "workHeight": work_h,
        "route": str(document["route"]),
        "reasons": [str(r) for r in document.get("reasons", [])],
        "geometry": str(document.get("geometry", "identity")),
        "reviewFlags": [str(f) for f in document.get("review_flags", [])],
        "paperDetected": paper_detected,
        "paperQuad": paper_quad,
        "preprocessMs": round(preprocess_ms, 2),
        "segmentMs": round(segment_ms, 2),
        "previews": previews,
    }
