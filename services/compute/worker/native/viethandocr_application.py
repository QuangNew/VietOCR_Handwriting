"""Nhận dạng ảnh dòng và ảnh đoạn chữ viết tay tiếng Việt bằng Native–ML_s44.

VietOCR dùng giấy phép Apache-2.0, revision fe8c3a7fc714aec57ab81cec844eb3adf0c1636c.
Native lấy từ mã đã thực thi trong Notebook54 của dự án VietHandOCR.

Ví dụ gọi từ một dự án Python
    from viethandocr_application import LineRecognizer, process_image

    ocr = LineRecognizer()
    result = process_image("page.jpg", ocr, output_root="results")
    for line in result["lines"]:
        print(line["line_id"], line["text"], line["source_polygon"])

Hai tệp model_config.json và ml_s44_fp16.pth đặt trong model/ cạnh file này.
Kết quả chứa đường dẫn tương đối từ output_dir. Dùng source.png làm ảnh nền
khi vẽ source_polygon. output_root=None trả dữ liệu trong bộ nhớ.
CLI nhận một ảnh hoặc thư mục ảnh và lưu cùng định dạng kết quả.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import copy
import csv
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
import io
import json
import math
import os
from pathlib import Path
import sys
from tempfile import mkdtemp
import threading
import time
import unicodedata
import warnings


import numpy as np
import cv2
from PIL import Image, ImageOps
from scipy import ndimage
from scipy.ndimage import distance_transform_edt, gaussian_filter1d, maximum_filter1d
from scipy.signal import find_peaks
import torch
from torch import nn


# Chạy ứng dụng và lưu kết quả
def main():
    parser = argparse.ArgumentParser(description="Nhận dạng chữ viết tay tiếng Việt bằng ML_s44.")
    parser.add_argument("inputs", nargs="*", help="Ảnh hoặc thư mục ảnh. Mặc định đọc input.")
    parser.add_argument(
        "--output", type=Path, default=Path("viethandocr_output"), help="Thư mục kết quả."
    )
    parser.add_argument(
        "--preprocess",
        choices=("auto", "legacy", "scanner"),
        default=APPLICATION_DEFAULT_PREPROCESS,
        help="Tiền xử lý ảnh. Mặc định %(default)s.",
    )
    parser.add_argument("--preprocess-only", action="store_true", help="Xử lý ảnh và tách dòng.")
    parser.add_argument(
        "--figures",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Lưu ảnh các bước xử lý và ảnh mô hình ML_s44.",
    )
    args = parser.parse_intermixed_args()

    input_folder = Path.cwd() / "input"
    if not input_folder.is_dir():
        input_folder = Path(__file__).resolve().parent / "input"
    if not args.inputs and not input_folder.is_dir():
        parser.error("Truyền đường dẫn ảnh hoặc đặt ảnh trong thư mục input.")
    paths = collect_application_images(args.inputs or [input_folder], excluded=[args.output])
    if not paths:
        parser.error("Thư mục đầu vào không có ảnh hỗ trợ.")

    try:
        return run_application_batch(
            paths, args.output, args.preprocess, args.preprocess_only, figures=args.figures
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1


def run_application_batch(paths, output_root, preprocess, preprocess_only, *, figures=True):
    recognizer = None if preprocess_only else LineRecognizer(progress=print)
    cv2.setNumThreads(1)
    destination = create_output_folder(output_root)
    print(f"Kết quả lưu tại {destination}", flush=True)

    fields = (
        "source",
        "status",
        "preprocess_route",
        "geometry",
        "lines",
        "compute_seconds",
        "review_flags",
        "message",
        "output",
    )
    errors = 0
    summary = destination / "summary.csv"
    with summary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, path in enumerate(paths, 1):
            print(f"[{index}/{len(paths)}] {path}", flush=True)
            folder = (
                destination if len(paths) == 1 else destination / f"{index:04d}_{path.stem[:60]}"
            )
            row = {"source": str(path)}
            try:
                result = transcribe_image(
                    path,
                    recognizer,
                    preprocess=preprocess,
                    preprocess_only=preprocess_only,
                    capture_model=figures,
                )
                exported = export_result(result, folder, figures=figures)
                row["output"] = folder.relative_to(destination).as_posix()
            except (OSError, ValueError, RuntimeError, cv2.error) as error:
                row.update(status="error", message=str(error))
            else:
                row.update(
                    status=exported["status"],
                    preprocess_route=exported["route"],
                    geometry=exported["geometry"],
                    lines=len(exported["lines"]),
                    compute_seconds=round(exported["compute_cost"]["compute_seconds"], 3),
                    review_flags="|".join(exported["review_flags"]),
                    message=" | ".join(
                        filter(None, [exported["message"], *exported["visualization_warnings"]])
                    ),
                )
                print(
                    f"  {row['status']} · {row['preprocess_route']} · {row['lines']} dòng",
                    flush=True,
                )
                if len(paths) == 1 and exported["text"]:
                    print(exported["text"])
            if row["status"] in {"error", "failed"}:
                errors += 1
                print(f"  {row['message']}", file=sys.stderr)
            writer.writerow(row)
            handle.flush()
    print(f"Đã lưu {len(paths) - errors}/{len(paths)} kết quả. Tổng hợp tại {summary}")
    return int(errors > 0)


def create_output_folder(output_root):
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return Path(mkdtemp(prefix=datetime.now().strftime("%Y%m%d_%H%M%S_"), dir=root))


def process_image(
    source,
    recognizer=None,
    *,
    output_root=None,
    preprocess=None,
    preprocess_only=False,
    figures=True,
) -> dict:
    """Xử lý đường dẫn, bytes hoặc ảnh Pillow và trả dict tuần tự hóa được sang JSON.

    Dùng lại một LineRecognizer khi xử lý nhiều ảnh. Nếu có output_root, mỗi lượt
    xuất một thư mục con mới. Các đường dẫn trong kết quả tính từ output_dir.
    source_polygon đặt trên ảnh RGB đã định hướng EXIF, được lưu trong source.png.
    """
    if recognizer is None and not preprocess_only:
        recognizer = LineRecognizer()
    mode = APPLICATION_DEFAULT_PREPROCESS if preprocess is None else preprocess
    capture_model = output_root is not None and figures
    result = transcribe_image(
        source,
        recognizer,
        preprocess=mode,
        preprocess_only=preprocess_only,
        capture_model=capture_model,
    )
    directory = create_output_folder(output_root) if output_root is not None else None
    return export_result(result, directory, figures=figures)


def decode_image(source):
    path = Path(source) if isinstance(source, (str, os.PathLike)) else None
    if isinstance(source, (bytes, bytearray, memoryview)):
        source = io.BytesIO(source)
    opened_image = nullcontext(source) if isinstance(source, Image.Image) else Image.open(source)
    with opened_image as opened:
        if getattr(opened, "n_frames", 1) != 1 or min(opened.size) < 2:
            raise ValueError("Đầu vào phải là một ảnh có ít nhất hai pixel mỗi chiều.")
        info = dict(opened.info.get("viethandocr_source", {}))
        info.setdefault("original_size", list(opened.size))
        info.setdefault("exif_orientation", opened.getexif().get(274))
        image = ImageOps.exif_transpose(opened)

    if path is not None:
        info["name"] = path.name
    if "A" in image.getbands() or "transparency" in image.info:
        white = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(white, image.convert("RGBA"))
    image = image.convert("RGB")
    image.info["viethandocr_source"] = info
    return image


def recognize_lines(crops, recognizer, scanner_route, render, clock, *, capture_model=False):
    lines = []
    preview = None
    with torch.inference_mode(), torch.autocast(device_type=recognizer.device.type, enabled=False):
        for number, crop in enumerate(crops, 1):
            with clock.stage("v2c"):
                if scanner_route:
                    _, prepared, _ = prepare_scanner_line(crop, render)
                else:
                    image = Image.fromarray(crop["image"]).convert("RGB")
                    prepared, _ = prepare_image(image, "v2c")
            with clock.stage("tensor"):
                array, resized = recognizer.input_array(prepared)
                tensor = torch.from_numpy(array).unsqueeze(0).to(recognizer.device)
            with clock.stage("encoder"):
                cnn_features = recognizer.model.cnn(tensor)
                memory = recognizer.model.transformer.forward_encoder(cnn_features)
            with clock.stage("decoder"):
                decoded = recognizer.decode(memory)
            lines.append(
                {
                    **decoded,
                    "line_id": int(crop["line_id"]),
                    "bbox": crop["bbox"],
                    "image": crop["image"],
                    "resized": resized,
                }
            )
            if capture_model and number == len(crops):
                preview = (cnn_features, memory)
            del tensor, cnn_features, memory
    return lines, preview


def transcribe_image(
    image,
    recognizer,
    *,
    preprocess="legacy",
    scanner_config=None,
    preprocess_only=False,
    capture_model=False,
):
    image = decode_image(image)
    if scanner_config is None:
        scanner_config = (
            APPLICATION_AUTO_SCANNER_CONFIG if preprocess == "auto" else DocumentScannerConfig()
        )
    ocr = recognizer if not preprocess_only else None
    device = str(ocr.device) if ocr is not None else "cpu"
    clock = ComputeClock(ocr.synchronize) if ocr is not None else ComputeClock()
    memory = MemoryObservation(device)
    clock.synchronize()
    memory.start()
    started = time.perf_counter_ns()
    lines, preview = [], None
    try:
        with clock.stage("preprocess"):
            document = preprocess_document(image, scanner_config, mode=preprocess)
        with clock.stage("native"):
            native_input = document["native_gray"]
            backend = (
                segment_native_adaptive(native_input, keep_branches=False)
                if document["foreground"].any()
                else None
            )
            native = backend["result"] if backend is not None else None
            line_crops = document_line_crops(document, native)
            status = backend["status"] if backend is not None else "empty"
            message = "Không phát hiện mực." if status == "empty" else ""
            if status == "failed":
                message = "Native không tạo được dòng hợp lệ."
                document["review_flags"].append("native_failed")

        scanner_route = document["route"] == "scanner"
        crops = line_crops if scanner_route or native is None else native["crops"]
        if crops and not preprocess_only:
            if ocr is None:
                raise ValueError("Cần nạp ML_s44 trước khi nhận dạng.")
            lines, preview = recognize_lines(
                crops,
                ocr,
                scanner_route,
                scanner_config.line_render,
                clock,
                capture_model=capture_model,
            )
        with clock.stage("composition"):
            text = "\n".join(line["text"] for line in lines)
            if any(not line["ended_with_eos"] for line in lines):
                status, message = "partial", "Có dòng chạm giới hạn giải mã."
    finally:
        elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
        memory_values = memory.finish()

    model_features = None
    if preview is not None:
        model_features = tuple(tensor[:, 0, :].detach().cpu().numpy().T for tensor in preview)
    source = dict(image.info["viethandocr_source"], rgb_size=list(image.size))
    return {
        "image": image,
        "source": source,
        "document": document,
        "native_input": native_input,
        "native": backend,
        "line_crops": line_crops,
        "lines": lines,
        "text": text,
        "model_features": model_features,
        "status": status,
        "message": message,
        "preprocess_only": preprocess_only,
        "compute_seconds": elapsed,
        "stage_seconds": clock.seconds,
        "memory": memory_values,
        "device": device,
    }


def result_lines(result):
    """Gắn văn bản với đúng ID dòng, kể cả khi chỉ có vùng crop mà Native đưa vào OCR."""
    crops = {line["line_id"]: line for line in result["line_crops"]}
    recognized = {line["line_id"]: line for line in result["lines"]}
    lines = []
    for identifier in sorted(crops.keys() | recognized.keys()):
        crop = crops.get(identifier)
        ocr = recognized.get(identifier)
        if crop is not None:
            bbox, polygon = crop["bbox"], crop["source_polygon"]
        else:
            bbox = ocr["bbox"]
            polygon = scanner_source_polygon(bbox, result["document"]["source_to_working"])
        status = "segmented"
        if ocr is not None:
            status = "ok" if ocr["ended_with_eos"] else "partial"
        lines.append(
            {
                "line_id": int(identifier),
                "status": status,
                "text": ocr["text"] if ocr is not None else None,
                "bbox": list(map(int, bbox)),
                "source_polygon": polygon,
                "crop_path": None,
                "h64_path": None,
            }
        )
    return lines


def export_result(result, directory=None, *, figures=False):
    document = result["document"]
    matrix = document["source_to_working"]
    info = {
        key: document[key]
        for key in ("mode", "route", "geometry", "configuration", "ink_bbox", "review_flags")
    }
    info.update(
        schema_version=1,
        source=result["source"],
        coordinate_space="source_after_exif",
        status=result["status"],
        message=result["message"],
        preprocess_only=result["preprocess_only"],
        text=None if result["preprocess_only"] else result["text"],
        source_to_working=matrix.tolist(),
        working_to_source=np.linalg.inv(matrix).tolist(),
        lines=result_lines(result),
        files={},
        visualization_warnings=[],
    )
    if not result["preprocess_only"]:
        info["recognition"] = {
            "model": "ML_s44",
            "input": "V2c/H64",
            "precision": "float32",
            "decoder": "greedy",
            "max_decode_steps": 257,
        }
    cost = {
        key: result[key]
        for key in (
            "status",
            "device",
            "preprocess_only",
            "compute_seconds",
            "stage_seconds",
            "memory",
        )
    }
    cost.update(
        preprocess_route=document["route"],
        line_count=len(info["lines"]),
        measurement_boundary="Từ ảnh RGB trong RAM đến kết quả xử lý ảnh hoặc bản chép. "
        "Đọc ảnh, nạp mô hình, lưu tệp và dựng hình nằm ngoài khoảng đo.",
    )
    if directory is not None:
        directory = Path(directory).resolve()
        save_result_files(result, directory, info, figures=figures)
        info["files"].update(compute_cost="compute_cost.json", preprocessing="preprocessing.json")
        (directory / "compute_cost.json").write_text(
            json.dumps(cost, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (directory / "preprocessing.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return {
        **info,
        "compute_cost": cost,
        "output_dir": str(directory) if directory is not None else None,
    }


def save_result_files(result, directory, info, *, figures):
    line_folder = directory / "lines"
    line_folder.mkdir(parents=True, exist_ok=True)
    document = result["document"]
    result["image"].save(directory / "source.png")
    Image.fromarray(document["ink_image"]).save(directory / "ink_only.png")
    Image.fromarray(document["ink_mask"].astype(np.uint8) * 255).save(directory / "ink_mask.png")

    overlay = np.array(result["image"])
    outside, discarded = ~document["source_paper"], document["source_discarded"]
    overlay[outside] = overlay[outside] * 0.55 + np.array([255, 68, 52]) * 0.45
    overlay[discarded] = overlay[discarded] * 0.70 + np.array([255, 164, 42]) * 0.30
    Image.fromarray(overlay).save(directory / "rejected_overlay.png")

    info["files"].update(
        source="source.png",
        ink_only="ink_only.png",
        ink_mask="ink_mask.png",
        rejected_overlay="rejected_overlay.png",
    )
    lines = {line["line_id"]: line for line in info["lines"]}
    crops = {line["line_id"]: line["image"] for line in result["lines"]}
    crops.update({line["line_id"]: line["image"] for line in result["line_crops"]})
    for identifier, image in crops.items():
        name = f"lines/line_{identifier:03}.png"
        Image.fromarray(image).save(directory / name)
        lines[identifier]["crop_path"] = name
    for line in result["lines"]:
        name = f"lines/line_{line['line_id']:03}_h64.png"
        line["resized"].save(directory / name)
        lines[line["line_id"]]["h64_path"] = name

    if not result["preprocess_only"]:
        (directory / "transcription.txt").write_text(result["text"], encoding="utf-8")
        info["files"]["transcription"] = "transcription.txt"
    if figures:
        pictures, warnings = save_visualizations(result, directory)
        info["files"].update(pictures)
        info["visualization_warnings"] = warnings


def save_result(result, directory, *, figures=False):
    export_result(result, directory, figures=figures)
    return Path(directory)


# Ảnh xử lý và đặc trưng mô hình
FIGURE_BACKGROUND = "#F1F5F7"
FIGURE_TEXT = "#123047"
FIGURE_MUTED = "#476275"
FIGURE_ACCENT = "#0A756D"


def figure_heading(figure, title, subtitle):
    height = figure.get_figheight()
    figure.text(
        0.035, 1 - 0.26 / height, title, va="top", color=FIGURE_TEXT, fontsize=22, fontweight="bold"
    )
    figure.text(
        0.035,
        1 - 0.69 / height,
        subtitle,
        va="top",
        color=FIGURE_MUTED,
        fontsize=11,
        parse_math=False,
    )


def image_panel(axis, image, title):
    pixels = np.asarray(image)
    if pixels.ndim == 2:
        axis.imshow(pixels, cmap="gray", vmin=0, vmax=255)
    else:
        axis.imshow(pixels)
    height, width = pixels.shape[:2]
    axis.set_title(
        f"{title}  ·  {width} × {height} px",
        loc="left",
        pad=11,
        fontsize=11,
        color=FIGURE_TEXT,
        fontweight="bold",
    )
    axis.set_anchor("N")
    axis.set_axis_off()


def save_pipeline_picture(result, target):
    from matplotlib.figure import Figure
    from matplotlib.patches import Polygon

    source = result["image"]
    ink = result["document"]["ink_image"]
    crops = result["line_crops"]
    ocr_line = result["lines"][-1] if result["lines"] else None
    if ocr_line is not None:
        example = next((line for line in crops if line["line_id"] == ocr_line["line_id"]), ocr_line)
    else:
        example = crops[-1] if crops else None
    details = []
    if example is not None:
        details.append((example["image"], f"Ảnh cắt dòng {example['line_id']}"))
    if ocr_line is not None:
        details.append(
            (np.asarray(ocr_line["resized"]), f"Đầu vào H64 của dòng {ocr_line['line_id']}")
        )

    page_height = np.clip(
        4.3 * max(source.height / source.width, ink.shape[0] / ink.shape[1]), 0.48, 5.25
    )
    height = page_height + 1.53
    if details:
        detail_ratio = max(image.shape[0] / image.shape[1] for image, _ in details)
        detail_height = np.clip(13.3 * detail_ratio / len(details), 0.58, 1.4)
        height += 0.47 + detail_height
    figure = Figure(figsize=(14.4, height), facecolor=FIGURE_BACKGROUND)
    name = result["source"].get("name", "Ảnh đầu vào")
    route = (
        "Tách mực nhánh scanner"
        if result["document"]["route"] == "scanner"
        else "Tiền xử lý Native gốc"
    )
    figure_heading(figure, "Từ ảnh đầu vào đến từng dòng", f"{name}  ·  {route}")
    grid = figure.add_gridspec(
        1,
        3,
        left=0.035,
        right=0.965,
        top=1 - 1.25 / height,
        bottom=1 - (1.25 + page_height) / height,
        wspace=0.11,
    )
    image_panel(figure.add_subplot(grid[0, 0]), source, "Ảnh đầu vào")
    image_panel(figure.add_subplot(grid[0, 1]), ink, "Mực chữ đã tách")
    positions = figure.add_subplot(grid[0, 2])
    lines = result_lines(result)
    image_panel(positions, source, f"Vị trí {len(lines)} dòng")
    colors = ("#096B63", "#4338AA", "#A05308")
    for line in lines:
        polygon = line["source_polygon"]
        identifier = line["line_id"]
        color = colors[(identifier - 1) % len(colors)]
        positions.add_patch(Polygon(polygon, fill=False, edgecolor=color, linewidth=1.35))
        positions.annotate(
            str(identifier),
            polygon[0],
            xytext=(3, 2),
            textcoords="offset points",
            color="white",
            fontsize=8,
            bbox={"boxstyle": "round,pad=0.18", "fc": color, "ec": "none"},
        )
    positions.set(xlim=(-0.5, source.width - 0.5), ylim=(source.height - 0.5, -0.5))

    if details:
        previews = figure.add_gridspec(
            1,
            len(details),
            left=0.035,
            right=0.965,
            wspace=0.15,
            bottom=0.28 / height,
            top=(0.28 + detail_height) / height,
        )
        for index, (image, title) in enumerate(details):
            image_panel(figure.add_subplot(previews[0, index]), image, title)
    figure.savefig(target, dpi=155, backend="agg")
    figure.clear()


def draw_model_flow(axis, stages):
    from matplotlib.patches import FancyBboxPatch

    axis.set_axis_off()
    for index, (title, description) in enumerate(stages):
        left = 0.012 + index * 0.255
        axis.add_patch(
            FancyBboxPatch(
                (left, 0.16),
                0.21,
                0.69,
                boxstyle="round,pad=0.008,rounding_size=0.04",
                facecolor="#FFFFFF",
                edgecolor="#AECAC9",
                linewidth=1,
                transform=axis.transAxes,
            )
        )
        axis.text(
            left + 0.105,
            0.59,
            title,
            ha="center",
            va="center",
            transform=axis.transAxes,
            fontsize=12,
            fontweight="bold",
            color=FIGURE_TEXT,
        )
        axis.text(
            left + 0.105,
            0.36,
            description,
            ha="center",
            va="center",
            transform=axis.transAxes,
            fontsize=10,
            color=FIGURE_MUTED,
        )
        if index < len(stages) - 1:
            axis.annotate(
                "",
                xy=(left + 0.245, 0.5),
                xytext=(left + 0.222, 0.5),
                xycoords="axes fraction",
                arrowprops={"arrowstyle": "-|>", "color": FIGURE_ACCENT, "linewidth": 1.5},
            )


def draw_feature_map(figure, axis, features, title):
    channels = np.sort(np.argsort(features.std(axis=1), kind="stable")[-24:])
    values = features[channels]
    scale = max(float(np.quantile(np.abs(values), 0.98)), 1e-5)
    heatmap = axis.imshow(
        values, aspect="auto", interpolation="nearest", cmap="RdBu_r", vmin=-scale, vmax=scale
    )
    rows = np.linspace(0, len(channels) - 1, min(6, len(channels)), dtype=int)
    axis.set_yticks(rows, channels[rows])
    axis.set_xlabel("Vị trí trong chuỗi ảnh", color=FIGURE_MUTED)
    axis.set_ylabel(f"{len(channels)} kênh chọn lọc", color=FIGURE_MUTED)
    axis.tick_params(labelsize=9, colors=FIGURE_MUTED)
    axis.set_title(title, loc="left", pad=10, color=FIGURE_TEXT, fontsize=13, fontweight="bold")
    for spine in axis.spines.values():
        spine.set_color("#AEC0CD")
    bar = figure.colorbar(heatmap, ax=axis, fraction=0.035, pad=0.03, extend="both")
    bar.ax.tick_params(labelsize=8, colors=FIGURE_MUTED)
    bar.outline.set_visible(False)


def save_model_picture(result, target):
    from matplotlib.figure import Figure
    from textwrap import shorten

    line = result["lines"][-1]
    cnn, encoder = result["model_features"]
    figure = Figure(figsize=(14.4, 8.35), facecolor=FIGURE_BACKGROUND)
    name = result["source"].get("name", "Ảnh đầu vào")
    figure_heading(
        figure,
        "Bên trong ML_s44",
        f"{name}  ·  Dòng {line['line_id']}  ·  Đặc trưng từ lượt nhận dạng",
    )
    grid = figure.add_gridspec(
        4,
        2,
        left=0.065,
        right=0.95,
        top=0.86,
        bottom=0.045,
        height_ratios=(0.82, 0.75, 2.55, 0.78),
        hspace=0.42,
        wspace=0.28,
    )
    tokens = line["token_ids"][1:]
    draw_model_flow(
        figure.add_subplot(grid[0, :]),
        (
            ("Ảnh H64", f"{line['resized'].width} × {line['resized'].height} px RGB"),
            ("VGG19-BN", f"{cnn.shape[0]} kênh · {cnn.shape[1]} vị trí"),
            ("Transformer Encoder", f"{encoder.shape[0]} chiều · {encoder.shape[1]} vị trí"),
            ("Transformer Decoder", f"{len(tokens)} bước greedy"),
        ),
    )
    input_line = figure.add_subplot(grid[1, :])
    input_line.imshow(line["resized"])
    input_line.set_axis_off()
    draw_feature_map(figure, figure.add_subplot(grid[2, 0]), cnn, "Đặc trưng từ CNN")
    draw_feature_map(
        figure, figure.add_subplot(grid[2, 1]), encoder, "Đặc trưng sau Transformer Encoder"
    )

    output = figure.add_subplot(grid[3, :])
    output.set_axis_off()
    output.text(
        0, 0.91, "Dòng nhận dạng", va="top", fontsize=11, fontweight="bold", color=FIGURE_ACCENT
    )
    output.text(
        0,
        0.63,
        shorten(line["text"], width=125, placeholder="…"),
        va="top",
        fontsize=16,
        color=FIGURE_TEXT,
        parse_math=False,
    )
    token_text = " · ".join(str(token) for token in tokens[:20])
    if len(tokens) > 20:
        token_text += " · …"
    output.text(0, 0.24, f"ID token   {token_text}", va="top", fontsize=10, color=FIGURE_MUTED)
    figure.savefig(target, dpi=155, backend="agg")
    figure.clear()


def save_visualizations(result, directory):
    directory = Path(directory)
    figures = [("pipeline", save_pipeline_picture)]
    if result["model_features"] is not None:
        figures.append(("model", save_model_picture))

    files, warnings = {}, []
    for name, draw in figures:
        filename = f"{name}.png"
        try:
            draw(result, directory / filename)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            warnings.append(f"{filename}: {error}")
        else:
            files[name] = filename
    return files, warnings


# Cấu hình tách thành phần
@dataclass(frozen=True)
class SplitEvidenceConfig:
    enabled: bool = True
    anchor_radius_chars: float = 0.3
    min_anchor_columns_chars: float = 0.35
    min_anchor_area_chars2: float = 0.025
    min_part_height_chars: float = 0.3
    prune_empty_cores: bool = True

    def __post_init__(self):
        if not 0 < self.anchor_radius_chars < 0.48:
            raise ValueError("Anchor tube must lie inside the line body band")
        if (
            min(
                self.min_anchor_columns_chars,
                self.min_anchor_area_chars2,
                self.min_part_height_chars,
            )
            <= 0
        ):
            raise ValueError("Split evidence thresholds must be positive")


# Cấu hình Support
@dataclass(frozen=True)
class SupportConfig:
    analysis_width: int = 1200
    max_skew_degrees: float = 10.0
    skew_step_degrees: float = 0.5
    seed_prominence: float = 0.12
    min_separation_chars: float = 0.85
    local_profile_weight: float = 0.25
    support_fraction: float = 0.18
    residual_distance_chars: float = 0.7
    residual_min_mass_chars2: float = 0.18
    residual_min_pitch_fraction: float = 0.65
    residual_pitch_cap_chars: float = 3.0
    residual_body_height_chars: float = 0.75
    residual_body_area_chars2: float = 0.1
    residual_single_body_width_chars: float = 2.0
    multi_line_min_fraction: float = 0.18
    mark_max_height_chars: float = 0.65
    mark_max_area_chars2: float = 0.2
    mark_assignment_mode: str = "bbox_legacy"
    mark_core_protection_chars: float = 0.32
    protect_compact_bodies: bool = True
    padding: int = 8
    recover_residual: bool = True
    assign_marks: bool = True
    split_components: bool = True
    limit_x_support: bool = True
    deskew: bool = True

    def __post_init__(self):
        if self.analysis_width < 128 or self.padding < 0:
            raise ValueError("Invalid analysis width/padding")
        if not 0 <= self.max_skew_degrees <= 20 or self.skew_step_degrees <= 0:
            raise ValueError("Invalid skew search")
        if not 0 < self.seed_prominence < 1 or self.min_separation_chars <= 0:
            raise ValueError("Invalid seed configuration")
        if not 0 < self.multi_line_min_fraction < 0.5:
            raise ValueError("Invalid multi-line gate")
        if not 0 <= self.local_profile_weight <= 1 or not 0 < self.support_fraction <= 1:
            raise ValueError("Invalid profile/support weight")
        if not 0 < self.residual_min_pitch_fraction < 1:
            raise ValueError("Invalid residual pitch separation")
        if (
            min(
                self.residual_distance_chars,
                self.residual_min_mass_chars2,
                self.residual_body_height_chars,
                self.residual_body_area_chars2,
                self.residual_single_body_width_chars,
                self.residual_pitch_cap_chars,
            )
            <= 0
        ):
            raise ValueError("Residual evidence thresholds must be positive")
        if self.mark_assignment_mode not in ("bbox_legacy", "body_pixel"):
            raise ValueError("Unknown compact-component assignment mode")
        if not 0 < self.mark_core_protection_chars < 0.48:
            raise ValueError("Compact body protection must lie inside the body tube")


# Cấu hình hợp nhất lõi và router
@dataclass(frozen=True)
class AdaptiveConfig:
    merge_fragments: bool = True
    restrict_body_support: bool = False
    prefer_dip_on_count_agreement: bool = True
    fragment_q10_gap_chars: float = 0.5
    fragment_median_gap_chars: float = 1.5
    fragment_max_x_overlap: float = 0.5
    weak_body_width_chars: float = 1.0
    weak_neighbor_ratio: float = 3.0
    weak_q10_gap_chars: float = 0.55
    body_support_padding_chars: float = 1.5
    collapse_single_line: bool = False
    single_line_max_residual_chars: float = 0.3
    support_decoder: str = "support"
    support: SupportConfig = field(
        default_factory=lambda: SupportConfig(mark_assignment_mode="body_pixel")
    )
    split: SplitEvidenceConfig = field(
        default_factory=lambda: SplitEvidenceConfig(
            min_anchor_columns_chars=0.75, min_anchor_area_chars2=0.015, min_part_height_chars=0.45
        )
    )

    def __post_init__(self):
        if self.support_decoder not in ("support", "stage2"):
            raise ValueError("Unknown geometric decoder")
        if not 0 < self.fragment_max_x_overlap < 1:
            raise ValueError("Horizontal overlap threshold must be between zero and one")
        if (
            min(
                self.fragment_q10_gap_chars,
                self.fragment_median_gap_chars,
                self.weak_body_width_chars,
                self.weak_neighbor_ratio,
                self.weak_q10_gap_chars,
                self.body_support_padding_chars,
                self.single_line_max_residual_chars,
            )
            <= 0
        ):
            raise ValueError("Geometric thresholds must be positive")


# Cấu hình thang chữ
@dataclass(frozen=True)
class BodyScaleConfig:
    method: str = "legacy"
    height_quantile: float = 0.65
    min_area_pixels: float = 12.0
    min_height_pixels: float = 5.0
    min_width_pixels: float = 2.0
    min_scale_pixels: float = 6.0
    min_height_strokes: float = 2.5
    min_width_strokes: float = 0.75
    min_area_strokes2: float = 3.0
    stroke_peak_weight_power: float = 2.0
    log_height_bandwidth: float = 0.22
    mode_grid_points: int = 257
    component_weight_cap: float = 4.0

    def __post_init__(self):
        if self.method not in ("legacy", "source_gate", "stroke_quantile", "stroke_mode"):
            raise ValueError("Unknown body-scale estimator")
        if not 0 < self.height_quantile < 1:
            raise ValueError("Height quantile must lie in (0,1)")
        positive = [
            self.min_area_pixels,
            self.min_height_pixels,
            self.min_width_pixels,
            self.min_scale_pixels,
            self.min_height_strokes,
            self.min_width_strokes,
            self.min_area_strokes2,
            self.stroke_peak_weight_power,
            self.log_height_bandwidth,
            self.component_weight_cap,
        ]
        if not all((np.isfinite(value) and value > 0 for value in positive)):
            raise ValueError("Body-scale parameters must be finite and positive")
        if self.mode_grid_points < 33 or self.mode_grid_points % 2 != 1:
            raise ValueError("Use an odd mode grid with at least33 points")


# Cấu hình Native
@dataclass(frozen=True)
class NativeAdaptiveConfig:
    adaptive: AdaptiveConfig = field(
        default_factory=lambda: replace(AdaptiveConfig(), fragment_q10_gap_chars=0.55)
    )
    scale: BodyScaleConfig = field(
        default_factory=lambda: BodyScaleConfig(method="stroke_quantile")
    )

    @classmethod
    def from_dict(cls, values):
        values = dict(values)
        unknown = set(values) - {"adaptive", "scale"}
        if unknown:
            raise ValueError(f"Unknown native-adaptive config sections: {sorted(unknown)}")
        defaults = cls()
        updates = dict(values.get("adaptive", {}))
        adaptive = {**asdict(defaults.adaptive), **updates}
        adaptive["support"] = SupportConfig(
            **{**asdict(defaults.adaptive.support), **dict(updates.get("support", {}))}
        )
        adaptive["split"] = SplitEvidenceConfig(
            **{**asdict(defaults.adaptive.split), **dict(updates.get("split", {}))}
        )
        return cls(
            adaptive=AdaptiveConfig(**adaptive),
            scale=BodyScaleConfig(**{**asdict(defaults.scale), **dict(values.get("scale", {}))}),
        )


# Foreground Otsu
def binarize(gray):
    threshold, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return (b.astype(bool), float(threshold))


# Dựng crop theo ownership
def crops_from_owners(gray, owners, padding=8):
    ink, _ = binarize(gray)
    crops = []
    for label in sorted(set(np.unique(owners)) - {0}):
        yy, xx = np.nonzero(ink & (owners == label))
        if not len(xx):
            continue
        x0, x1 = (max(0, int(xx.min()) - padding), min(gray.shape[1], int(xx.max()) + 1 + padding))
        y0, y1 = (max(0, int(yy.min()) - padding), min(gray.shape[0], int(yy.max()) + 1 + padding))
        image = np.where(owners[y0:y1, x0:x1] == label, gray[y0:y1, x0:x1], 255).astype(np.uint8)
        crops.append(
            {"image": image, "line_id": int(label), "x0": x0, "y0": y0, "bbox": [x0, y0, x1, y1]}
        )
    return crops


# Router và bằng chứng thân chữ
def combine_image_hypotheses(dip, support, config=AdaptiveConfig(), *, decoder_cache=None):
    if config.support_decoder != "support":
        raise ValueError("This baseline fixes support_decoder='support'")
    if dip is None and support is None:
        raise ValueError("Both image hypotheses failed")
    if (
        dip is not None
        and support is not None
        and (not np.array_equal(dip["gray"], support["gray"]))
    ):
        raise ValueError("Hypotheses refer to different source images")
    dip_count = len(dip["crops"]) if dip is not None else None
    support_count = len(support["crops"]) if support is not None else None
    use_dip = dip is not None and (
        support is None or (config.prefer_dip_on_count_agreement and dip_count == support_count)
    )
    result = dict(dip if use_dip else support)
    decoder_error = None
    result["labels"] = result["labels"].copy()
    result["crops"] = crops_from_owners(result["gray"], result["labels"], 8)
    result["adaptive_decision"] = {
        "selected": "dip" if use_dip else "repaired_support",
        "dip_inferred_count": dip_count,
        "support_inferred_count": support_count,
        "reason": "count_agreement_prefer_dip"
        if use_dip and support is not None
        else "only_successful_hypothesis"
        if dip is None or support is None
        else "configured_support_preference"
        if not config.prefer_dip_on_count_agreement
        else "count_disagreement_use_body_recovered_cores",
        "reference_used": False,
    }
    result["adaptive_config"] = asdict(config)
    result["adaptive_decision"]["support_decoder"] = config.support_decoder
    result["adaptive_decision"]["decoder_fallback_error"] = decoder_error
    if support is not None:
        result["core_merge_decisions"] = support.get("core_merge_decisions", [])
        result["original_core_groups"] = support.get("original_core_groups", [])
    result["metrics"] = {
        **result.get("metrics", {}),
        "n_lines": len(result["crops"]),
        "semantic_accuracy_measured": False,
    }
    return result


def body_observations(base, char_height, *, with_points=False):
    ink = base["original_mask"]
    curves = base["original_ridges"]
    ch = char_height
    _, cc, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    body_x = np.zeros_like(base["support"], bool)
    counts = np.zeros(len(curves), int)
    points = [[] for _ in curves]
    for component in range(1, len(stats)):
        x, y, w, h, area = stats[component]
        if h < 0.45 * ch or area < 0.08 * ch**2:
            continue
        ly, lx = np.nonzero(cc[y : y + h, x : x + w] == component)
        yy, xx = (ly + y, lx + x)
        labels = base["labels"][yy, xx]
        line = int(np.bincount(labels).argmax())
        if line < 1 or np.mean(labels == line) < 0.85:
            continue
        if np.median(np.abs(yy - curves[line - 1, xx])) > 0.55 * ch:
            continue
        body_x[line - 1, x : x + w] = True
        counts[line - 1] += 1
        points[line - 1].append([float(np.mean(xx)), float(np.median(yy))])
    return (body_x, counts, points) if with_points else (body_x, counts)


# Halo luminance
def gray_halo(ink, ink_owners):
    if not ink.any() or np.any(ink_owners[ink] == 0):
        raise ValueError("Every source-ink pixel must have an owner")
    _, nearest = distance_transform_edt(~ink, return_indices=True)
    return ink_owners[tuple(nearest)].astype(np.uint16)


# Gate tách thành phần
def part_evidence(yy, xx, curve, supported, char_height, config):
    scale = float(char_height)
    if scale <= 0 or len(xx) == 0:
        raise ValueError("Part evidence needs nonempty ink and positive body scale")
    residual = yy.astype(float) - curve[xx]
    anchors = (np.abs(residual) <= config.anchor_radius_chars * scale) & supported[xx]
    columns = len(np.unique(xx[anchors])) / scale
    mass = int(anchors.sum()) / scale**2
    height = float(np.quantile(residual, 0.95) - np.quantile(residual, 0.05)) / scale
    reasons = []
    if columns < config.min_anchor_columns_chars:
        reasons.append("insufficient_independent_body_columns")
    if mass < config.min_anchor_area_chars2:
        reasons.append("insufficient_body_anchor_mass")
    if height < config.min_part_height_chars:
        reasons.append("part_has_insufficient_body_height")
    return {
        "pixels": len(xx),
        "anchor_columns_chars": float(columns),
        "anchor_area_chars2": float(mass),
        "part_height_chars": height,
        "body_supported": not reasons,
        "reasons": reasons,
    }


def refine_split_components(base, config=SplitEvidenceConfig(), *, char_height=None):
    started = time.perf_counter()
    gray = base["gray"]
    ink = base["original_mask"]
    curves, support = (np.asarray(base["original_ridges"]), np.asarray(base["support"]))
    if gray.ndim != 2 or gray.dtype != np.uint8 or ink.shape != gray.shape:
        raise ValueError("Need original uint8 grayscale and its foreground mask")
    if curves.ndim != 2 or curves.shape[1] != gray.shape[1] or support.shape != curves.shape:
        raise ValueError("Core/support dimensions do not match the source")
    if char_height is None:
        width = min(gray.shape[1], base["config"]["analysis_width"])
        height = max(2, round(gray.shape[0] * width / gray.shape[1]))
        char_height = base["analysis"]["char_height"] * gray.shape[0] / height
    count, cc, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    decisions = copy.deepcopy(base["component_decisions"])
    if count - 1 != len(decisions):
        raise ValueError("Component decisions do not match this foreground")
    owners = np.where(ink, base["labels"], 0).astype(np.uint16)
    proposed, rejected, changed = ([], [], np.zeros_like(ink, bool))
    for record in decisions:
        if not record["multi_line"]:
            continue
        component = record["component_id"]
        x, y, width, height, _ = stats[component]
        ly, lx = np.nonzero(cc[y : y + height, x : x + width] == component)
        yy, xx = (ly + y, lx + x)
        labels = owners[yy, xx].copy()
        parts = []
        for label in np.unique(labels):
            chosen = labels == label
            value = part_evidence(
                yy[chosen], xx[chosen], curves[label - 1], support[label - 1], char_height, config
            )
            parts.append({"line_id": int(label), **value})
        admitted = not config.enabled or len(parts) < 2 or all((p["body_supported"] for p in parts))
        winner = int(record.get("initial_line_id", record["line_id"]))
        decision = {
            "component_id": int(component),
            "bbox_xywh": [int(x), int(y), int(width), int(height)],
            "initial_vote_winner": winner,
            "parts": parts,
            "split_admitted": bool(admitted),
            "gate_enabled": config.enabled,
        }
        proposed.append(decision)
        if not admitted:
            owners[yy, xx] = winner
            changed[yy[labels != winner], xx[labels != winner]] = True
            rejected.append(component)
        record["split_evidence"] = decision
    active = sorted(set(np.unique(owners[ink])) - {0})
    if not active:
        raise ValueError("No text-line ownership after component decisions")
    removed = sorted(set(range(1, len(curves) + 1)) - set(active))
    result = dict(base)
    if removed and (not config.prune_empty_cores):
        raise ValueError("A core lost all owned ink; empty-core removal is disabled")
    if removed:
        mapping = np.zeros(len(curves) + 1, np.uint16)
        mapping[active] = np.arange(1, len(active) + 1, dtype=np.uint16)
        owners = mapping[owners]
        curves, support = (curves[np.asarray(active) - 1], support[np.asarray(active) - 1])
    labels = gray_halo(ink, owners) if changed.any() or removed else base["labels"].copy()
    result.update(
        labels=labels,
        original_ridges=curves,
        support=support,
        seams=np.rint((curves[:-1] + curves[1:]) / 2).astype(np.int32),
        crops=crops_from_owners(gray, labels, base["config"]["padding"]),
        component_decisions=decisions,
        split_evidence_decisions=proposed,
        split_evidence_config=asdict(config),
        removed_empty_core_ids=removed,
        active_original_core_ids=active,
        seams_are_ownership_boundaries=False,
    )
    metrics = dict(base["metrics"])
    metrics.update(
        n_lines=len(result["crops"]),
        proposed_split_components=len(proposed),
        rejected_split_components=len(rejected),
        split_gate_changed_foreground_pixels=int(changed.sum()),
        removed_empty_cores=len(removed),
        runtime_seconds_split_gate=time.perf_counter() - started,
        semantic_accuracy_measured=False,
    )
    result["metrics"] = metrics
    result["warnings"] = [*base.get("warnings", [])]
    if rejected:
        result["warnings"].append(
            {
                "type": "split_rejected_without_two_supported_bodies",
                "component_ids": [int(c) for c in rejected],
            }
        )
    if removed:
        result["warnings"].append(
            {"type": "empty_core_removed_after_ownership", "original_ids": removed}
        )
    return result


# Gán mực và thành phần nhỏ
def assign_marks_to_body_pixels(owners, cc, stats, marks, bodies, ridges, support, ch, cfg):
    eligible = []
    parent_ids = list(bodies)
    for component, record in marks:
        x, y, w, h, _ = stats[component]
        ly, lx = np.nonzero(cc[y : y + h, x : x + w] == component)
        yy, xx = (ly + y, lx + x)
        d = np.abs(yy[None, :] - ridges[:, xx]) / ch
        if cfg.limit_x_support:
            d += 1.5 * ~support[:, xx]
        protected = cfg.protect_compact_bodies and bool(
            np.max((d < cfg.mark_core_protection_chars).mean(axis=1)) >= 0.5
        )
        if protected:
            record.update(mark_role="core_supported_compact", mark_accepted=None)
            parent_ids.append(component)
        else:
            eligible.append((component, record, yy, xx))
    if not eligible:
        return
    candidates = {component: [] for component, _, _, _ in eligible}
    parent_mask = np.isin(cc, parent_ids)
    yy, xx = np.nonzero(parent_mask)
    labels = owners[yy, xx]
    for line in range(len(ridges)):
        selected = (labels == line + 1) & (np.abs(yy - ridges[line, xx]) < 0.45 * ch)
        if cfg.limit_x_support:
            selected &= support[line, xx]
        if not selected.any():
            continue
        body = np.zeros_like(parent_mask)
        body[yy[selected], xx[selected]] = True
        distances, nearest = distance_transform_edt(~body, sampling=(1.0, 1.7), return_indices=True)
        for component, record, my, mx in eligible:
            gap = float(np.quantile(distances[my, mx], 0.25)) / ch
            core_gap = float(np.median(np.abs(my - ridges[line, mx]))) / ch
            if gap > 1.05:
                continue
            score = gap + 0.12 * core_gap
            point = int(np.argmin(distances[my, mx]))
            parent = int(cc[nearest[0, my[point], mx[point]], nearest[1, my[point], mx[point]]])
            candidates[component].append((score, line + 1, parent, gap))
    for component, record, yy, xx in eligible:
        options = sorted(candidates[component])
        record["mark_role"] = "detached_compact_candidate"
        if not options:
            record.update(mark_accepted=False, mark_reason="no_supported_body_within_gate")
            continue
        best = options[0]
        margin = options[1][0] - best[0] if len(options) > 1 else None
        accepted = best[0] <= 1.05 and (margin is None or margin >= 0.12)
        record.update(
            mark_parent=best[2],
            mark_score=float(best[0]),
            mark_body_gap_chars=best[3],
            mark_margin=float(margin) if margin is not None else None,
            mark_accepted=bool(accepted),
            mark_reason="supported_body_pixel_distance" if accepted else "competing_body_support",
        )
        if accepted:
            owners[yy, xx] = best[1]
            record["line_id"] = best[1]


def assign_supported_owners(gray, ridges, support, ch, cfg):
    ink, _ = binarize(gray)
    n, cc, st, ct = cv2.connectedComponentsWithStats(ink.astype("uint8"), connectivity=8)
    line_count = len(ridges)
    owners = np.zeros_like(cc, dtype=np.uint16)
    bodies, marks, decisions = ([], [], [])
    for k in range(1, n):
        x, y, w, h, area = st[k]
        local = cc[y : y + h, x : x + w] == k
        ly, lx = np.nonzero(local)
        xx, yy = (lx + x, ly + y)
        distances = np.abs(yy[None, :] - ridges[:, xx]) / ch
        if cfg.limit_x_support:
            distances += 1.5 * ~support[:, xx]
        votes = np.exp(-0.5 * (distances / 0.4) ** 2).sum(axis=1)
        winner = int(votes.argmax())
        if votes.max() <= 1e-08:
            winner = int(distances.mean(axis=1).argmin())
        near_fraction = (distances < 0.48).mean(axis=1)
        substantial = np.flatnonzero(near_fraction >= cfg.multi_line_min_fraction)
        multiline = bool(len(substantial) > 1 and h > 0.8 * ch)
        compact = bool(
            h < cfg.mark_max_height_chars * ch and area < cfg.mark_max_area_chars2 * ch**2
        )
        record = {
            "component_id": int(k),
            "x": int(x),
            "y": int(y),
            "width": int(w),
            "height": int(h),
            "area": int(area),
            "line_id": winner + 1,
            "initial_line_id": winner + 1,
            "multi_line": multiline,
            "compact": compact,
            "body_fractions": near_fraction.tolist(),
        }
        if multiline and cfg.split_components:
            choices = distances[substantial].argmin(axis=0)
            owners[yy, xx] = (substantial[choices] + 1).astype(np.uint16)
        else:
            owners[yy, xx] = winner + 1
        if compact:
            marks.append((k, record))
        elif not multiline and area >= 0.035 * ch**2 and (h >= 0.28 * ch):
            bodies.append(k)
        decisions.append(record)
    if cfg.assign_marks and cfg.mark_assignment_mode == "body_pixel":
        assign_marks_to_body_pixels(owners, cc, st, marks, bodies, ridges, support, ch, cfg)
    elif cfg.assign_marks and bodies:
        for k, record in marks:
            x, y, w, h, area = st[k]
            candidates = []
            for parent in bodies:
                px, py, pw, ph, _ = st[parent]
                dx = max(0, x - (px + pw - 1), px - (x + w - 1))
                dy = max(0, y - (py + ph - 1), py - (y + h - 1))
                if dx > 0.65 * ch or dy > 0.85 * ch:
                    continue
                p_owners = owners[py : py + ph, px : px + pw][
                    cc[py : py + ph, px : px + pw] == parent
                ]
                label = int(np.bincount(p_owners).argmax())
                score = (1.7 * dx + dy + 0.12 * abs(ct[k, 0] - ct[parent, 0])) / ch
                candidates.append((float(score), label, parent))
            if candidates:
                candidates.sort()
                best = candidates[0]
                second = next((c for c in candidates if c[1] != best[1]), None)
                margin = second[0] - best[0] if second else None
                accepted = best[0] <= 1.05 and (margin is None or margin >= 0.12)
                record.update(
                    mark_parent=int(best[2]),
                    mark_score=best[0],
                    mark_margin=margin,
                    mark_accepted=bool(accepted),
                )
                if accepted:
                    local = cc[y : y + h, x : x + w] == k
                    owners[y : y + h, x : x + w][local] = best[1]
                    record["line_id"] = best[1]
    _, nearest = distance_transform_edt(~ink, return_indices=True)
    labels = owners[tuple(nearest)].astype(np.uint16)
    present = sorted(set(np.unique(owners[ink])) - {0})
    if present != list(range(1, line_count + 1)):
        raise ValueError("An inferred core has no owned ink; review required")
    return (labels, ink, decisions)


# Sửa mảnh lõi
def repair_core_fragments(base, config=AdaptiveConfig()):
    h, w = base["gray"].shape
    sh = max(2, round(h * min(w, base["config"]["analysis_width"]) / w))
    ch = base["analysis"]["char_height"] * h / sh
    curves = np.asarray(base["original_ridges"])
    old_support = np.asarray(base["support"])
    observed, counts, points = body_observations(base, ch, with_points=True)
    single_residual = None
    if len(curves) == 2:
        samples = np.asarray(points[0] + points[1], float)
        if len(samples) >= 6 and np.ptp(samples[:, 0]) > 3 * ch:
            x = (samples[:, 0] - w / 2) / w
            fit = np.polyfit(x, samples[:, 1], 2)
            single_residual = float(
                np.quantile(np.abs(samples[:, 1] - np.polyval(fit, x)), 0.9) / ch
            )
    decisions = []
    admitted = []
    for i in range(len(curves) - 1):
        a, b = (observed[i], observed[i + 1])
        wa, wb = (int(a.sum()), int(b.sum()))
        gap = (curves[i + 1] - curves[i]) / ch
        overlap = int((a & b).sum()) / max(1, min(wa, wb))
        q10 = float(np.quantile(gap, 0.1))
        median = float(np.median(gap))
        fragment = (
            wa > 0
            and wb > 0
            and (q10 < config.fragment_q10_gap_chars)
            and (median < config.fragment_median_gap_chars)
            and (overlap < config.fragment_max_x_overlap)
        )
        smaller, larger = (min(wa, wb) / ch, max(wa, wb) / ch)
        weak = (
            smaller > 0
            and smaller < config.weak_body_width_chars
            and (larger > config.weak_neighbor_ratio * smaller)
            and (q10 < config.weak_q10_gap_chars)
        )
        single = bool(
            config.collapse_single_line
            and len(curves) == 2
            and (q10 < 0.5)
            and (median < 0.85)
            and (single_residual is not None)
            and (single_residual < config.single_line_max_residual_chars)
        )
        merge = bool(config.merge_fragments and (fragment or weak or single))
        decisions.append(
            {
                "upper_original_core_id": i + 1,
                "lower_original_core_id": i + 2,
                "q10_gap_chars": q10,
                "median_gap_chars": median,
                "body_x_overlap_min": overlap,
                "body_width_chars": [wa / ch, wb / ch],
                "body_components": [int(counts[i]), int(counts[i + 1])],
                "fragment_test": bool(fragment),
                "weak_core_test": bool(weak),
                "single_line_residual_chars": single_residual,
                "single_line_test": single,
                "merge": merge,
            }
        )
        if merge:
            admitted.append(i)
    merged = []
    for i in range(len(curves)):
        if merged and i - 1 in admitted:
            merged[-1].append(i)
        else:
            merged.append([i])
    new_curves = []
    new_support = []
    for group in merged:
        if len(group) == 1:
            curve = curves[group[0]].copy()
        else:
            weights = np.asarray(
                [gaussian_filter1d(observed[i].astype(float), max(1.0, 0.5 * ch)) for i in group]
            )
            mass = weights.sum(axis=0)
            valid = mass > 1e-05
            if not valid.any():
                raise ValueError("Merged core lacks real body observations")
            value = (weights * curves[group]).sum(axis=0) / np.maximum(mass, 1e-09)
            curve = np.interp(np.arange(w), np.flatnonzero(valid), value[valid])
            curve = gaussian_filter1d(curve, max(1.0, 0.3 * ch))
            curve = np.clip(curve, curves[group[0]], curves[group[-1]])
        support = np.logical_or.reduce(old_support[group])
        actual = np.logical_or.reduce(observed[group])
        if config.restrict_body_support and actual.any():
            size = max(1, 2 * round(config.body_support_padding_chars * ch) + 1)
            support &= maximum_filter1d(actual.astype(np.uint8), size=size) > 0
        new_curves.append(curve)
        new_support.append(support)
    new_curves = np.asarray(new_curves)
    new_support = np.asarray(new_support)
    if len(new_curves) > 1 and np.any(np.diff(new_curves, axis=0) <= 0):
        raise ValueError("Repaired core tracks cross")
    settings = SupportConfig(**base["config"])
    labels, ink, cc_decisions = assign_supported_owners(
        base["gray"], new_curves, new_support, ch, settings
    )
    result = {
        **base,
        "labels": labels,
        "original_mask": ink,
        "original_ridges": new_curves,
        "support": new_support,
        "component_decisions": cc_decisions,
        "crops": crops_from_owners(base["gray"], labels, settings.padding),
        "core_merge_decisions": decisions,
        "original_core_groups": [[i + 1 for i in g] for g in merged],
        "body_observation_columns": observed,
        "body_component_counts": counts,
        "metrics": {**base["metrics"], "merged_core_pairs": len(admitted)},
        "warnings": [*base.get("warnings", [])],
    }
    result = refine_split_components(result, config.split, char_height=ch)
    result["metrics"]["n_lines"] = len(result["crops"])
    return result


# Năng lượng seam và truy hồi
@dataclass(frozen=True)
class SeamConfig:
    analysis_width: int = 1536
    seed_prominence: float = 0.12
    seed_distance_chars: float = 0.9
    local_weight: float = 0.4
    ink_weight: float = 90.0
    halo_weight: float = 5.0
    density_weight: float = 2.0
    guide_weight: float = 1.5
    step_weight: float = 0.1
    max_step: int = 2
    corridor_fraction: float = 0.38
    guide_mode: str = "ordered_strip"

    def __post_init__(self):
        if not 0 < self.corridor_fraction < 0.5:
            raise ValueError("corridor_fraction must be in (0, .5) to keep search bands disjoint.")
        if not 0 <= self.local_weight <= 1:
            raise ValueError("local_weight must be in [0, 1].")
        if not 1 <= self.max_step <= 32:
            raise ValueError("max_step must be between 1 and 32.")
        if self.guide_mode not in ("ordered_strip", "density_ridge", "fixed_seed"):
            raise ValueError("Unknown guide mode.")


def assign_regions(shape, seams):
    h, w = shape
    seams = np.asarray(seams, dtype=int).reshape(-1, w)
    if seams.size and (seams.min() < 1 or seams.max() >= h):
        raise ValueError("Every internal seam must stay strictly inside the image.")
    if len(seams) > 1 and np.any(np.diff(seams, axis=0) <= 0):
        raise ValueError("Seams intersect or lose their top-to-bottom order.")
    labels = np.ones(shape, np.uint16)
    yy = np.arange(h)[:, None]
    for seam in seams:
        labels += yy >= seam[None, :]
    return labels


def diagnose(mask, seams, labels):
    return ({"n_lines": len(seams) + 1, "diagnostics_measured": False}, [], [])


def extract_crops(gray, seams, labels):
    h, w = gray.shape
    bounds = [np.zeros(w, int), *seams, np.full(w, h, int)]
    crops = []
    for i, (top, bottom) in enumerate(zip(bounds[:-1], bounds[1:]), 1):
        y0, y1 = (int(top.min()), int(bottom.max()))
        image = np.where(labels[y0:y1] == i, gray[y0:y1], 255).astype(np.uint8)
        crops.append(dict(image=image, x0=0, y0=y0, line_id=i))
    return crops


def shortest_path(cost, lower, upper, max_step=2, step_weight=0.1):
    h, w = cost.shape
    lo = np.clip(np.ceil(lower).astype(int), 0, h - 1)
    hi = np.clip(np.floor(upper).astype(int), 0, h - 1)
    if np.any(lo > hi):
        raise ValueError("Empty seam corridor; inspect line seeds.")
    y0, y1 = (int(lo.min()), int(hi.max()) + 1)
    yy = np.arange(y0, y1)
    local = cost[y0:y1].astype(np.float64).copy()
    local[(yy[:, None] < lo) | (yy[:, None] > hi)] = np.inf
    nh = len(yy)
    back = np.zeros((nh, w), dtype=np.int8)
    prev = local[:, 0]
    steps = np.arange(-max_step, max_step + 1)
    for x in range(1, w):
        candidates = np.full((len(steps), nh), np.inf)
        for k, delta in enumerate(steps):
            dest = np.arange(max(0, -delta), min(nh, nh - delta))
            candidates[k, dest] = prev[dest + delta] + step_weight * abs(delta)
        choice = candidates.argmin(axis=0)
        prev = local[:, x] + candidates[choice, np.arange(nh)]
        back[:, x] = steps[choice]
    if not np.isfinite(prev).any():
        raise ValueError("No continuous path in corridor; inspect constraints.")
    path = np.empty(w, dtype=np.int32)
    row = int(prev.argmin())
    path[-1] = row + y0
    for x in range(w - 1, 0, -1):
        row += int(back[row, x])
        path[x - 1] = row + y0
    return path


# Projection và ghép peak theo strip
def line_guides(density, centers, char_h):
    h, w = density.shape
    edges = np.r_[0, (centers[:-1] + centers[1:]) / 2, h - 1]
    yy = np.arange(h)[:, None]
    norm = density / max(float(np.percentile(density, 99)), 1e-06)
    ridges = []
    for i, center in enumerate(centers):
        radius = max(char_h, min(center - edges[i], edges[i + 1] - center))
        cost = -norm + 0.3 * ((yy - center) / radius) ** 2
        lo, hi = (np.full(w, edges[i] + 1), np.full(w, edges[i + 1] - 1))
        path = shortest_path(cost, lo, hi, max_step=1, step_weight=0.08)
        path = gaussian_filter1d(path.astype(float), max(2.0, w / 100.0))
        ridges.append(np.clip(path, lo, hi))
    return np.asarray(ridges)


def match_ordered_peaks(previous, candidates):
    n, m = (len(previous), len(candidates))
    gaps = np.diff(previous)
    pitch = np.r_[gaps[:1], gaps] if len(gaps) else np.array([40.0])
    pitch = np.maximum(pitch, 12.0)
    dp = np.full((n + 1, m + 1), np.inf)
    action = np.zeros((n + 1, m + 1), np.int8)
    dp[0, 0] = 0.0
    dp[1:, 0] = np.arange(1, n + 1) * 1.3
    dp[0, 1:] = np.arange(1, m + 1) * 0.9
    action[1:, 0] = 1
    action[0, 1:] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            delta = abs(float(candidates[j - 1]) - previous[i - 1]) / pitch[i - 1]
            match = dp[i - 1, j - 1] + (delta / 0.45) ** 2 if delta <= 0.7 else np.inf
            values = [match, dp[i - 1, j] + 1.3, dp[i, j - 1] + 0.9]
            action[i, j] = int(np.argmin(values))
            dp[i, j] = min(values)
    matched = np.full(n, np.nan)
    i, j = (n, m)
    while i or j:
        choice = action[i, j]
        if choice == 0:
            matched[i - 1] = candidates[j - 1]
            i, j = (i - 1, j - 1)
        elif choice == 1:
            i -= 1
        else:
            j -= 1
    return matched


def ordered_strip_guides(seed, width, cfg):
    centers = seed["centers"]
    profiles = seed["strip_profiles"]
    peaks, prominences = ([], [])
    for profile in profiles:
        p, props = find_peaks(
            profile,
            distance=max(15.0, cfg.seed_distance_chars * seed["char_height"]),
            prominence=cfg.seed_prominence,
        )
        peaks.append(p)
        prominences.append(props["prominences"])
    full = [j for j, p in enumerate(peaks) if len(p) == len(centers)]
    anchor = max(full, key=lambda j: prominences[j].sum()) if full else len(peaks) // 2
    tracks = np.full((len(centers), len(peaks)), np.nan)
    tracks[:, anchor] = peaks[anchor] if full else match_ordered_peaks(centers, peaks[anchor])
    for direction in (-1, 1):
        previous = np.where(np.isfinite(tracks[:, anchor]), tracks[:, anchor], centers).astype(
            float
        )
        for j in range(anchor + direction, len(peaks) if direction > 0 else -1, direction):
            matched = match_ordered_peaks(previous, peaks[j])
            tracks[:, j] = matched
            previous = np.where(np.isfinite(matched), matched, previous)
    xnodes = seed["strip_x"] + (seed["strip_width"] - 1) / 2
    xx = np.arange(width)
    ridges = []
    for i, row in enumerate(tracks):
        observed = np.isfinite(row)
        ridge = (
            np.interp(xx, xnodes[observed], row[observed])
            if observed.any()
            else np.full(width, centers[i])
        )
        ridges.append(gaussian_filter1d(ridge.astype(float), max(2.0, width / 200)))
    ridges = np.asarray(ridges)
    if len(ridges) > 1 and np.any(np.diff(ridges, axis=0) <= 2):
        raise ValueError("Strip line tracks lost order; requires review rather than silent repair.")
    return (
        ridges,
        dict(
            strip_match_positions=tracks,
            strip_peak_positions=peaks,
            strip_peak_prominences=prominences,
            anchor_strip=anchor,
        ),
    )


def read_gray(image):
    if isinstance(image, np.ndarray):
        if image.dtype != np.uint8 or image.ndim != 2:
            raise ValueError("Cần luminance uint8 hai chiều.")
        return image.copy()
    if isinstance(image, Image.Image):
        return np.asarray(image.convert("L")).copy()
    with Image.open(image) as opened:
        return np.asarray(opened.convert("L")).copy()


def seed_lines(mask, cfg):
    h, w = mask.shape
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    st = stats[1:]
    usable = st[(st[:, 4] > 16) & (st[:, 3] > 7) & (st[:, 2] > 2)]
    char_h = float(np.percentile(usable[:, 3], 70)) if len(usable) else max(12.0, h / 12.0)
    sigma = max(2.0, 0.13 * char_h)
    global_profile = gaussian_filter1d(mask.mean(axis=1).astype(float), sigma)
    global_norm = global_profile / max(float(global_profile.max()), 1e-08)
    strip_w = max(32, round(w * 0.195))
    xs = np.linspace(0, w - strip_w, 9).astype(int)
    strip_profiles = []
    for x in xs:
        p = gaussian_filter1d(mask[:, x : x + strip_w].mean(axis=1).astype(float), sigma)
        strip_profiles.append(p / max(float(p.max()), 1e-08))
    strip_profiles = np.asarray(strip_profiles)
    local_max = strip_profiles.max(axis=0)
    score = (1 - cfg.local_weight) * global_norm + cfg.local_weight * local_max
    centers, props = find_peaks(
        score, distance=max(15.0, cfg.seed_distance_chars * char_h), prominence=cfg.seed_prominence
    )
    global_centers, _ = find_peaks(
        global_norm,
        distance=max(15.0, cfg.seed_distance_chars * char_h),
        prominence=cfg.seed_prominence,
    )
    if not len(centers):
        raise ValueError("No text-line seed detected. Do not silently output one line.")
    density = cv2.GaussianBlur(
        mask.astype(np.float32),
        (0, 0),
        sigmaX=max(3.0, 1.1 * char_h),
        sigmaY=max(2.0, 0.18 * char_h),
    )
    return dict(
        centers=centers,
        seed_prominences=props["prominences"],
        global_centers=global_centers,
        char_height=char_h,
        global_profile=global_profile,
        global_norm=global_norm,
        strip_profiles=strip_profiles,
        strip_x=xs,
        strip_width=strip_w,
        seed_score=score,
        density=density,
    )


# DIP trên lưới nguồn
def unsupported_ink_flags(mask, labels, tracks, strip_x, strip_width, scale_x):
    return []


def upsample_curve(curve, target_w, scale_y):
    target_x = (np.arange(target_w) + 0.5) * len(curve) / target_w - 0.5
    return (np.interp(target_x, np.arange(len(curve)), curve) + 0.5) / scale_y - 0.5


def segment_dip_seams(path, cfg=SeamConfig()):
    start = time.perf_counter()
    gray = read_gray(path)
    h, w = gray.shape
    sw = min(w, cfg.analysis_width)
    sh = round(h * sw / w)
    work_gray = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA)
    scale_x, scale_y = (sw / w, sh / h)
    mask, threshold = binarize(work_gray)
    original_mask, original_threshold = binarize(gray)
    seed = seed_lines(mask, cfg)
    centers, char_h = (seed["centers"], seed["char_height"])
    guide_info = {}
    if cfg.guide_mode == "ordered_strip":
        ridges, guide_info = ordered_strip_guides(seed, sw, cfg)
    elif cfg.guide_mode == "density_ridge":
        ridges = line_guides(seed["density"], centers, char_h)
    else:
        ridges = np.repeat(centers[:, None].astype(float), sw, axis=1)
    guides = (ridges[:-1] + ridges[1:]) / 2
    original_ridges = np.asarray([upsample_curve(r, w, scale_y) for r in ridges])
    yy = np.arange(h)[:, None]
    contact = original_mask | np.vstack([original_mask[:1], original_mask[:-1]])
    distance = cv2.distanceTransform((~original_mask).astype(np.uint8), cv2.DIST_L2, 5)
    halo = np.exp(-distance / max(1.0, 0.055 * char_h / scale_y))
    halo = np.maximum(halo, np.vstack([halo[:1], halo[:-1]]))
    density_orig = cv2.resize(seed["density"], (w, h))
    density_orig /= max(float(np.percentile(density_orig, 99)), 1e-06)
    base_energy = (
        cfg.ink_weight * contact + cfg.halo_weight * halo + cfg.density_weight * density_orig
    )
    seams, corridor_lows, corridor_highs = ([], [], [])
    for i in range(len(centers) - 1):
        guide = (original_ridges[i] + original_ridges[i + 1]) / 2
        gap = np.maximum(4.0, original_ridges[i + 1] - original_ridges[i])
        radius = cfg.corridor_fraction * gap
        lo = np.maximum(1.0, guide - radius)
        hi = np.minimum(h - 1.0, guide + radius)
        prior = cfg.guide_weight * ((yy - guide) / np.maximum(1.0, radius)) ** 2
        s = shortest_path(base_energy + prior, lo, hi, cfg.max_step, cfg.step_weight)
        seams.append(s)
        corridor_lows.append(lo)
        corridor_highs.append(hi)
    seams = np.asarray(seams, dtype=np.int32).reshape(-1, w)
    labels = assign_regions(gray.shape, seams)
    metrics, cuts, uncertain = diagnose(original_mask, seams, labels)
    unsupported = (
        unsupported_ink_flags(
            original_mask,
            labels,
            guide_info["strip_match_positions"],
            seed["strip_x"],
            seed["strip_width"],
            scale_x,
        )
        if "strip_match_positions" in guide_info
        else []
    )
    metrics["unsupported_ink_components"] = (
        len(unsupported) if "strip_match_positions" in guide_info else None
    )
    crops = extract_crops(gray, seams, labels)
    metrics["source_pixels_reconstructed_exactly"] = None
    metrics["runtime_seconds"] = time.perf_counter() - start
    metrics["global_hpp_seed_count"] = len(seed["global_centers"])
    return dict(
        path=str(path) if isinstance(path, (str, Path)) else None,
        gray=gray,
        work_gray=work_gray,
        mask=mask,
        original_mask=original_mask,
        energy=cv2.resize(base_energy.astype(np.float32), (sw, sh)),
        **seed,
        **guide_info,
        ridges=ridges,
        guides=guides,
        original_ridges=original_ridges,
        seams=seams,
        corridor_lows=np.asarray(corridor_lows),
        corridor_highs=np.asarray(corridor_highs),
        labels=labels,
        crops=crops,
        metrics=metrics,
        cut_stats=cuts,
        uncertain_marks=uncertain,
        unsupported_ink=unsupported,
        scale=scale_x,
        scale_y=scale_y,
        threshold=threshold,
        original_threshold=original_threshold,
        config=asdict(cfg),
    )


# Cấu hình sửa nét nối
@dataclass(frozen=True)
class BodyConfig:
    sigma_chars: float = 0.24
    min_height_chars: float = 0.4
    min_area_chars2: float = 0.06
    max_height_chars: float = 2.0
    min_body_mass_fraction: float = 0.12
    min_winner_fraction: float = 0.72
    min_absolute_margin: float = 0.12
    use_strip_support: bool = True
    expand_corridor: bool = True
    max_step: int = 2
    step_weight: float = 0.1


# Cấu hình liên kết thành phần
@dataclass(frozen=True)
class AssociationConfig:
    child_max_height_chars: float = 0.7
    child_max_width_chars: float = 1.05
    child_max_area_chars2: float = 0.2
    body_min_height_chars: float = 0.55
    body_min_area_chars2: float = 0.1
    parent_min_owner_fraction: float = 0.98
    max_horizontal_gap_chars: float = 0.45
    max_vertical_gap_chars: float = 0.65
    max_score_chars: float = 0.8
    min_line_margin_chars: float = 0.2
    association_weight: float = 45.0
    central_body_min_height_chars: float = 0.3
    central_body_min_area_chars2: float = 0.045
    central_body_centroid_distance_chars: float = 0.3
    uncertainty_mode: str = "margin"

    def __post_init__(self):
        if self.uncertainty_mode not in ("margin", "support_only"):
            raise ValueError("Unknown association uncertainty gate.")


# Biên khả thi và đề xuất thân
def lipschitz_lower(a, step):
    a = a.copy()
    for x in range(1, a.shape[-1]):
        a[..., x] = np.maximum(a[..., x], a[..., x - 1] - step)
    for x in range(a.shape[-1] - 2, -1, -1):
        a[..., x] = np.maximum(a[..., x], a[..., x + 1] - step)
    return a


def lipschitz_upper(a, step):
    return -lipschitz_lower(-a, step)


def feasible_bounds(r, desired, cfg):
    h, w = desired.shape
    n = len(r["seams"])
    mask = r["original_mask"]
    low = np.ones((n, w), np.int32)
    high = np.full((n, w), h - 1, np.int32)
    yy, xx = np.nonzero(mask)
    owner = desired[yy, xx]
    for b in range(n):
        upper = owner <= b + 1
        lower = ~upper
        np.maximum.at(low[b], xx[upper], yy[upper] + 1)
        np.minimum.at(high[b], xx[lower], yy[lower])
    if not cfg.expand_corridor:
        low = np.maximum(low, np.ceil(r["corridor_lows"]).astype("int32"))
        high = np.minimum(high, np.floor(r["corridor_highs"]).astype("int32"))
    low = lipschitz_lower(low, cfg.max_step)
    high = lipschitz_upper(high, cfg.max_step)
    for b in range(1, n):
        low[b] = np.maximum(low[b], low[b - 1] + 1)
    for b in range(n - 2, -1, -1):
        high[b] = np.minimum(high[b], high[b + 1] - 1)
    bad = low > high
    return (not np.any(bad), low, high, int(np.count_nonzero(bad)))


def strip_support(r):
    support = np.zeros((len(r["ridges"]), r["gray"].shape[1]), bool)
    for line, row in enumerate(r["strip_match_positions"]):
        for j in np.flatnonzero(np.isfinite(row)):
            a = max(0, int(np.floor(r["strip_x"][j] / r["scale"])))
            b = min(
                support.shape[1], int(np.ceil((r["strip_x"][j] + r["strip_width"]) / r["scale"]))
            )
            support[line, a:b] = True
    return support


def propose_bodies(r, cfg):
    mask = r["original_mask"]
    n, cc, st, ct = cv2.connectedComponentsWithStats(mask.astype("uint8"), connectivity=8)
    ch = r["char_height"] / r["scale_y"]
    support = strip_support(r)
    records = []
    for k in range(1, n):
        x, y, w, h, area = st[k]
        yy, xx = np.nonzero(cc[y : y + h, x : x + w] == k)
        yy += y
        xx += x
        old = r["labels"][yy, xx]
        owners, counts = np.unique(old, return_counts=True)
        if len(owners) < 2:
            continue
        dist = (yy[None, :] - r["original_ridges"][:, xx]) / ch
        raw = np.exp(-0.5 * (dist / cfg.sigma_chars) ** 2)
        gated = raw * support[:, xx] if cfg.use_strip_support else raw
        votes = gated.sum(axis=1)
        rank = np.argsort(-votes, kind="stable")
        best = rank[0]
        second = float(votes[rank[1]]) if len(rank) > 1 else 0.0
        share = float(votes[best] / max(votes[best] + second, 1e-09))
        margin = float((votes[best] - second) / area)
        reason = []
        if h < cfg.min_height_chars * ch or area < cfg.min_area_chars2 * ch**2:
            reason.append("too_small_for_body")
        if h > cfg.max_height_chars * ch:
            reason.append("possibly_multi_line_component")
        if votes[best] / area < cfg.min_body_mass_fraction:
            reason.append("weak_body_evidence")
        if share < cfg.min_winner_fraction:
            reason.append("ambiguous_line_votes")
        if margin < cfg.min_absolute_margin:
            reason.append("weak_absolute_margin")
        if best + 1 not in owners:
            reason.append("proposed_line_outside_existing_split")
        records.append(
            dict(
                component_id=k,
                x=int(x),
                y=int(y),
                width=int(w),
                height=int(h),
                area=int(area),
                cx=float(ct[k, 0]),
                cy=float(ct[k, 1]),
                previous_lines=owners.tolist(),
                previous_counts=counts.tolist(),
                raw_votes=raw.sum(axis=1).tolist(),
                gated_votes=votes.tolist(),
                support_fraction=support[:, xx].mean(axis=1).tolist(),
                proposed_line=int(best + 1),
                winner_fraction=share,
                absolute_margin=margin,
                body_mass_fraction=float(votes[best] / area),
                eligible=not reason,
                reason=reason,
                accepted=False,
            )
        )
    return (records, cc, st, support)


# Sửa nét nối có ràng buộc
def repair_connected_strokes(baseline, cfg=BodyConfig()):
    start = time.perf_counter()
    r = dict(baseline)
    proposals, cc, stats, support = propose_bodies(r, cfg)
    desired = r["labels"].copy()
    ok, low, high, _ = feasible_bounds(r, desired, cfg)
    if not ok:
        raise ValueError(
            "Frozen baseline violates requested continuity/corridor; no silent fallback"
        )
    ordered = sorted(
        (q for q in proposals if q["eligible"]),
        key=lambda q: (-q["absolute_margin"], -q["winner_fraction"], q["component_id"]),
    )
    for q in ordered:
        x, y, w, h = (q["x"], q["y"], q["width"], q["height"])
        own = cc[y : y + h, x : x + w] == q["component_id"]
        old = desired[y : y + h, x : x + w][own].copy()
        desired[y : y + h, x : x + w][own] = q["proposed_line"]
        ok, ll, hh, bad = feasible_bounds(r, desired, cfg)
        q["infeasible_bound_columns"] = bad
        if ok:
            q["accepted"] = True
            low, high = (ll, hh)
        else:
            desired[y : y + h, x : x + w][own] = old
            q["reason"].append("no_continuous_ordered_path_with_pixel_guards")
    gray, mask = (r["gray"], r["original_mask"])
    h, w = gray.shape
    ch = r["char_height"] / r["scale_y"]
    contact = mask | np.vstack([mask[:1], mask[:-1]])
    distance = cv2.distanceTransform((~mask).astype("uint8"), cv2.DIST_L2, 5)
    halo = np.exp(-distance / max(1.0, 0.055 * ch))
    halo = np.maximum(halo, np.vstack([halo[:1], halo[:-1]]))
    density = cv2.resize(r["density"], (w, h))
    density /= max(float(np.percentile(density, 99)), 1e-06)
    base = (
        r["config"]["ink_weight"] * contact
        + r["config"]["halo_weight"] * halo
        + r["config"]["density_weight"] * density
    )
    yy = np.arange(h)[:, None]
    seams = []
    energy_slices = []
    for b in range(len(r["seams"])):
        guide = (r["original_ridges"][b] + r["original_ridges"][b + 1]) / 2
        radius = r["config"]["corridor_fraction"] * np.maximum(
            4.0, r["original_ridges"][b + 1] - r["original_ridges"][b]
        )
        cost = base + r["config"]["guide_weight"] * ((yy - guide) / np.maximum(1.0, radius)) ** 2
        if "mark_decisions" in r:
            for d in r["mark_decisions"]:
                if not d["accepted"]:
                    continue
                x, y, cw, chh = (int(d[k]) for k in ("x", "y", "width", "height"))
                if int(d["proposed_line"]) == b + 1:
                    cost[: y + chh, x : x + cw] += 45.0
                elif int(d["proposed_line"]) == b + 2:
                    cost[y + 1 :, x : x + cw] += 45.0
        lo = low[b].copy()
        if seams:
            lo = np.maximum(lo, seams[-1] + 1)
        s = shortest_path(cost, lo, high[b], cfg.max_step, cfg.step_weight)
        seams.append(s)
        a = max(0, int(lo.min()) - 3)
        z = min(h, int(high[b].max()) + 4)
        energy_slices.append(dict(boundary=b + 1, y0=a, cost=cost[a:z].astype("float32")))
    seams = np.asarray(seams, np.int32).reshape(-1, w)
    labels = assign_regions(gray.shape, seams)
    if not np.array_equal(labels[mask], desired[mask]):
        raise AssertionError("Hard ownership guards violated")
    metrics, cuts, uncertain = diagnose(mask, seams, labels)
    crops = extract_crops(gray, seams, labels)
    accepted_ids = [q["component_id"] for q in proposals if q["accepted"]]
    accepted_mask = np.isin(cc, accepted_ids) & mask
    changed_mask = mask & (labels != baseline["labels"])
    outside_changed = int(np.count_nonzero(changed_mask & ~accepted_mask))
    if outside_changed:
        raise AssertionError("Changed foreground outside admitted components")
    metrics.update(
        source_pixels_reconstructed_exactly=None,
        accepted_body_proposals=sum((q["accepted"] for q in proposals)),
        eligible_body_proposals=sum((q["eligible"] for q in proposals)),
        changed_foreground_pixels=int(np.count_nonzero(changed_mask)),
        foreground_outside_accepted_bodies_changed=outside_changed,
        runtime_seconds_body_stage=time.perf_counter() - start,
        max_observed_step=int(max((np.abs(np.diff(s)).max() for s in seams), default=0)),
    )
    for q in proposals:
        x, y, w, h = (q["x"], q["y"], q["width"], q["height"])
        own = cc[y : y + h, x : x + w] == q["component_id"]
        q["final_lines"] = np.unique(labels[y : y + h, x : x + w][own]).tolist()
        q["final_all_proposed_line"] = q["final_lines"] == [q["proposed_line"]]
    r.update(
        seams=seams,
        labels=labels,
        crops=crops,
        metrics=metrics,
        cut_stats=cuts,
        uncertain_marks=uncertain,
        body_proposals=proposals,
        body_config=asdict(cfg),
        strip_support=support,
        adaptive_lows=low,
        adaptive_highs=high,
        desired_foreground_owners=desired,
        energy_slices=energy_slices,
    )
    return r


# Liên kết thành phần nhỏ
def component_associations(result, cfg=AssociationConfig()):
    mask, labels = (result["original_mask"], result["labels"])
    n, cc, stats, centers = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    char_h = result["char_height"] / result["scale_y"]
    area = stats[:, cv2.CC_STAT_AREA]
    heights, widths = (stats[:, cv2.CC_STAT_HEIGHT], stats[:, cv2.CC_STAT_WIDTH])
    compact = (
        (heights <= cfg.child_max_height_chars * char_h)
        & (widths <= cfg.child_max_width_chars * char_h)
        & (area >= 3)
        & (area <= cfg.child_max_area_chars2 * char_h**2)
    )
    compact[0] = False
    body = (
        (heights >= cfg.body_min_height_chars * char_h)
        & (area >= cfg.body_min_area_chars2 * char_h**2)
        & ~compact
    )
    body[0] = False
    owners = np.zeros(n, int)
    confidence = np.zeros(n, float)
    for k in range(1, n):
        x, y, w, h, _ = stats[k]
        own = labels[y : y + h, x : x + w][cc[y : y + h, x : x + w] == k]
        counts = np.bincount(own, minlength=len(result["ridges"]) + 1)
        owners[k] = counts.argmax()
        confidence[k] = counts[owners[k]] / len(own)
    x_centers = np.clip(np.rint(centers[:, 0]).astype(int), 0, mask.shape[1] - 1)
    support = np.zeros((len(result["ridges"]), mask.shape[1]), bool)
    for line, row in enumerate(result["strip_match_positions"]):
        for j in np.flatnonzero(np.isfinite(row)):
            a = max(0, int(np.floor(result["strip_x"][j] / result["scale"])))
            b = min(
                mask.shape[1],
                int(np.ceil((result["strip_x"][j] + result["strip_width"]) / result["scale"])),
            )
            support[line, a:b] = True
    has_support = support[np.maximum(0, owners - 1), x_centers]
    ridge = result["original_ridges"][np.maximum(0, owners - 1), x_centers]
    central_body = (
        (heights >= cfg.central_body_min_height_chars * char_h)
        & (area >= cfg.central_body_min_area_chars2 * char_h**2)
        & (np.abs(centers[:, 1] - ridge) <= cfg.central_body_centroid_distance_chars * char_h)
    )
    central_body[0] = False
    body = (body | central_body) & (confidence >= cfg.parent_min_owner_fraction)
    if cfg.uncertainty_mode == "support_only":
        body &= has_support
    compact &= ~body
    bodies = np.flatnonzero(body)
    decisions = []
    for child in np.flatnonzero(compact):
        x, y, w, h, ar = stats[child]
        cx, cy = centers[child]
        candidates = []
        for parent in bodies:
            if parent == child:
                continue
            px, py, pw, ph, pa = stats[parent]
            gx = max(0, x - (px + pw - 1), px - (x + w - 1))
            gy = max(0, y - (py + ph - 1), py - (y + h - 1))
            if (
                gx > cfg.max_horizontal_gap_chars * char_h
                or gy > cfg.max_vertical_gap_chars * char_h
            ):
                continue
            score = (np.hypot(gx, gy) + 0.6 * gx + 0.15 * abs(cx - centers[parent, 0])) / char_h
            candidates.append((float(score), int(parent), int(owners[parent])))
        candidates.sort()
        if not candidates:
            continue
        best = candidates[0]
        other = next((c for c in candidates if c[2] != best[2]), None)
        margin = other[0] - best[0] if other else float("inf")
        accepted = best[0] <= cfg.max_score_chars and margin >= cfg.min_line_margin_chars
        current_support = bool(has_support[child])
        target_support = bool(support[best[2] - 1, x_centers[child]])
        if cfg.uncertainty_mode == "support_only":
            accepted = (
                accepted and best[2] != owners[child] and (not current_support) and target_support
            )
        decisions.append(
            dict(
                component_id=int(child),
                x=int(x),
                y=int(y),
                width=int(w),
                height=int(h),
                area=int(ar),
                cx=float(cx),
                cy=float(cy),
                previous_line=int(owners[child]),
                parent_id=best[1],
                proposed_line=best[2],
                parent_cx=float(centers[best[1], 0]),
                parent_cy=float(centers[best[1], 1]),
                best_score_chars=best[0],
                second_line_score_chars=other[0] if other else None,
                line_margin_chars=float(margin) if np.isfinite(margin) else None,
                accepted=bool(accepted),
                changed_hypothesis=bool(accepted and best[2] != owners[child]),
                current_line_has_strip_support=current_support,
                proposed_line_has_strip_support=target_support,
                candidate_count=len(candidates),
            )
        )
    return (decisions, cc, stats)


# DIP với liên kết thành phần
def segment_component_aware(
    path, seam_cfg=None, association_cfg=AssociationConfig(), baseline=None
):
    start = time.perf_counter()
    seam_cfg = seam_cfg or SeamConfig(corridor_fraction=0.48, guide_mode="ordered_strip")
    baseline = baseline or segment_dip_seams(path, seam_cfg)
    r = dict(baseline)
    decisions, cc, stats = component_associations(baseline, association_cfg)
    accepted = [d for d in decisions if d["accepted"]]
    gray, mask = (r["gray"], r["original_mask"])
    h, w = gray.shape
    char_h = r["char_height"] / r["scale_y"]
    contact = mask | np.vstack([mask[:1], mask[:-1]])
    distance = cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)
    halo = np.exp(-distance / max(1.0, 0.055 * char_h))
    halo = np.maximum(halo, np.vstack([halo[:1], halo[:-1]]))
    density = cv2.resize(r["density"], (w, h))
    density /= max(float(np.percentile(density, 99)), 1e-06)
    base = (
        seam_cfg.ink_weight * contact
        + seam_cfg.halo_weight * halo
        + seam_cfg.density_weight * density
    )
    yy = np.arange(h)[:, None]
    seams, violations, relevant_counts = ([], [], [])
    for boundary in range(len(r["ridges"]) - 1):
        guide = (r["original_ridges"][boundary] + r["original_ridges"][boundary + 1]) / 2
        radius = seam_cfg.corridor_fraction * np.maximum(
            4.0, r["original_ridges"][boundary + 1] - r["original_ridges"][boundary]
        )
        cost = base + seam_cfg.guide_weight * ((yy - guide) / np.maximum(1.0, radius)) ** 2
        semantic = np.zeros((h, w), np.float32)
        relevant = []
        for d in accepted:
            if d["proposed_line"] not in (boundary + 1, boundary + 2):
                continue
            x, y, cw, ch = (d["x"], d["y"], d["width"], d["height"])
            if d["proposed_line"] == boundary + 1:
                semantic[: y + ch, x : x + cw] += association_cfg.association_weight
            else:
                semantic[y + 1 :, x : x + cw] += association_cfg.association_weight
            relevant.append(d)
        s = shortest_path(
            cost + semantic,
            r["corridor_lows"][boundary],
            r["corridor_highs"][boundary],
            seam_cfg.max_step,
            seam_cfg.step_weight,
        )
        seams.append(s)
        violations.append(float(semantic[s, np.arange(w)].sum()))
        relevant_counts.append(len(relevant))
    seams = np.asarray(seams, np.int32).reshape(-1, w)
    labels = assign_regions(gray.shape, seams)
    metrics, cuts, uncertain = diagnose(mask, seams, labels)
    unsupported = unsupported_ink_flags(
        mask, labels, r["strip_match_positions"], r["strip_x"], r["strip_width"], r["scale"]
    )
    metrics["unsupported_ink_components"] = len(unsupported)
    crops = extract_crops(gray, seams, labels)
    metrics["source_pixels_reconstructed_exactly"] = None
    metrics["runtime_seconds_component_stage"] = time.perf_counter() - start
    metrics["accepted_associations"] = len(accepted)
    metrics["accepted_changed_hypotheses"] = sum((d["changed_hypothesis"] for d in accepted))
    changed = []
    for d in decisions:
        x, y, cw, ch = (d["x"], d["y"], d["width"], d["height"])
        pix = cc[y : y + ch, x : x + cw] == d["component_id"]
        final = labels[y : y + ch, x : x + cw][pix]
        d["final_majority_line"] = int(np.bincount(final).argmax())
        d["final_split"] = bool(len(np.unique(final)) > 1)
        d["final_agrees_with_hypothesis"] = bool(np.all(final == d["proposed_line"]))
        if d["final_majority_line"] != d["previous_line"] or d["final_split"]:
            changed.append(d)
    metrics["changed_compact_components"] = len(changed)
    metrics["accepted_association_violations"] = sum(
        (not d["final_agrees_with_hypothesis"] for d in accepted)
    )
    r.update(
        seams=seams,
        labels=labels,
        crops=crops,
        metrics=metrics,
        cut_stats=cuts,
        uncertain_marks=uncertain,
        unsupported_ink=unsupported,
        association_decisions=decisions,
        changed_components=changed,
        association_config=asdict(association_cfg),
        semantic_penalty_by_boundary=violations,
        semantic_associations_by_boundary=relevant_counts,
    )
    return r


# Gán thành phần sau sửa thân
def post_supported_marks(body_result, association_cfg=None):
    start = time.perf_counter()
    r = dict(body_result)
    acfg = association_cfg or AssociationConfig(uncertainty_mode="support_only")
    cfg = BodyConfig()
    decisions, cc, stats = component_associations(r, acfg)
    desired = r["labels"].copy()
    admitted = []
    for d in sorted(
        (q for q in decisions if q["accepted"]),
        key=lambda q: (q["best_score_chars"], q["component_id"]),
    ):
        x, y, w, h = (d[k] for k in ("x", "y", "width", "height"))
        own = cc[y : y + h, x : x + w] == d["component_id"]
        old = desired[y : y + h, x : x + w][own].copy()
        desired[y : y + h, x : x + w][own] = d["proposed_line"]
        ok, lo, hi, bad = feasible_bounds(r, desired, cfg)
        d["geometrically_admitted"] = bool(ok)
        d["infeasible_bound_columns"] = bad
        if ok:
            admitted.append(d)
        else:
            desired[y : y + h, x : x + w][own] = old
    ok, lo, hi, bad = feasible_bounds(r, desired, cfg)
    if not ok:
        raise AssertionError("Post-mark foreground targets infeasible")
    gray, mask = (r["gray"], r["original_mask"])
    h, w = gray.shape
    ch = r["char_height"] / r["scale_y"]
    contact = mask | np.vstack([mask[:1], mask[:-1]])
    distance = cv2.distanceTransform((~mask).astype("uint8"), cv2.DIST_L2, 5)
    halo = np.exp(-distance / max(1.0, 0.055 * ch))
    halo = np.maximum(halo, np.vstack([halo[:1], halo[:-1]]))
    density = cv2.resize(r["density"], (w, h))
    density /= max(float(np.percentile(density, 99)), 1e-06)
    base = 90 * contact + 5 * halo + 2 * density
    yy = np.arange(h)[:, None]
    seams = []
    energies = []
    for b in range(len(r["seams"])):
        guide = (r["original_ridges"][b] + r["original_ridges"][b + 1]) / 2
        radius = 0.48 * np.maximum(4.0, r["original_ridges"][b + 1] - r["original_ridges"][b])
        cost = base + 1.5 * ((yy - guide) / np.maximum(1.0, radius)) ** 2
        for d in [*r.get("mark_decisions", []), *admitted]:
            if not d["accepted"]:
                continue
            x, y, cw, chh = (int(d[k]) for k in ("x", "y", "width", "height"))
            if int(d["proposed_line"]) == b + 1:
                cost[: y + chh, x : x + cw] += 45.0
            elif int(d["proposed_line"]) == b + 2:
                cost[y + 1 :, x : x + cw] += 45.0
        lower = lo[b].copy()
        if seams:
            lower = np.maximum(lower, seams[-1] + 1)
        s = shortest_path(cost, lower, hi[b], 2, 0.1)
        seams.append(s)
        a = max(0, int(lower.min()) - 3)
        z = min(h, int(hi[b].max()) + 4)
        energies.append(dict(boundary=b + 1, y0=a, cost=cost[a:z].astype("float32")))
    seams = np.asarray(seams, np.int32).reshape(-1, w)
    labels = assign_regions(gray.shape, seams)
    if not np.array_equal(labels[mask], desired[mask]):
        raise AssertionError("Post-mark guards violated")
    metrics, cuts, uncertain = diagnose(mask, seams, labels)
    crops = extract_crops(gray, seams, labels)
    changed = mask & (labels != body_result["labels"])
    selected = np.isin(cc, [d["component_id"] for d in admitted]) & mask
    outside = int(np.count_nonzero(changed & ~selected))
    if outside:
        raise AssertionError("Post-mark change outside admitted components")
    for d in decisions:
        d.setdefault("geometrically_admitted", False)
        x, y, cw, chh = (d[k] for k in ("x", "y", "width", "height"))
        own = cc[y : y + chh, x : x + cw] == d["component_id"]
        d["final_lines"] = np.unique(labels[y : y + chh, x : x + cw][own]).tolist()
    metrics.update(
        source_pixels_reconstructed_exactly=None,
        accepted_body_proposals=body_result["metrics"]["accepted_body_proposals"],
        eligible_body_proposals=body_result["metrics"]["eligible_body_proposals"],
        post_mark_hypotheses=sum((d["accepted"] for d in decisions)),
        accepted_post_marks=len(admitted),
        post_mark_changed_foreground_pixels=int(changed.sum()),
        post_mark_outside_admitted_changed=outside,
        runtime_seconds_post_mark_stage=time.perf_counter() - start,
        max_observed_step=int(max((np.abs(np.diff(s)).max() for s in seams), default=0)),
    )
    r.update(
        seams=seams,
        labels=labels,
        crops=crops,
        metrics=metrics,
        cut_stats=cuts,
        uncertain_marks=uncertain,
        adaptive_lows=lo,
        adaptive_highs=hi,
        energy_slices=energies,
        post_mark_decisions=decisions,
        post_mark_config=asdict(acfg),
    )
    return r


# DIP strict
def segment_quality_paragraph(
    path, *, seam_config=None, association_config=None, body_config=None, post_mark_config=None
):
    started = time.perf_counter()
    raw = segment_dip_seams(
        path, seam_config or SeamConfig(corridor_fraction=0.48, guide_mode="ordered_strip")
    )
    supported = segment_component_aware(
        path,
        seam_cfg=seam_config or SeamConfig(corridor_fraction=0.48, guide_mode="ordered_strip"),
        association_cfg=association_config or AssociationConfig(uncertainty_mode="support_only"),
        baseline=raw,
    )
    supported["mark_decisions"] = supported["association_decisions"]
    supported["baseline_cache"] = "None: computed from raw source image in this call"
    initial = supported["labels"].copy()
    body = repair_connected_strokes(supported, body_config or BodyConfig())
    final = post_supported_marks(
        body,
        post_mark_config
        or AssociationConfig(
            uncertainty_mode="support_only", max_vertical_gap_chars=1.1, max_score_chars=1.1
        ),
    )
    for key in [
        "association_decisions",
        "changed_components",
        "semantic_penalty_by_boundary",
        "semantic_associations_by_boundary",
    ]:
        if key in final:
            final["initial_" + key] = final.pop(key)
    final["unsupported_ink"] = unsupported_ink_flags(
        final["original_mask"],
        final["labels"],
        final["strip_match_positions"],
        final["strip_x"],
        final["strip_width"],
        final["scale"],
    )
    final["metrics"]["unsupported_ink_components"] = len(final["unsupported_ink"])
    final["desired_foreground_owners"] = final["labels"].copy()
    final["initial_support_owners"] = initial
    final["quality_config"] = {
        "seam": final["config"],
        "body": final["body_config"],
        "post_marks": final["post_mark_config"],
    }
    final["metrics"]["changed_foreground_pixels"] = int(
        np.count_nonzero(final["original_mask"] & (final["labels"] != initial))
    )
    final["metrics"]["runtime_seconds_raw_image_pipeline_including_legacy_ablations"] = (
        time.perf_counter() - started
    )
    return final


# Fallback DIP
def segment_dip_with_fallback(image, config=None, *, allow_fallback=False, method="dip"):
    if method != "dip":
        raise ValueError("This baseline fixes method='dip'")
    errors = []
    options = {}
    if config:
        constructors = {
            "seam": SeamConfig,
            "association": AssociationConfig,
            "body": BodyConfig,
            "post_mark": AssociationConfig,
        }
        for name, settings in config.items():
            if name not in constructors:
                raise ValueError(f"Unknown segmentation config section: {name}")
            options[name + "_config"] = constructors[name](**settings)
    try:
        result = segment_quality_paragraph(image, **options)
        return {
            "status": "ok",
            "strict_status": "ok",
            "fallback_mode": "none",
            "errors": [],
            "result": result,
        }
    except (ValueError, AssertionError) as exc:
        errors.append({"method": "strict", "error": f"{type(exc).__name__}: {exc}"})
    if allow_fallback:
        for mode in ("density_ridge", "fixed_seed"):
            try:
                result = segment_dip_seams(
                    image, SeamConfig(corridor_fraction=0.48, guide_mode=mode)
                )
                return {
                    "status": "fallback",
                    "strict_status": "review_exception",
                    "fallback_mode": mode + "_dp",
                    "errors": errors,
                    "result": result,
                }
            except (ValueError, AssertionError) as exc:
                errors.append({"method": mode, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "status": "failed",
        "strict_status": "review_exception",
        "fallback_mode": "none",
        "errors": errors,
        "result": None,
    }


# Ước lượng thang từ nét
class BodyScaleEstimationError(ValueError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


def weighted_median(values, weights):
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order], dtype=float)
    return float(values[order[np.searchsorted(cumulative, 0.5 * cumulative[-1], side="left")]])


def stroke_evidence(mask, *, weight_power=2.0, include_fields=False):
    mask = np.asarray(mask)
    if mask.ndim != 2 or mask.dtype != bool or (not mask.any()):
        raise ValueError("Need a nonempty two-dimensional bool ink mask")
    if not np.isfinite(weight_power) or weight_power <= 0:
        raise ValueError("Stroke weight power must be finite and positive")
    padded = np.pad(mask.astype(np.uint8), 1)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)[1:-1, 1:-1].copy()
    maxima = mask & (distance >= cv2.dilate(distance, np.ones((3, 3), np.uint8)) - 1e-06)
    diameters = np.maximum(1.0, 2 * distance[maxima].astype(float) - 1.0)
    weights = diameters**weight_power
    width = weighted_median(diameters, weights)
    result = {
        "width_proxy": width,
        "ridge_diameters": diameters,
        "ridge_weights": weights,
        "ridge_yx": np.column_stack(np.nonzero(maxima)),
        "weight_power": weight_power,
        "diameter_convention": "max(1,2*distance_to_zero-1)",
        "outside_image": "one-pixel zero border",
    }
    if include_fields:
        result.update(distance=distance, ridge_mask=maxima)
    return result


def estimate_body_scale(
    mask, config=BodyScaleConfig(), *, source_scale_xy=(1.0, 1.0), include_fields=False
):
    mask = np.asarray(mask)
    if mask.ndim != 2 or mask.dtype != bool:
        raise ValueError("Expected a two-dimensional bool ink mask")
    sx, sy = map(float, source_scale_xy)
    if not all((np.isfinite(value) and value > 0 for value in (sx, sy))):
        raise ValueError("Source-to-analysis scales must be finite and positive")
    count, labels, full_stats, centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    if count <= 1:
        raise BodyScaleEstimationError(
            "No substantial ink component",
            {
                "config": asdict(config),
                "component_stats": full_stats[1:],
                "retained_components": 0,
                "reference_used": False,
            },
        )
    stats = full_stats[1:]
    x, y, width, height, area = stats.T
    stroke = None
    if config.method in ("legacy", "source_gate"):
        gx, gy = (sx, sy) if config.method == "source_gate" else (1.0, 1.0)
        thresholds = {
            "area": config.min_area_pixels * gx * gy,
            "height": config.min_height_pixels * gy,
            "width": config.min_width_pixels * gx,
        }
        floor = config.min_scale_pixels * gy
    else:
        stroke = stroke_evidence(
            mask, weight_power=config.stroke_peak_weight_power, include_fields=include_fields
        )
        sw = stroke["width_proxy"]
        thresholds = {
            "area": config.min_area_strokes2 * sw**2,
            "height": config.min_height_strokes * sw,
            "width": config.min_width_strokes * sw,
        }
        floor = 1.0
    area_pass = area >= thresholds["area"]
    height_pass = height >= thresholds["height"]
    width_pass = width >= thresholds["width"]
    keep = area_pass & height_pass & width_pass
    if not keep.any():
        evidence = {
            "config": asdict(config),
            "component_ids": np.arange(1, count),
            "component_stats": stats,
            "component_centroids": centroids[1:],
            "retained": keep,
            "area_gate_pass": area_pass,
            "height_gate_pass": height_pass,
            "width_gate_pass": width_pass,
            "effective_thresholds": thresholds,
            "stroke": stroke,
            "retained_components": 0,
            "reference_used": False,
            "fallback_used": False,
        }
        if include_fields:
            evidence["component_labels"] = labels
        raise BodyScaleEstimationError("No CC passes the declared body-scale gates", evidence)
    heights = height[keep].astype(float)
    quantiles = np.percentile(heights, [40, 65, 80]).tolist()
    chosen = float(np.percentile(heights, 100 * config.height_quantile))
    mode = None
    if config.method == "stroke_mode":
        z = np.log(heights / stroke["width_proxy"])
        weights = np.sqrt(area[keep].astype(float))
        weights = np.minimum(weights, config.component_weight_cap * np.median(weights))
        grid = np.linspace(
            z.min() - config.log_height_bandwidth,
            z.max() + config.log_height_bandwidth,
            config.mode_grid_points,
        )
        density = np.exp(-0.5 * ((grid[:, None] - z) / config.log_height_bandwidth) ** 2) @ weights
        index = int(np.argmax(density))
        chosen = float(np.exp(grid[index]) * stroke["width_proxy"])
        mode = {
            "log_height_over_stroke": z,
            "component_weights": weights,
            "grid_log_height_over_stroke": grid,
            "density": density,
            "selected_index": index,
            "selected_height": chosen,
            "bandwidth": config.log_height_bandwidth,
        }
    result = {
        "char_height": max(floor, chosen),
        "height_quantiles": quantiles,
        "config": asdict(config),
        "source_scale_xy": [sx, sy],
        "component_ids": np.arange(1, count),
        "component_stats": stats,
        "component_centroids": centroids[1:],
        "retained": keep,
        "area_gate_pass": area_pass,
        "height_gate_pass": height_pass,
        "width_gate_pass": width_pass,
        "effective_thresholds": thresholds,
        "minimum_scale": floor,
        "stroke": stroke,
        "mode": mode,
        "retained_components": int(keep.sum()),
        "scalar_role": "heuristic geometric scale; not labeled x-height",
        "reference_used": False,
        "fallback_used": False,
    }
    if include_fields:
        result["component_labels"] = labels
    return result


def height_hook(evidence, *, evidence_to_analysis_y=1.0):
    factor = float(evidence_to_analysis_y)
    if not np.isfinite(factor) or factor <= 0:
        raise ValueError("Height conversion factor must be positive")
    height = float(evidence["char_height"]) * factor
    quantiles = (np.asarray(evidence["height_quantiles"]) * factor).tolist()

    def hook(mask):
        return (height, quantiles.copy())

    return hook


# Cấu hình khởi tạo lõi
@dataclass(frozen=True)
class SeedProfileConfig:
    scales: tuple[float, ...] = (0.75, 1.0, 1.25)
    smoothing_chars: float = 0.14
    local_width_chars: float = 4.0
    local_width_fraction: float = 0.16
    local_strip_count: int = 11

    def __post_init__(self):
        if not self.scales or any((not np.isfinite(s) or s <= 0 for s in self.scales)):
            raise ValueError("Seed scales must be finite and positive")
        if min(self.smoothing_chars, self.local_width_chars, self.local_width_fraction) <= 0:
            raise ValueError("Seed dimensions must be positive")
        if not 0 < self.local_width_fraction <= 1 or self.local_strip_count < 1:
            raise ValueError("Invalid local-strip geometry")


# Peak tại biên ảnh
def support_profile_peaks(profile, distance, prominence):
    values = np.r_[0.0, profile, 0.0]
    peaks, props = find_peaks(values, distance=max(1.0, distance), prominence=prominence)
    keep = (peaks > 0) & (peaks <= len(profile))
    return (peaks[keep] - 1, props["prominences"][keep])


# Projection đa thang
def seed_profile_evidence(mask, char_height, config, seed_config=SeedProfileConfig()):
    if not np.isfinite(char_height) or char_height <= 0:
        raise ValueError("Character height must be finite and positive")
    observations = []
    for scale in seed_config.scales:
        sigma = max(1.0, seed_config.smoothing_chars * char_height * scale)
        global_profile = gaussian_filter1d(mask.mean(axis=1).astype(float), sigma)
        global_profile /= max(global_profile.max(), 1e-09)
        width = min(
            mask.shape[1],
            max(
                round(seed_config.local_width_chars * char_height),
                round(seed_config.local_width_fraction * mask.shape[1]),
            ),
        )
        strips, ranges = ([], [])
        for x in np.linspace(0, mask.shape[1] - width, seed_config.local_strip_count).astype(int):
            profile = gaussian_filter1d(mask[:, x : x + width].mean(axis=1).astype(float), sigma)
            strips.append(profile / max(profile.max(), 1e-09))
            ranges.append((int(x), int(x + width)))
        local_max = np.max(strips, axis=0)
        score = (
            1 - config.local_profile_weight
        ) * global_profile + config.local_profile_weight * local_max
        centers, prominence = support_profile_peaks(
            score, config.min_separation_chars * char_height, config.seed_prominence
        )
        observations.append(
            {
                "scale": float(scale),
                "sigma_pixels": sigma,
                "global_profile": global_profile,
                "strip_profiles": np.asarray(strips),
                "strip_x_ranges": ranges,
                "local_max_profile": local_max,
                "fused_score": score,
                "centers": centers,
                "prominences": prominence,
            }
        )
    if not any((len(o["centers"]) for o in observations)):
        raise ValueError("No line core; explicit failure")
    counts = [len(o["centers"]) for o in observations]
    median = int(np.median(counts))
    chosen = min(
        range(len(observations)),
        key=lambda i: (abs(counts[i] - median), -observations[i]["prominences"].sum()),
    )
    log = {"scale_counts": counts, "selected_scale": float(seed_config.scales[chosen])}
    return (
        observations[chosen]["centers"],
        log,
        {
            "seed_config": asdict(seed_config),
            "observations": observations,
            "selected_index": chosen,
        },
    )


# Skew, ridge và phục hồi lõi
def estimate_legacy_body_height(mask):
    _, _, st, _ = cv2.connectedComponentsWithStats(mask.astype("uint8"), connectivity=8)
    st = st[1:]
    good = st[(st[:, 4] >= 12) & (st[:, 3] >= 5) & (st[:, 2] >= 2)]
    if not len(good):
        raise ValueError("No substantial ink component")
    heights = good[:, 3].astype(float)
    char_h = float(np.percentile(heights, 65))
    return (max(6.0, char_h), np.percentile(heights, [40, 65, 80]).tolist())


def track_supported_ridges(mask, centers, ch, cfg):
    density = cv2.GaussianBlur(
        mask.astype("float32"), (0, 0), sigmaX=max(2.0, ch), sigmaY=max(1.0, 0.16 * ch)
    )
    edges = np.r_[0.0, (centers[:-1] + centers[1:]) / 2, mask.shape[0]]
    ridges, support = ([], [])
    for i, center in enumerate(centers):
        a, b = (max(0, int(edges[i])), min(mask.shape[0], int(np.ceil(edges[i + 1]))))
        ys = np.arange(a, b)[:, None]
        local = density[a:b]
        regularized = local - 0.015 * ((ys - center) / ch) ** 2
        y = regularized.argmax(axis=0).astype(float) + a
        strength = local.max(axis=0)
        supported = strength >= max(float(np.quantile(strength, 0.9)) * cfg.support_fraction, 0.005)
        if not supported.any():
            y[:] = center
        else:
            xx = np.arange(mask.shape[1])
            y = np.interp(xx, xx[supported], y[supported])
        ridges.append(gaussian_filter1d(y, max(1.0, 0.6 * ch)))
        support.append(supported)
    return (np.asarray(ridges), np.asarray(support), density)


def recover_residual_lines(mask, centers, ch, cfg):
    decisions = []
    if not cfg.recover_residual:
        return (centers, decisions)
    for iteration in range(2):
        ridges, support, _ = track_supported_ridges(mask, centers, ch, cfg)
        yy, xx = np.nonzero(mask)
        distances = np.abs(yy[None, :] - ridges[:, xx])
        if cfg.limit_x_support:
            distances += ~support[:, xx] * ch
        residual = np.zeros_like(mask)
        _, cc, st, centroids = cv2.connectedComponentsWithStats(
            mask.astype("uint8"), connectivity=8
        )
        nearest = np.zeros_like(mask, dtype=float)
        nearest[yy, xx] = distances.min(axis=0)
        residual_bodies = []
        for k in range(1, len(st)):
            x, y, w, h, area = st[k]
            if h < 0.45 * ch or area < 0.05 * ch**2:
                continue
            local = cc[y : y + h, x : x + w] == k
            d = nearest[y : y + h, x : x + w][local]
            if np.mean(d < 0.48 * ch) < 0.15 and np.median(d) > cfg.residual_distance_chars * ch:
                residual[y : y + h, x : x + w][local] = True
                if (
                    h >= cfg.residual_body_height_chars * ch
                    and area >= cfg.residual_body_area_chars2 * ch**2
                ):
                    residual_bodies.append(k)
        score = gaussian_filter1d(residual.sum(axis=1).astype(float), max(1.0, 0.15 * ch))
        if score.max() <= 0:
            break
        peaks, _ = support_profile_peaks(score / score.max(), 0.85 * ch, 0.18)
        admitted = []
        pitch = float(np.median(np.diff(centers))) if len(centers) > 1 else 2.0 * ch
        effective_pitch = min(pitch, cfg.residual_pitch_cap_chars * ch)
        minimum_separation = max(
            cfg.min_separation_chars * ch, cfg.residual_min_pitch_fraction * effective_pitch
        )
        for peak in peaks:
            a, b = (max(0, int(peak - 0.35 * ch)), min(mask.shape[0], int(peak + 0.35 * ch + 1)))
            ry, rx = np.nonzero(residual[a:b])
            mass = len(rx) / ch**2
            width = (np.ptp(rx) + 1) / ch if len(rx) else 0.0
            nearby = [k for k in residual_bodies if abs(centroids[k, 1] - peak) <= 0.9 * ch]
            wide_body = any(
                (
                    st[k, 2] >= cfg.residual_single_body_width_chars * ch
                    and st[k, 4] >= 0.4 * ch**2
                    for k in nearby
                )
            )
            body_evidence = len(nearby) >= 2 or wide_body
            compared = np.r_[centers, admitted]
            separated = bool(np.min(np.abs(compared - peak)) >= minimum_separation)
            accept = (
                separated
                and mass >= cfg.residual_min_mass_chars2
                and (width >= 0.8)
                and body_evidence
            )
            reasons = []
            if not separated:
                reasons.append("too_close_to_existing_or_admitted_core")
            if mass < cfg.residual_min_mass_chars2 or width < 0.8:
                reasons.append("insufficient_residual_ink")
            if not body_evidence:
                reasons.append("no_independent_body_support")
            decisions.append(
                {
                    "iteration": iteration,
                    "y": int(peak),
                    "mass_chars2": mass,
                    "width_chars": width,
                    "pitch_pixels": pitch,
                    "minimum_separation_pixels": float(minimum_separation),
                    "body_component_ids": [int(k) for k in nearby],
                    "wide_body_support": bool(wide_body),
                    "reasons": reasons,
                    "accepted": bool(accept),
                }
            )
            if accept:
                admitted.append(peak)
        if not admitted:
            break
        centers = np.sort(np.r_[centers, admitted])
    return (centers, decisions)


def shear_binary_mask(mask, slope):
    h, w = mask.shape
    pad = int(np.ceil(abs(slope) * w / 2)) + 2
    x = np.arange(w, dtype=np.float32)[None, :]
    y = np.arange(h + 2 * pad, dtype=np.float32)[:, None]
    mx = np.broadcast_to(x, (h + 2 * pad, w)).copy()
    my = np.broadcast_to(y - pad + slope * (x - (w - 1) / 2), mx.shape).astype(np.float32).copy()
    return (
        cv2.remap(
            mask.astype("uint8"), mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT
        ).astype(bool),
        pad,
    )


def estimate_support_skew(mask, ch, cfg):
    if not cfg.deskew or cfg.max_skew_degrees == 0:
        return (0.0, [{"degrees": 0.0, "score": None}])
    probe = cv2.resize(
        mask.astype("uint8"),
        (
            min(600, mask.shape[1]),
            max(2, round(mask.shape[0] * min(600, mask.shape[1]) / mask.shape[1])),
        ),
        interpolation=cv2.INTER_NEAREST,
    ).astype(bool)
    sigma = max(1.0, 0.1 * ch * probe.shape[1] / mask.shape[1])
    records = []
    for degree in np.arange(
        -cfg.max_skew_degrees, cfg.max_skew_degrees + 0.01, cfg.skew_step_degrees
    ):
        sheared, _ = shear_binary_mask(probe, np.tan(np.deg2rad(degree)))
        profile = gaussian_filter1d(sheared.sum(axis=1).astype(float), sigma)
        records.append({"degrees": float(degree), "score": float(np.dot(profile, profile))})
    best = max(records, key=lambda r: (r["score"], -abs(r["degrees"]), -r["degrees"]))
    return (float(np.tan(np.deg2rad(best["degrees"]))), records)


# Thứ tự thực thi Support
def trace_count_core_stages(
    image, config=SupportConfig(), *, seed_config=SeedProfileConfig(), hooks=None
):
    started = time.perf_counter()
    hooks = dict(hooks or {})
    allowed = {"binarize", "height", "skew", "seed", "recover", "track", "owners"}
    if set(hooks) - allowed:
        raise ValueError("Unknown detector stage hook")
    if any((not callable(value) for value in hooks.values())):
        raise ValueError("Stage hooks must be callable")
    if isinstance(image, (str, Path)):
        gray = read_gray(image)
    elif isinstance(image, Image.Image):
        gray = np.asarray(image.convert("L")).copy()
    else:
        gray = np.asarray(image).copy()
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("Expected uint8 grayscale image")
    h, w = gray.shape
    sw = min(w, config.analysis_width)
    sh = max(2, round(h * sw / w))
    reduced = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA)
    mask, threshold = hooks.get("binarize", binarize)(reduced)
    ch, quantiles = hooks.get("height", estimate_legacy_body_height)(mask)
    slope, skew_scores = hooks.get("skew", estimate_support_skew)(mask, ch, config)
    analysis, pad = shear_binary_mask(mask, slope)
    if "seed" in hooks:
        centers, seed_log = hooks["seed"](analysis, ch, config)
        seed_trace = {"custom_seed_hook": True, "summary": seed_log}
    else:
        centers, seed_log, seed_trace = seed_profile_evidence(analysis, ch, config, seed_config)
    centers = np.asarray(centers).copy()
    initial_centers = centers.copy()
    centers, residual = hooks.get("recover", recover_residual_lines)(analysis, centers, ch, config)
    ridges, supported, density = hooks.get("track", track_supported_ridges)(
        analysis, centers, ch, config
    )
    if len(ridges) > 1 and np.any(np.diff(ridges, axis=0) <= 0):
        raise ValueError("Core tracks cross; review required")
    original_x = (np.arange(w) + 0.5) * sw / w - 0.5
    curves, source_support = ([], [])
    for curve, valid in zip(ridges, supported):
        source_y = (
            np.interp(original_x, np.arange(sw), curve) - pad + slope * (original_x - (sw - 1) / 2)
        )
        curves.append((source_y + 0.5) * h / sh - 0.5)
        source_support.append(np.interp(original_x, np.arange(sw), valid.astype(float)) >= 0.5)
    curves, source_support = (np.asarray(curves), np.asarray(source_support))
    labels, foreground, decisions = hooks.get("owners", assign_supported_owners)(
        gray, curves, source_support, ch * h / sh, config
    )
    crops = crops_from_owners(gray, labels, config.padding)
    ambiguous = [
        d["component_id"] for d in decisions if d.get("compact") and d.get("mark_accepted") is False
    ]
    warnings = []
    if ambiguous:
        warnings.append({"type": "ambiguous_compact_components", "component_ids": ambiguous})
    if residual and any((r["accepted"] for r in residual)):
        warnings.append(
            {"type": "residual_core_recovery", "count": len(centers) - len(initial_centers)}
        )
    if abs(slope) >= np.tan(np.deg2rad(config.max_skew_degrees)) - 1e-06 and config.deskew:
        warnings.append({"type": "skew_search_at_limit"})
    result = {
        "gray": gray,
        "original_mask": foreground,
        "labels": labels,
        "original_ridges": curves,
        "support": source_support,
        "crops": crops,
        "seams": np.rint((curves[:-1] + curves[1:]) / 2).astype(np.int32),
        "config": asdict(config),
        "warnings": warnings,
        "component_decisions": decisions,
        "analysis": {
            "char_height": ch,
            "height_quantiles": quantiles,
            "skew_degrees": float(np.rad2deg(np.arctan(slope))),
            "skew_scores": skew_scores,
            "threshold": threshold,
            "seed": seed_log,
            "initial_lines": len(initial_centers),
            "residual_decisions": residual,
        },
        "metrics": {
            "n_lines": len(crops),
            "foreground_pixels": int(foreground.sum()),
            "foreground_assigned": int(np.count_nonzero(labels[foreground])),
            "multiline_components": sum((d["multi_line"] for d in decisions)),
            "ambiguous_compact_components": len(ambiguous),
            "runtime_seconds": time.perf_counter() - started,
            "semantic_accuracy_measured": False,
        },
    }
    trace = {
        "gray": gray,
        "reduced": reduced,
        "mask": mask,
        "sheared_mask": analysis,
        "threshold": threshold,
        "char_height_analysis": ch,
        "char_height_source": ch * h / sh,
        "height_quantiles": quantiles,
        "slope": slope,
        "skew_scores": skew_scores,
        "shear_pad": pad,
        "source_x_in_analysis": original_x,
        "seed": seed_trace,
        "initial_centers": initial_centers,
        "recovered_centers": centers,
        "residual_decisions": residual,
        "density": density,
        "analysis_ridges": ridges,
        "analysis_support": supported,
        "custom_hooks": sorted(hooks),
        "recovery_uses_original_tracker_unless_replaced": True,
        "reference_used_in_inference": False,
    }
    return {"result": result, "trace": trace}


# Gắn thang chữ vào Support
def segment_with_body_scale(
    gray,
    support_config=SupportConfig(),
    scale_config=BodyScaleConfig(),
    *,
    anchor_to_source=False,
    full_trace=False,
):
    gray = np.asarray(gray)
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("Expected uint8 grayscale image")
    h, w = gray.shape
    sw = min(w, support_config.analysis_width)
    sh = max(2, round(h * sw / w))
    analysis_gray = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA)
    analysis_mask, threshold = binarize(analysis_gray)
    if anchor_to_source:
        evidence_mask, evidence_threshold = binarize(gray)
        frame = (1.0, 1.0)
        conversion = sh / h
    else:
        evidence_mask, evidence_threshold = (analysis_mask, threshold)
        frame = (sw / w, sh / h)
        conversion = 1.0
    evidence = estimate_body_scale(
        evidence_mask, scale_config, source_scale_xy=frame, include_fields=full_trace
    )
    traced = trace_count_core_stages(
        gray,
        support_config,
        hooks={"height": height_hook(evidence, evidence_to_analysis_y=conversion)},
    )
    assert np.array_equal(traced["trace"]["mask"], analysis_mask), (
        "Detector mask changed after scale estimation"
    )
    report = {
        "scale_config": asdict(scale_config),
        "anchor_to_source": bool(anchor_to_source),
        "source_shape": [h, w],
        "analysis_shape": [sh, sw],
        "evidence_shape": list(evidence_mask.shape),
        "analysis_Otsu_threshold": threshold,
        "evidence_Otsu_threshold": evidence_threshold,
        "evidence_to_analysis_y": conversion,
        "char_height_evidence": evidence["char_height"],
        "char_height_analysis": evidence["char_height"] * conversion,
        "char_height_source": evidence["char_height"] * conversion * h / sh,
        "retained_components": evidence["retained_components"],
        "stroke_width_proxy_evidence": None
        if evidence["stroke"] is None
        else evidence["stroke"]["width_proxy"],
        "reference_used_in_inference": False,
        "custom_stage": "height only",
        "source_foreground_rule_unchanged": True,
        "ownership_rules_unchanged": True,
    }
    result = {"result": traced["result"], "scale_evidence": evidence, "scale_report": report}
    if full_trace:
        result["trace"] = {**traced["trace"], "scale_input_mask": evidence_mask}
    return result


# Ghép Native từ hai giả thuyết
def read_native_input(image):
    path = Path(image) if isinstance(image, (str, Path)) else None
    if isinstance(image, np.ndarray) and image.ndim == 3:
        image = Image.fromarray(image)
    gray = read_gray(image)
    return (
        gray,
        path,
        {"path": str(path) if path is not None else None, "gray_shape": list(gray.shape)},
    )


def segment_native_adaptive(
    image, config=NativeAdaptiveConfig(), *, full_trace=False, keep_branches=True
):
    if not isinstance(config, NativeAdaptiveConfig):
        raise TypeError("config must be a NativeAdaptiveConfig")
    tick = time.perf_counter()
    gray, path, source = read_native_input(image)
    native = replace(
        config.adaptive,
        support=replace(config.adaptive.support, analysis_width=max(128, gray.shape[1])),
    )
    errors, support, wrapped = ([], None, None)
    support_status = "failed"
    scale_failure_evidence = None
    try:
        wrapped = segment_with_body_scale(gray, native.support, config.scale, full_trace=full_trace)
        try:
            support = repair_core_fragments(wrapped["result"], native)
            support_status = "ok"
        except (ValueError, AssertionError) as exc:
            errors.append({"stage": "core_repair", "error": f"{type(exc).__name__}: {exc}"})
            support = refine_split_components(wrapped["result"], native.split)
            support_status = "fallback"
    except (ValueError, AssertionError) as exc:
        errors.append({"stage": "native_support", "error": f"{type(exc).__name__}: {exc}"})
        if isinstance(exc, BodyScaleEstimationError):
            scale_failure_evidence = exc.evidence
    dip = segment_dip_with_fallback(gray, allow_fallback=True)
    errors.extend(({"stage": "dip", **error} for error in dip["errors"]))
    result = None
    try:
        result = combine_image_hypotheses(dip["result"], support, native)
        status = "ok" if dip["status"] == support_status == "ok" else "fallback"
        result["native_adaptive_parameters"] = {
            "requested": asdict(config),
            "effective_adaptive": asdict(native),
        }
        result["adaptive_decision"].update(
            dip_status=dip["status"],
            native_support_status=support_status,
            body_scale_estimator=config.scale.method,
        )
        result["metrics"]["runtime_seconds_native_adaptive"] = time.perf_counter() - tick
    except (ValueError, AssertionError) as exc:
        status = "failed"
        errors.append({"stage": "routing", "error": f"{type(exc).__name__}: {exc}"})
    stages = {
        "source_gray": gray,
        "scale_evidence": wrapped["scale_evidence"]
        if wrapped is not None
        else scale_failure_evidence,
        "scale_report": wrapped["scale_report"] if wrapped is not None else None,
        "dip_coverage": {k: v for k, v in dip.items() if k != "result"},
        "native_support_status": support_status,
    }
    if full_trace and wrapped is not None:
        stages["support_trace"] = wrapped["trace"]
    if keep_branches:
        stages.update(
            dip_result=dip["result"],
            support_result=support,
            support_before_repair=wrapped["result"] if wrapped is not None else None,
        )
    return {
        "status": status,
        "strict_status": "ok" if status == "ok" else "review_exception",
        "fallback_mode": result["adaptive_decision"]["selected"]
        if status == "fallback"
        else "none",
        "errors": errors,
        "result": result,
        "source": source,
        "stages": stages,
        "parameters": {"requested": asdict(config), "effective_adaptive": asdict(native)},
        "reference_used_in_inference": False,
        "method": "native_stroke_scale_adaptive",
        "scope": "Train/Val-selected CPU research candidate; final Test/external evidence separate",
    }


# Lõi mực V2c
V2C_MARGIN_PX = 8
V2C_WIDTH_PX = 2048


def normalize(text):
    return unicodedata.normalize("NFC", text).strip()


def ink_mask(image):
    gray = np.asarray(image.convert("L"))
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    w0 = np.cumsum(hist)
    moment = np.cumsum(hist * np.arange(256))
    w1 = total - w0
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (moment[-1] * w0 / total - moment) ** 2 / (w0 * w1)
    threshold = int(np.argmax(np.nan_to_num(between)))
    return gray <= threshold


def ink_bbox(image):
    mask = ink_mask(image)
    height, width = mask.shape
    columns = np.flatnonzero(mask.sum(0) >= max(2, int(0.01 * height)))
    rows = np.flatnonzero(mask.sum(1) >= max(2, int(0.005 * width)))
    if not len(columns) or not len(rows):
        return None
    return (int(columns[0]), int(rows[0]), int(columns[-1] + 1), int(rows[-1] + 1))


def ink_components(image):
    labels, count = ndimage.label(ink_mask(image), structure=np.ones((3, 3), dtype=bool))
    areas = np.bincount(labels.ravel(), minlength=count + 1)
    areas[0] = 0
    return (labels, areas)


def ink_bbox_v2(image):
    core = ink_bbox(image)
    if core is None:
        return None
    labels, areas = ink_components(image)
    left, top, right, bottom = core
    padding = int(np.ceil(0.25 * (bottom - top)))
    neighborhood = labels[
        max(0, top - padding) : min(image.height, bottom + padding),
        max(0, left - padding) : min(image.width, right + padding),
    ]
    kept = np.zeros(len(areas), dtype=bool)
    nearby = np.unique(neighborhood)
    kept[nearby[areas[nearby] >= 4]] = True
    ys, xs = np.nonzero(kept[labels])
    if not len(xs):
        return core
    return (
        min(left, int(xs.min())),
        min(top, int(ys.min())),
        max(right, int(xs.max()) + 1),
        max(bottom, int(ys.max()) + 1),
    )


# Chuẩn hóa lề V2c
def _background_rgb(image, mask):
    rgb = np.asarray(image.convert("RGB"))
    pixels = rgb[~np.asarray(mask, dtype=bool)]
    if not len(pixels):
        pixels = rgb.reshape(-1, 3)
    return tuple((int(value) for value in np.median(pixels, axis=0)))


def _normalize_margins(image, lr_px, tb_px, ref_width):
    box = ink_bbox_v2(image)
    info = {
        "bbox_found": box is not None,
        "bbox": box,
        "source_size": image.size,
        "lr_px": lr_px,
        "tb_px": tb_px,
        "ref_width": ref_width,
    }
    if box is None:
        info["output_size"] = image.size
        return (image.copy(), info)
    background = _background_rgb(image, ink_mask(image))
    crop = image.convert("RGB").crop(box)
    width = ref_width - 2 * lr_px
    height = max(1, round(crop.height * width / crop.width))
    if height > 4096:
        raise ValueError("Vùng chữ quá cao và hẹp. Hãy xoay ảnh hoặc cắt một dòng ngang.")
    crop = crop.resize((width, height), Image.Resampling.LANCZOS)
    result = Image.new("RGB", (ref_width, height + 2 * tb_px), background)
    result.paste(crop, (lr_px, tb_px))
    info.update(background_rgb=background, content_size=crop.size, output_size=result.size)
    return (result, info)


def prepare_image(image, pre="v2c"):
    if pre == "raw":
        return (image.copy(), None)
    if pre != "v2c":
        raise ValueError('pre phải là "v2c" hoặc "raw".')
    return _normalize_margins(image, V2C_MARGIN_PX, V2C_MARGIN_PX, V2C_WIDTH_PX)


# VGG19-BN và Transformer
class _Vgg(nn.Module):
    def __init__(self, ss, ks, hidden):
        super().__init__()
        layers, channels, pool = ([], 3, 0)
        for item in VGG19_LAYERS:
            if item == "P":
                layers.append(nn.AvgPool2d(kernel_size=ks[pool], stride=ss[pool], padding=0))
                pool += 1
            else:
                layers += [
                    nn.Conv2d(channels, item, kernel_size=3, padding=1),
                    nn.BatchNorm2d(item),
                    nn.ReLU(inplace=True),
                ]
                channels = item
        self.features = nn.Sequential(*layers)
        self.last_conv_1x1 = nn.Conv2d(512, hidden, 1)

    def forward(self, x):
        conv = self.last_conv_1x1(self.features(x))
        return conv.transpose(-1, -2).flatten(2).permute(-1, 0, 1)


class _Cnn(nn.Module):
    def __init__(self, ss, ks, hidden):
        super().__init__()
        self.model = _Vgg(ss, ks, hidden)

    def forward(self, x):
        return self.model(x)


class _PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len):
        super().__init__()
        self.register_buffer("pe", torch.zeros(max_len, 1, d_model))

    def forward(self, x):
        return x + self.pe[: x.size(0), :]


class _LanguageTransformer(nn.Module):
    def __init__(
        self,
        vocab_size,
        d_model,
        nhead,
        num_encoder_layers,
        num_decoder_layers,
        dim_feedforward,
        max_seq_length,
        trans_dropout,
        **_,
    ):
        super().__init__()
        self.d_model = d_model
        self.embed_tgt = nn.Embedding(vocab_size, d_model)
        self.pos_enc = _PositionalEncoding(d_model, max_seq_length)
        self.transformer = nn.Transformer(
            d_model, nhead, num_encoder_layers, num_decoder_layers, dim_feedforward, trans_dropout
        )
        self.fc = nn.Linear(d_model, vocab_size)

    def forward_encoder(self, src):
        return self.transformer.encoder(self.pos_enc(src * math.sqrt(self.d_model)))

    def forward_decoder(self, tgt, memory):
        length = tgt.shape[0]
        mask = (torch.triu(torch.ones(length, length)) == 1).transpose(0, 1)
        mask = (
            mask.float()
            .masked_fill(mask == 0, float("-inf"))
            .masked_fill(mask == 1, 0.0)
            .to(tgt.device)
        )
        tgt = self.pos_enc(self.embed_tgt(tgt) * math.sqrt(self.d_model))
        return self.fc(self.transformer.decoder(tgt, memory, tgt_mask=mask).transpose(0, 1))


class _VietOCR(nn.Module):
    def __init__(self, vocab_size, cnn, transformer):
        super().__init__()
        self.cnn = _Cnn(cnn["ss"], cnn["ks"], cnn["hidden"])
        self.transformer = _LanguageTransformer(vocab_size, **transformer)


# Cấu hình scanner và khung mực
@dataclass(frozen=True)
class DocumentScannerConfig:
    """Cấu hình ứng viên, tính theo kích thước thân chữ hoặc thang 8 bit."""

    probe_long_side: int = 1200
    binarizer: str = "sauvola"
    sauvola_k: float = 0.18
    sauvola_window_chars: float = 3.0
    use_color: bool = True
    rectify: bool = True
    line_render: str = "gray"
    outside_fraction: float = 0.055
    background_spread: float = 24.0
    minimum_rotation: float = 1.2

    def __post_init__(self):
        if self.binarizer not in {"sauvola", "otsu"} or self.line_render not in {"gray", "binary"}:
            raise ValueError("Cấu hình nhị phân hóa hoặc ảnh dòng không hợp lệ.")
        if not 128 <= self.probe_long_side <= 1200:
            raise ValueError("Cạnh dài của ảnh phân tích phải trong [128, 1200].")
        if not 0.05 <= self.sauvola_k <= 0.45 or self.sauvola_window_chars < 1:
            raise ValueError("Tham số Sauvola không hợp lệ.")
        if not 0 < self.outside_fraction < 1 or not 0 < self.background_spread <= 255:
            raise ValueError("Ngưỡng nền phải dương và thuộc miền đo.")
        if not 0 < self.minimum_rotation < 20:
            raise ValueError("Ngưỡng chỉnh nghiêng phải trong (0, 20) độ.")


def scanner_odd(value, minimum=3):
    return max(minimum, 2 * int(round((value - 1) / 2)) + 1)


def scanner_reduce(array, long_side):
    height, width = array.shape[:2]
    scale = min(1.0, long_side / max(height, width))
    if scale == 1:
        return array
    shape = (max(2, round(width * scale)), max(2, round(height * scale)))
    return cv2.resize(array, shape, interpolation=cv2.INTER_AREA)


def scanner_bbox(mask):
    x, y, width, height = cv2.boundingRect(mask.astype(np.uint8))
    return [x, y, x + width, y + height] if width and height else None


def scanner_mask_crop(gray, mask):
    box = scanner_bbox(mask)
    if box is None:
        return (np.full((1, 1), 255, np.uint8), np.zeros((1, 1), bool), None)
    x0, y0, x1, y1 = box
    cropped_mask = mask[y0:y1, x0:x1].copy()
    return (np.where(cropped_mask, gray[y0:y1, x0:x1], 255), cropped_mask, box)


# Xác định tờ giấy chính
def scanner_paper_probe(rgb):
    """Tìm mặt giấy bằng vùng màu sáng ít texture và cụm có dạng nét chữ."""
    lab = cv2.cvtColor(cv2.GaussianBlur(rgb, (5, 5), 0), cv2.COLOR_RGB2LAB)
    light, a, b = cv2.split(lab.astype(np.int16))
    height, width = light.shape
    low_light = max(82, np.percentile(light, 78) - 48)
    seed = (light >= low_light) & (np.abs(a - 128) <= 17) & (b >= 99) & (b <= 136)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (scanner_odd(0.018 * min(height, width)),) * 2
    )
    colors = cv2.morphologyEx(seed.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    colors = cv2.morphologyEx(colors, cv2.MORPH_CLOSE, kernel)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(colors, connectivity=8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    window = scanner_odd(min(height, width) / 33, 9)
    texture = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, np.ones((window, window), np.uint8))
    _, _, ink_stats, centers = cv2.connectedComponentsWithStats(
        (texture >= 19).astype(np.uint8), connectivity=8
    )
    glyph = (ink_stats[1:, 3] >= 5) & (ink_stats[1:, 3] <= max(18, min(height, width) * 0.1))
    glyph &= (ink_stats[1:, 4] >= 7) & (
        ink_stats[1:, 2] <= np.minimum(width * 0.25, 9 * ink_stats[1:, 3])
    )
    centers = np.rint(centers[1:][glyph]).astype(int)
    centers[:, 0] = np.minimum(centers[:, 0], width - 1)
    centers[:, 1] = np.minimum(centers[:, 1], height - 1)
    component_heights = ink_stats[1:, 3][glyph]
    by_region = labels[centers[:, 1], centers[:, 0]]
    scores = []
    for region in range(1, n):
        fraction = stats[region, 4] / gray.size
        if fraction < 0.035:
            continue
        is_inside = by_region == region
        body_count = int(np.count_nonzero(is_inside))
        vertical_coverage = len(np.unique(centers[is_inside, 1] // max(1, height // 14)))
        score = body_count * (0.5 + 0.5 * vertical_coverage / 14) + 35 * fraction
        scores.append((float(score), float(fraction), region))
    if not scores:
        paper = np.ones(gray.shape, bool)
        selected_heights = component_heights
        region_status = "no_supported_boundary"
    else:
        _, _, best = max(scores)
        paper = ndimage.binary_fill_holes(labels == best)
        median_b = np.median(b[paper])
        cool = paper & (b <= median_b + 7)
        if 0.66 * paper.sum() <= cool.sum() < 0.985 * paper.sum():
            restricted = cv2.morphologyEx(cool.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
            _, components, component_stats, _ = cv2.connectedComponentsWithStats(
                restricted, connectivity=8
            )
            largest = 1 + int(component_stats[1:, 4].argmax())
            if component_stats[largest, 4] >= 0.66 * paper.sum():
                paper = ndimage.binary_fill_holes(components == largest)
        selected_heights = component_heights[by_region == best]
        region_status = "paper_candidate"
        if paper.mean() > 0.975:
            paper = np.ones(gray.shape, bool)
            region_status = "whole_frame"
    char_height = (
        float(np.quantile(selected_heights, 0.8))
        if len(selected_heights)
        else min(height, width) / 32
    )
    char_height = max(8.0, char_height)
    smooth = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((window, window), np.uint8))
    q10, q90 = np.percentile(smooth[paper], [10, 90])
    metrics = {
        "paper_probe": region_status,
        "paper_candidates": len(scores),
        "outside_fraction": float(1 - paper.mean()),
        "background_spread": float(q90 - q10),
        "body_candidates": int(len(selected_heights)),
        "probe_char_height": char_height,
    }
    return (paper, char_height, metrics)


def scanner_refine_paper(rgb, paper, char_height):
    """Cho phép biên mềm, kể cả vùng giấy mở ra ngoài khung hình."""
    if paper.all():
        return (paper, "whole_frame")
    radius = max(2, min(12, round(0.25 * char_height)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)
    inside = cv2.erode(paper.astype(np.uint8), kernel).astype(bool)
    outside = ~cv2.dilate(paper.astype(np.uint8), kernel).astype(bool)
    if inside.sum() < 20 or outside.sum() < 20:
        return (paper, "insufficient_seeds")
    labels = np.where(paper, cv2.GC_PR_FGD, cv2.GC_PR_BGD).astype(np.uint8)
    labels[inside] = cv2.GC_FGD
    labels[outside] = cv2.GC_BGD
    try:
        cv2.setRNGSeed(0)
        cv2.grabCut(
            np.ascontiguousarray(rgb),
            labels,
            None,
            np.zeros((1, 65)),
            np.zeros((1, 65)),
            1,
            cv2.GC_INIT_WITH_MASK,
        )
    except cv2.error:
        return (paper, "grabcut_failed")
    refined = ndimage.binary_fill_holes(labels & 1 != 0)
    if np.count_nonzero(refined & paper) < 0.98 * paper.sum():
        return (paper, "boundary_loss_rejected")
    return (paper | refined, "grabcut")


# Cân bằng nền và xác định nét
def scanner_correct_background(rgb, paper, char_height):
    """Ước lượng nền từ pixel giấy rồi hiệu chỉnh từng kênh bằng phép chia."""
    height, width = paper.shape
    step = max(22, round(0.95 * char_height))
    rows = max(2, math.ceil(height / step))
    columns = max(2, math.ceil(width / step))
    grid = np.zeros((rows, columns, 3), np.float32)
    valid = np.zeros((rows, columns), bool)
    radius = max(3, round(0.7 * step))
    for row in range(rows):
        y = int((row + 0.5) * height / rows)
        for column in range(columns):
            x = int((column + 0.5) * width / columns)
            region = np.s_[max(0, y - radius) : y + radius + 1, max(0, x - radius) : x + radius + 1]
            samples = rgb[region][paper[region]]
            if len(samples):
                rank = round(0.66 * (len(samples) - 1))
                grid[row, column] = np.partition(samples, rank, axis=0)[rank]
                valid[row, column] = True
    nearest = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    grid = grid[tuple(nearest)]
    background = cv2.morphologyEx(grid, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    background = cv2.GaussianBlur(background, (3, 3), 0.65)
    background = cv2.resize(background, (width, height), interpolation=cv2.INTER_LINEAR)
    corrected = np.minimum(
        255, np.rint(255.0 * rgb.astype(np.float32) / np.maximum(background, 16))
    ).astype(np.uint8)
    corrected[~paper] = 255
    red, green, blue = cv2.split(background - rgb)
    return (
        cv2.cvtColor(corrected, cv2.COLOR_RGB2GRAY),
        0.65 * red + 0.35 * green - blue,
        0.299 * red + 0.587 * green + 0.114 * blue,
    )


def scanner_ink_evidence(gray, paper, blue_vote, contrast, char_height, config):
    if config.binarizer == "otsu":
        threshold, _ = cv2.threshold(gray[paper], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        retained = paper & (gray <= threshold) & (contrast >= 4)
        return (retained, retained.copy(), {"otsu_threshold": float(threshold)})
    width = scanner_odd(config.sauvola_window_chars * char_height, 9)
    values = gray.astype(np.float32)
    mean = cv2.boxFilter(values, -1, (width, width), borderType=cv2.BORDER_REFLECT_101)
    square_mean = cv2.boxFilter(
        values * values, -1, (width, width), borderType=cv2.BORDER_REFLECT_101
    )
    spread = np.sqrt(np.maximum(0, square_mean - mean * mean))
    local_range = spread / 128.0 - 1
    strong = (values < mean * (1 + config.sauvola_k * local_range)) & (contrast >= 10)
    weak = (values < mean * (1 + 0.055 * local_range)) & (contrast >= 6)
    if config.use_color:
        strong |= (blue_vote >= 12) & (contrast >= 13)
        weak |= (blue_vote >= 6) & (contrast >= 7)
    stroke_window = scanner_odd(0.32 * char_height, 7)
    narrow_darkness = cv2.morphologyEx(
        gray, cv2.MORPH_BLACKHAT, np.ones((stroke_window, stroke_window), np.uint8)
    )
    strong &= narrow_darkness >= 9
    weak &= narrow_darkness >= 6
    return (
        paper & strong,
        paper & (weak | strong),
        {"sauvola_window": width, "sauvola_r": 128, "weak_k": 0.055},
    )


def scanner_keep_ink(strong, weak, paper, contrast, blue_vote, char_height):
    """Khôi phục nét yếu được nâng đỡ bởi thân chữ hoặc dấu lân cận."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        weak.astype(np.uint8), connectivity=8
    )
    if count <= 1:
        return (
            weak,
            {
                "weak_components": 0,
                "discarded_components": 0,
                "reinstated_components": 0,
                "punctuation_restored": 0,
            },
        )
    widths, heights, areas = (stats[:, 2], stats[:, 3], stats[:, 4])
    votes = np.bincount(labels[strong], minlength=count)
    fill = areas / np.maximum(1.0, widths.astype(float) * heights)
    distances_inside = cv2.distanceTransform(weak.astype(np.uint8), cv2.DIST_L2, 5)
    thick_pixels = np.bincount(
        labels[weak & (distances_inside > max(4.0, 0.2 * char_height))], minlength=count
    )
    thick = (
        (np.minimum(widths, heights) > 1.1 * char_height)
        & (fill > 0.24)
        & (thick_pixels >= 0.18 * areas)
    )
    margin_width = scanner_odd(max(13.0, 0.6 * char_height))
    edge = paper & ~cv2.erode(
        paper.astype(np.uint8), np.ones((margin_width, margin_width), np.uint8)
    ).astype(bool)
    nearby = np.bincount(labels[weak & edge], minlength=count)
    long = (np.maximum(widths, heights) >= 1.7 * char_height) | (areas >= 0.55 * char_height**2)
    artifact = thick | long & (nearby >= 0.52 * areas)
    plausible = ~artifact & (areas >= 2)
    plausible[0] = False
    seed = plausible & (votes >= np.maximum(1, np.ceil(0.035 * areas)))
    body = seed & (heights >= 0.28 * char_height) & (areas >= max(4, 0.026 * char_height**2))
    body[0] = False
    keep = body.copy()
    if body.any():
        distances = cv2.distanceTransform((~body[labels]).astype(np.uint8), cv2.DIST_L2, 5)
        close_ids = (
            np.bincount(labels[weak & (distances <= 0.72 * char_height)], minlength=count) > 0
        )
        centered_mark = (
            (heights <= 0.95 * char_height)
            & (widths <= 1.4 * char_height)
            & (areas <= 0.35 * char_height**2)
        )
        strong_support = votes > 0
        blue_support = np.bincount(labels[weak & (blue_vote >= 8)], minlength=count) > 0
        contrast_support = np.bincount(labels[weak & (contrast >= 13)], minlength=count) > 0
        keep |= (
            ~artifact
            & close_ids
            & centered_mark
            & (strong_support | blue_support | contrast_support)
        )
        weak_body = plausible & close_ids & (heights >= 0.28 * char_height)
        keep |= weak_body & (votes > 0)
    admissible = seed & ~artifact
    keep |= (
        admissible
        & (heights >= 0.23 * char_height)
        & (votes >= np.maximum(2, np.ceil(0.24 * areas)))
    )
    keep[0] = False
    if not keep.any() and admissible.any():
        keep = admissible
    punctuation_restored = 0
    if keep.any():
        frame_ink = weak & (labels > 0)
        frame_ink[1:-1, 1:-1] = False
        border_ids = np.bincount(labels[frame_ink], minlength=count) > 0
        flat_frame_edge = border_ids & (widths > 6 * char_height) & (heights < 0.45 * char_height)
        at_horizontal_edge = (stats[:, 1] <= 1) | (stats[:, 1] + heights >= weak.shape[0] - 1)
        look_like_strip = at_horizontal_edge & (widths > 5 * char_height) & (widths > 4 * heights)
        look_like_strip[0] = False
        for identifier in np.flatnonzero(look_like_strip):
            x0, y0, width, height, _ = stats[identifier]
            yy, xx = np.nonzero(labels[y0 : y0 + height, x0 : x0 + width] == identifier)
            slope, offset = np.polyfit(xx, yy, 1)
            residual = np.abs(yy - (slope * xx + offset))
            if np.quantile(residual, 0.9) <= max(2.0, 0.26 * char_height):
                flat_frame_edge[identifier] = True
        keep &= ~flat_frame_edge
        minimum_anchor_contrast = max(24, 0.53 * float(np.quantile(contrast[strong], 0.9)))
        dark_votes = np.bincount(
            labels[strong & (contrast >= minimum_anchor_contrast)], minlength=count
        )
        reliable = dark_votes >= np.maximum(2, np.ceil(0.08 * areas))
        core_ids = body & (heights >= 0.34 * char_height) & (heights <= 2.9 * char_height)
        core_ids &= (
            reliable & (widths <= 12 * char_height) & (nearby < 0.42 * areas) & ~flat_frame_edge
        )
        centers = np.column_stack((stats[:, 0] + widths // 2, stats[:, 1] + heights // 2))
        x = np.minimum(centers[:, 0], weak.shape[1] - 1)
        y = np.minimum(centers[:, 1], weak.shape[0] - 1)
        dot = np.zeros(weak.shape, np.float32)
        np.add.at(dot, (y[core_ids], x[core_ids]), 1)
        kernel = (scanner_odd(8 * char_height), scanner_odd(1.7 * char_height))
        peers = cv2.boxFilter(dot, -1, kernel, normalize=False, borderType=cv2.BORDER_CONSTANT)
        anchors = core_ids & (peers[y, x] >= 2)
        if np.count_nonzero(anchors) >= 4:
            context_kernel = (scanner_odd(4.0 * char_height), scanner_odd(5.0 * char_height))
            supporting = cv2.dilate(
                anchors[labels].astype(np.uint8), np.ones(context_kernel[::-1], np.uint8)
            ).astype(bool)
            contextual = np.bincount(labels[weak & supporting], minlength=count) > 0
            mark_kernel = (scanner_odd(1.3 * char_height), scanner_odd(2.3 * char_height))
            mark_support = cv2.dilate(
                anchors[labels].astype(np.uint8), np.ones(mark_kernel, np.uint8)
            ).astype(bool)
            contextual_mark = np.bincount(labels[weak & mark_support], minlength=count) > 0
            edge_fragment = (nearby >= 0.67 * areas) & (
                np.minimum(widths, heights) < 0.22 * char_height
            )
            supported = (
                (contextual & reliable | contextual_mark) & ~edge_fragment & ~flat_frame_edge
            )
            word_candidates = keep & body & reliable & ~supported & (nearby < 0.42 * areas)
            word_candidates &= (heights >= 0.65 * char_height) & (heights <= 5.0 * char_height)
            word_candidates &= (widths >= 0.75 * char_height) & (widths <= 10 * char_height)
            word_candidates &= (dark_votes >= np.ceil(0.2 * areas)) & (
                areas >= 0.12 * char_height**2
            )
            short_word = word_candidates.copy()
            anchor_columns = anchors[labels].any(axis=0, keepdims=True).astype(np.uint8)
            column_support = cv2.dilate(
                anchor_columns, np.ones((1, scanner_odd(6.0 * char_height)), np.uint8)
            )[0]
            if short_word.any():
                writing = (keep & supported & reliable)[labels].astype(np.uint8)
                row_window = (scanner_odd(1.9 * char_height), scanner_odd(8.0 * char_height))
                near_writing = cv2.dilate(writing, np.ones(row_window, np.uint8)) != 0
                neighbor_ids = np.bincount(labels[weak & near_writing], minlength=count) > 0
                short_word &= (column_support[x] != 0) | neighbor_ids
            if short_word.any():
                if np.any(word_candidates & ~short_word):
                    word_window = (scanner_odd(0.9 * char_height), scanner_odd(2.0 * char_height))
                    near_word = cv2.dilate(
                        short_word[labels].astype(np.uint8), np.ones(word_window, np.uint8)
                    ).astype(bool)
                    neighbors = np.bincount(labels[weak & near_word], minlength=count) > 0
                    short_word |= word_candidates & neighbors
                radius = scanner_odd(1.1 * char_height)
                support = (
                    cv2.dilate(
                        short_word[labels].astype(np.uint8), np.ones((radius, radius), np.uint8)
                    )
                    != 0
                )
                adjacent = np.bincount(labels[weak & support], minlength=count) > 0
                compact = (widths <= 1.35 * char_height) & (heights <= 0.85 * char_height)
                supported |= short_word | adjacent & compact & ~edge_fragment
            keep &= supported
        writing_components = keep & reliable & (heights >= max(5, 0.16 * char_height))
        writing_components &= areas >= max(10, 0.013 * char_height**2)
        right = (stats[:, 0] + widths)[writing_components]
        lower_start = (stats[:, 1] + 0.3 * heights)[writing_components]
        lower_end = (stats[:, 1] + heights)[writing_components] + 0.28 * char_height
        small_mark = (np.maximum(widths, heights) <= max(6, 0.35 * char_height)) & (areas >= 3)
        small_mark &= (fill >= 0.32) & (dark_votes >= np.maximum(2, np.ceil(0.22 * areas)))
        candidates = small_mark & ~keep & seed & ~flat_frame_edge & (nearby < 0.42 * areas)
        for identifier in np.flatnonzero(candidates):
            left, top, _, height, _ = stats[identifier]
            horizontal_gap = left - right
            center_y = top + 0.5 * height
            same_baseline = (center_y >= lower_start) & (center_y <= lower_end)
            if np.any(
                same_baseline & (horizontal_gap >= 0) & (horizontal_gap <= 1.4 * char_height)
            ):
                keep[identifier] = True
                punctuation_restored += 1
    return (
        keep[labels],
        {
            "weak_components": count - 1,
            "discarded_components": int(count - 1 - keep.sum()),
            "reinstated_components": int(np.count_nonzero(keep & (votes == 0))),
            "punctuation_restored": punctuation_restored,
        },
    )


# Kiểm hình học theo hướng dòng
def scanner_line_evidence(mask, char_height):
    """Hồi quy hướng từ nhiều hàng, chỉ dùng các dải có đủ hỗ trợ theo x."""
    box = scanner_bbox(mask)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    cropped = mask[y0:y1, x0:x1]
    probe = scanner_reduce(cropped.astype(np.uint8) * 255, 560)
    sy, sx = np.asarray(probe.shape) / np.asarray(cropped.shape)
    height, width = probe.shape
    scale_height = max(2.0, char_height * sy)
    pad = int(np.ceil(0.21 * width)) + 2
    center = (width - 1) / 2
    best = None
    for degrees in range(-20, 21):
        slope = float(np.tan(np.deg2rad(degrees)))
        shear = np.array([[1, 0, 0], [-slope, 1, pad + slope * center]])
        sheared = cv2.warpAffine(probe, shear, (width, height + 2 * pad), flags=cv2.INTER_LINEAR)
        profile = gaussian_filter1d(sheared.mean(axis=1), max(0.7, 0.12 * scale_height))
        score = float(profile @ profile)
        if best is None or (score, -abs(degrees)) > best[:2]:
            best = (score, -abs(degrees), slope, profile, sheared)
    _, _, slope, profile, sheared = best
    peaks, _ = find_peaks(
        profile, distance=max(2, 0.9 * scale_height), prominence=max(1.0, 0.1 * profile.max())
    )
    tracks = []
    for peak in peaks:
        radius = round(0.48 * scale_height)
        lower, upper = (max(0, peak - radius), min(len(profile), peak + radius + 1))
        points = []
        for left, right in zip(
            np.linspace(0, width, 11, dtype=int)[:-1], np.linspace(0, width, 11, dtype=int)[1:]
        ):
            yy, xx = np.nonzero(sheared[lower:upper, left:right] > 90)
            if len(yy) < scale_height:
                continue
            x = float(np.median(xx)) + left
            y = float(np.median(yy)) + lower - pad + slope * (x - center)
            points.append(((x + 0.5) / sx - 0.5 + x0, (y + 0.5) / sy - 0.5 + y0))
        if len(points) >= 4 and np.ptp(np.asarray(points)[:, 0]) >= max(
            4 * char_height, 0.32 * (x1 - x0)
        ):
            tracks.append(np.asarray(points, np.float32))
    return tracks


def scanner_fit_line(points):
    vx, vy, x, y = cv2.fitLine(
        np.asarray(points, np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01
    ).ravel()
    return np.asarray([-vy, vx, vy * x - vx * y], dtype=float)


def scanner_line_angles(tracks, matrix):
    angles = []
    for track in tracks:
        mapped = cv2.perspectiveTransform(track[:, None, :], matrix)[:, 0]
        a, b, _ = scanner_fit_line(mapped)
        angles.append(float(np.rad2deg(np.arctan2(-a * np.sign(b), abs(b)))))
    return np.asarray(angles)


def scanner_perspective(paper, tracks, char_height):
    if paper.all() or len(tracks) < 3:
        return None
    height, width = paper.shape
    line_centers = np.asarray([np.median(track[:, 1]) for track in tracks])
    top, bottom = (tracks[int(line_centers.argmin())], tracks[int(line_centers.argmax())])
    if np.ptp(line_centers) < 3 * char_height:
        return None
    sides = []
    for side in (0, -1):
        points = []
        for y in np.linspace(
            max(1, line_centers.min()), min(height - 2, line_centers.max()), 25
        ).astype(int):
            xs = np.flatnonzero(paper[y])
            if len(xs) and 2 <= xs[side] <= width - 3:
                points.append((xs[side], y))
        if len(points) < 14 or np.ptp(np.asarray(points)[:, 1]) < 0.6 * np.ptp(line_centers):
            return None
        line = scanner_fit_line(points)
        if abs(line[0]) < 0.86 or np.median(np.abs(np.asarray(points) @ line[:2] + line[2])) > max(
            3, 0.32 * char_height
        ):
            return None
        sides.append(line)
    top_line, bottom_line = (scanner_fit_line(top), scanner_fit_line(bottom))
    intersections = np.array(
        [
            np.cross(a, b)
            for a, b in (
                (top_line, sides[0]),
                (top_line, sides[1]),
                (bottom_line, sides[1]),
                (bottom_line, sides[0]),
            )
        ]
    )
    if np.any(np.abs(intersections[:, 2]) < 0.5):
        return None
    corners = (intersections[:, :2] / intersections[:, 2:]).astype(np.float32)
    if not cv2.isContourConvex(corners) or cv2.contourArea(corners, oriented=True) <= 0:
        return None
    edges = np.linalg.norm(corners - np.roll(corners, -1, axis=0), axis=1)
    if (
        edges.min() < 2 * char_height
        or max(edges[0] / edges[2], edges[2] / edges[0], edges[1] / edges[3], edges[3] / edges[1])
        > 1.55
    ):
        return None
    target_width, target_height = (edges[[0, 2]].mean(), edges[[1, 3]].mean())
    target = np.float32(
        [[0, 0], [target_width, 0], [target_width, target_height], [0, target_height]]
    )
    return cv2.getPerspectiveTransform(corners, target)


def scanner_geometry(mask, paper, char_height, config):
    identity = np.eye(3)
    tracks = scanner_line_evidence(mask, char_height)
    if len(tracks) < 2:
        return (identity, "identity", {"supported_lines": len(tracks)})
    angles = scanner_line_angles(tracks, identity)
    angle = float(np.median(angles))
    metrics = {
        "supported_lines": len(tracks),
        "median_line_angle": angle,
        "line_angles_before": angles.tolist(),
    }
    height, width = mask.shape
    rotation = identity
    if abs(angle) >= config.minimum_rotation and np.median(np.abs(angles - angle)) <= 3.0:
        rotation = np.vstack(
            (cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1), [0, 0, 1])
        )
    candidates = [
        ("perspective", scanner_perspective(paper, tracks, char_height)),
        ("rotation", rotation),
    ]
    before = float(np.mean(np.abs(angles)))
    for name, matrix in candidates:
        if matrix is None or not np.isfinite(matrix).all() or np.allclose(matrix, identity):
            continue
        candidate = scanner_line_angles(tracks, matrix)
        improvement = before - float(np.mean(np.abs(candidate)))
        required = max(0.22, 0.14 * before)
        if name == "perspective":
            rotation_error = np.mean(np.abs(scanner_line_angles(tracks, rotation)))
            required = max(required, before - rotation_error + 0.2)
        if improvement >= required:
            metrics["line_angles_after"] = candidate.tolist()
            return (matrix, name, metrics)
    return (identity, "identity", metrics)


def scanner_warp(gray, mask, matrix, geometry):
    """Tạo canvas đủ chứa ảnh, kiểm tỉ lệ và độ phủ mực trước khi chấp nhận."""
    if geometry == "identity":
        return (gray, mask, matrix, geometry)
    height, width = mask.shape
    corners = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    homogeneous = np.column_stack((corners, np.ones(4))) @ matrix.T
    scale = homogeneous[:, 2]
    original = (gray, mask, np.eye(3), "identity_warp_rejected")
    if np.any(scale * scale[0] <= 0) or np.min(np.abs(scale)) < 0.1 * np.max(np.abs(scale)):
        return original
    warped_corners = (homogeneous[:, :2] / scale[:, None]).astype(np.float32)
    area_ratio = cv2.contourArea(warped_corners, oriented=True) / ((height - 1) * (width - 1))
    minimum, maximum = (np.floor(warped_corners.min(axis=0)), np.ceil(warped_corners.max(axis=0)))
    shape = tuple((int(size) for size in maximum - minimum + 3))
    if not 0.64 <= area_ratio <= 1.65 or math.prod(shape) > 2.15 * mask.size:
        return original
    translation = np.array([[1, 0, 1 - minimum[0]], [0, 1, 1 - minimum[1]], [0, 0, 1]])
    shifted = translation @ matrix
    coverage = cv2.warpPerspective(mask.astype(np.float32), shifted, shape, flags=cv2.INTER_LINEAR)
    mapped_mask = coverage >= 0.25
    recovered = cv2.warpPerspective(
        mapped_mask.astype(np.uint8),
        np.linalg.inv(shifted),
        (width, height),
        flags=cv2.INTER_NEAREST,
    ).astype(bool)
    count, labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    components = np.bincount(labels[mask & recovered], minlength=count)
    if np.any(components[1:] == 0) or np.count_nonzero(mask & recovered) < 0.98 * mask.sum():
        return original
    image = cv2.warpPerspective(gray, shifted, shape, flags=cv2.INTER_LINEAR, borderValue=255)
    return (np.where(mapped_mask, image, 255), mapped_mask, shifted, geometry)


def scanner_trim_working(gray, mask, matrix, char_height):
    box = scanner_bbox(mask)
    if box is None:
        return (gray, mask, matrix)
    x0, y0, x1, y1 = box
    pad = max(8, round(0.25 * char_height))
    left, top = (max(0, x0 - pad), max(0, y0 - pad))
    right, bottom = (min(mask.shape[1], x1 + pad), min(mask.shape[0], y1 + pad))
    trim = np.array([[1, 0, -left], [0, 1, -top], [0, 0, 1]])
    return (gray[top:bottom, left:right].copy(), mask[top:bottom, left:right].copy(), trim @ matrix)


# Chọn mức tiền xử lý
def preprocess_document(image, config=DocumentScannerConfig(), *, mode="auto"):
    """Trả ảnh dùng cho Native, ảnh mức xám, mask và tọa độ ánh xạ."""
    if mode not in {"legacy", "auto", "scanner"}:
        raise ValueError("Chọn chế độ tiền xử lý legacy, auto hoặc scanner.")
    if not isinstance(image, Image.Image) or "viethandocr_source" not in image.info:
        image = decode_image(image)
    rgb = np.asarray(image)
    gray = np.asarray(image.convert("L"))
    matrix = np.eye(3)
    metrics = {}
    review_flags = []
    reasons = []
    if mode != "legacy":
        probe = scanner_reduce(rgb, config.probe_long_side)
        paper_probe, probe_char_height, metrics = scanner_paper_probe(probe)
        if metrics["outside_fraction"] >= config.outside_fraction:
            reasons.append("outside_paper")
        if metrics["background_spread"] >= config.background_spread:
            reasons.append("uneven_lighting")
        if not reasons and config.rectify:
            probe_gray = cv2.cvtColor(probe, cv2.COLOR_RGB2GRAY)
            probe_ink, _ = binarize(probe_gray)
            probe_tracks = scanner_line_evidence(probe_ink & paper_probe, probe_char_height)
            angles = scanner_line_angles(probe_tracks, matrix)
            if (
                len(angles) >= 3
                and abs(np.median(angles)) >= 3.5
                and (np.median(abs(angles - np.median(angles))) <= 2.0)
            ):
                reasons.append("coherent_skew")
    route = "scanner" if mode == "scanner" or (mode == "auto" and reasons) else "legacy"
    geometry = "identity"
    if route == "legacy":
        foreground, threshold = binarize(gray)
        source_foreground = foreground
        native_gray = gray
        clean_gray = np.where(foreground, gray, 255)
        source_paper = np.ones(gray.shape, bool)
        discarded = np.zeros(gray.shape, bool)
        reasons = [
            "requested_legacy" if mode == "legacy" else "background_and_alignment_within_limits"
        ]
    else:
        if mode == "scanner":
            reasons.insert(0, "requested_scanner")
        refined, metrics["paper_refinement"] = scanner_refine_paper(
            probe, paper_probe, probe_char_height
        )
        source_paper = cv2.resize(
            refined.astype(np.uint8), image.size, interpolation=cv2.INTER_NEAREST
        ).astype(bool)
        char_height = probe_char_height * gray.shape[0] / probe.shape[0]
        corrected, blue, contrast = scanner_correct_background(rgb, source_paper, char_height)
        strong, weak, threshold_details = scanner_ink_evidence(
            corrected, source_paper, blue, contrast, char_height, config
        )
        if config.binarizer == "otsu":
            source_foreground = strong
        else:
            source_foreground, component_metrics = scanner_keep_ink(
                strong, weak, source_paper, contrast, blue, char_height
            )
            metrics.update(component_metrics)
            if np.count_nonzero(strong & ~source_foreground) > 0.1 * max(1, int(strong.sum())):
                review_flags.append("discarded_strong_candidates")
        discarded = weak & ~source_foreground
        if discarded.sum() > 0.25 * max(1, int(source_foreground.sum())):
            review_flags.append("ambiguous_faint_ink")
        if metrics["paper_probe"] == "no_supported_boundary":
            review_flags.append("paper_boundary_uncertain")
        clean_gray = np.where(source_foreground, corrected, 255)
        foreground = source_foreground
        metrics.update(threshold_details, char_height=char_height)
        if config.rectify and foreground.any():
            matrix, geometry, geometry_metrics = scanner_geometry(
                foreground, source_paper, char_height, config
            )
            metrics.update(geometry_metrics)
            clean_gray, foreground, matrix, geometry = scanner_warp(
                clean_gray, foreground, matrix, geometry
            )
            if geometry == "identity_warp_rejected":
                review_flags.append("rectification_rejected")
        clean_gray, foreground, matrix = scanner_trim_working(
            clean_gray, foreground, matrix, char_height
        )
        native_gray = np.where(foreground, 0, 255).astype(np.uint8)
        threshold = 0.0
    if (
        source_foreground[0, :].any()
        or source_foreground[-1, :].any()
        or source_foreground[:, 0].any()
        or source_foreground[:, -1].any()
    ):
        review_flags.append("ink_at_image_edge")
    ink_image, ink_mask, ink_bbox = scanner_mask_crop(clean_gray, foreground)
    return {
        "mode": mode,
        "route": route,
        "reasons": reasons,
        "geometry": geometry,
        "metrics": metrics,
        "review_flags": review_flags,
        "configuration": asdict(config),
        "threshold": threshold,
        "source_to_working": matrix,
        "source_foreground": source_foreground,
        "source_paper": source_paper,
        "source_discarded": discarded,
        "native_gray": native_gray,
        "clean_gray": clean_gray,
        "foreground": foreground,
        "ink_image": ink_image,
        "ink_mask": ink_mask,
        "ink_bbox": ink_bbox,
    }


# Đo chi phí và nạp ML_s44
MODEL_FILES = ("model_config.json", "ml_s44_fp16.pth")
VGG19_LAYERS = (
    64,
    64,
    "P",
    128,
    128,
    "P",
    256,
    256,
    256,
    256,
    "P",
    512,
    512,
    512,
    512,
    "P",
    512,
    512,
    512,
    512,
    "P",
)
PAD, SOS, EOS, MASK = (0, 1, 2, 3)
COMPUTE_STAGES = ("preprocess", "native", "v2c", "tensor", "encoder", "decoder", "composition")


def model_candidates():
    explicit_directory = os.environ.get("VIETHANDOCR_MODEL_DIR")
    if explicit_directory:
        return [Path(explicit_directory).expanduser().resolve()]
    if Path("/kaggle/input").is_dir():
        return sorted({path.parent for path in Path("/kaggle/input").rglob("model_config.json")})
    candidates = []
    script_file = globals().get("__file__")
    if script_file:
        candidates.append(Path(script_file).resolve().parent)
        candidates.append(Path(script_file).resolve().parent / "model")
        candidates.append(
            Path(script_file).resolve().parent.parent
            / "artifacts/research/final_pipeline_decision_20261106/model"
        )
    candidates.append(Path.cwd())
    candidates.append(Path.cwd() / "model")
    candidates.append(Path.cwd() / "artifacts/research/final_pipeline_decision_20261106/model")
    return list(dict.fromkeys(candidates))


def resolve_model_files(progress=None):
    for folder in model_candidates():
        files = {filename: folder / filename for filename in MODEL_FILES}
        if not any((path.exists() for path in files.values())):
            continue
        missing = [filename for filename, path in files.items() if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"Thiếu tài nguyên trong {folder}: {', '.join(missing)}. Đặt hai tệp ML_s44 trong cùng thư mục."
            )
        if progress:
            for path in files.values():
                progress(f"Tài nguyên mô hình: {path}")
        return files
    raise FileNotFoundError(
        "Chưa có ML_s44. Gắn Kaggle Dataset chứa model_config.json và ml_s44_fp16.pth cùng thư mục; trên máy tính, đặt hai tệp ngang hàng với file Python hoặc trong thư mục model cạnh file Python, hoặc chỉ định VIETHANDOCR_MODEL_DIR. Chương trình không tự tải mô hình từ Internet."
    )


class ComputeClock:
    def __init__(self, synchronize=lambda: None, timer=time.perf_counter_ns):
        self.synchronize = synchronize
        self.timer = timer
        self.seconds = {}
        self.active = None

    @contextmanager
    def stage(self, name):
        if name not in COMPUTE_STAGES or self.active is not None:
            raise ValueError("Giai đoạn đo không hợp lệ hoặc bị lồng nhau: " + name)
        self.active = name
        self.synchronize()
        start = self.timer()
        try:
            yield
        finally:
            self.synchronize()
            elapsed = (self.timer() - start) / 1000000000
            self.seconds[name] = self.seconds.get(name, 0.0) + elapsed
            self.active = None


class MemoryObservation:
    def __init__(self, device):
        import psutil

        self.device = torch.device(device)
        self.process = psutil.Process()
        self.stop_event = threading.Event()
        self.baseline_rss = self.process.memory_info().rss
        self.peak_rss = self.baseline_rss
        self.sampler = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        while not self.stop_event.wait(0.02):
            self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)

    def start(self):
        if self.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(self.device)
        self.sampler.start()

    def finish(self):
        self.stop_event.set()
        self.sampler.join()
        self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
        result = {
            "rss_baseline_bytes": self.baseline_rss,
            "rss_sampled_peak_bytes": self.peak_rss,
            "rss_sampling_interval_seconds": 0.02,
        }
        if self.device.type == "cuda":
            result.update(
                cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(self.device),
                cuda_peak_reserved_bytes=torch.cuda.max_memory_reserved(self.device),
            )
        return result


class LineRecognizer:
    def __init__(self, progress=None, device=None):
        files = resolve_model_files(progress)
        self.settings = json.loads(files["model_config.json"].read_text(encoding="utf-8"))
        self.device = torch.device(device or ("cuda:0" if torch.cuda.is_available() else "cpu"))
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        cv2.setNumThreads(1)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="enable_nested_tensor")
            self.model = _VietOCR(
                len(self.settings["vocab"]) + 4, self.settings["cnn"], self.settings["transformer"]
            ).float()
        state = torch.load(files["ml_s44_fp16.pth"], map_location="cpu", weights_only=True)
        state = {
            key: value.float() if value.is_floating_point() else value
            for key, value in state.items()
        }
        self.model.load_state_dict(state, strict=True)
        del state
        try:
            self.model = self.model.to(device=self.device, dtype=torch.float32)
        except (RuntimeError, torch.cuda.OutOfMemoryError):
            if self.device.type != "cuda":
                raise
            self.device = torch.device("cpu")
            self.model = self.model.cpu()
            torch.cuda.empty_cache()
            if progress:
                progress("GPU không khả dụng cho mô hình; chuyển sang CPU.")
        self.model.eval().requires_grad_(False)
        self.characters = {
            index + 4: character for index, character in enumerate(self.settings["vocab"])
        }
        self.characters.update({PAD: "<pad>", SOS: "<sos>", EOS: "<eos>", MASK: "*"})

    def synchronize(self):
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)

    def input_array(self, prepared):
        width = math.ceil(int(64 * float(prepared.width) / float(prepared.height)) / 10) * 10
        width = min(max(width, 32), 2048)
        resized = prepared.resize((width, 64), Image.Resampling.LANCZOS)
        array = np.asarray(resized).transpose(2, 0, 1) / 255
        return (array.astype(np.float32), resized)

    def decode(self, memory):
        tokens = [SOS]
        for _ in range(257):
            prefix = torch.tensor(tokens, dtype=torch.long, device=self.device).unsqueeze(1)
            logits = self.model.transformer.forward_decoder(prefix, memory)[0, -1]
            if not bool(torch.isfinite(logits).all()):
                raise RuntimeError("ML_s44 tạo logits không hữu hạn.")
            token = int(logits.argmax())
            tokens.append(token)
            if token == EOS:
                break
        visible = tokens[1:-1] if tokens[-1] == EOS else tokens[1:]
        text = normalize("".join((self.characters[token] for token in visible)))
        return {"text": text, "token_ids": tokens, "ended_with_eos": tokens[-1] == EOS}


def scanner_source_polygon(box, source_to_working):
    x0, y0, x1, y1 = box
    corners = np.float64([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) - 0.5
    mapped = cv2.perspectiveTransform(corners[:, None, :], np.linalg.inv(source_to_working))
    return mapped[:, 0, :].tolist()


def document_line_crops(document, native):
    if native is None:
        return []
    crops = []
    foreground, owners = (document["foreground"], native["labels"])
    for crop in native["crops"]:
        left, top, right, bottom = crop["bbox"]
        region = np.s_[top:bottom, left:right]
        mask = foreground[region] & (owners[region] == crop["line_id"])
        gray, mask, local = scanner_mask_crop(document["clean_gray"][region], mask)
        if local is None:
            continue
        box = [left + local[0], top + local[1], left + local[2], top + local[3]]
        crops.append(
            {
                "line_id": int(crop["line_id"]),
                "image": gray,
                "mask": mask,
                "bbox": box,
                "source_polygon": scanner_source_polygon(box, document["source_to_working"]),
            }
        )
    document["metrics"]["unowned_ink_pixels"] = int(np.count_nonzero(foreground & (owners <= 0)))
    if document["metrics"]["unowned_ink_pixels"]:
        document["review_flags"].append("unowned_ink")
    return crops


def prepare_scanner_line(line, render):
    pixels = line["image"] if render == "gray" else np.where(line["mask"], 0, 255).astype(np.uint8)
    image = Image.fromarray(pixels).convert("RGB")
    width = V2C_WIDTH_PX - 2 * V2C_MARGIN_PX
    height = max(1, round(image.height * width / image.width))
    if height > 4096:
        raise ValueError("Vùng chữ quá cao và hẹp. Hãy xoay ảnh hoặc cắt một dòng ngang.")
    canvas = Image.new("RGB", (V2C_WIDTH_PX, height + 2 * V2C_MARGIN_PX), "white")
    canvas.paste(
        image.resize((width, height), Image.Resampling.LANCZOS), (V2C_MARGIN_PX, V2C_MARGIN_PX)
    )
    info = {
        "method": "v2c_document_mask",
        "render": render,
        "bbox_found": True,
        "bbox": [0, 0, image.width, image.height],
        "source_size": image.size,
        "lr_px": V2C_MARGIN_PX,
        "tb_px": V2C_MARGIN_PX,
        "ref_width": V2C_WIDTH_PX,
        "content_size": (width, height),
        "output_size": canvas.size,
        "background_rgb": [255, 255, 255],
    }
    return (image, canvas, info)


APPLICATION_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def collect_application_images(inputs, *, excluded=()):
    excluded = {Path(path).resolve() for path in excluded}
    files = []
    for source in map(Path, inputs):
        source = source.expanduser().resolve()
        if not source.is_dir():
            files.append(source)
            continue
        for current, directories, names in os.walk(source):
            folder = Path(current)
            directories[:] = [
                name for name in directories if (folder / name).resolve() not in excluded
            ]
            files.extend(
                (
                    folder / name
                    for name in names
                    if Path(name).suffix.lower() in APPLICATION_IMAGE_SUFFIXES
                )
            )
    return sorted(
        {path.resolve() for path in files}, key=lambda path: (str(path).casefold(), str(path))
    )


APPLICATION_DEFAULT_PREPROCESS = "auto"
APPLICATION_AUTO_SCANNER_CONFIG = DocumentScannerConfig(
    **{
        "probe_long_side": 1200,
        "binarizer": "sauvola",
        "sauvola_k": 0.18,
        "sauvola_window_chars": 3.0,
        "use_color": True,
        "rectify": False,
        "line_render": "gray",
        "outside_fraction": 0.055,
        "background_spread": 24.0,
        "minimum_rotation": 1.2,
    }
)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
