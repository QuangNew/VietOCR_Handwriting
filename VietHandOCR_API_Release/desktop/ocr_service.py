"""Local OCR adapter. No torch/model imports until recognition is requested."""

import importlib
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from types import SimpleNamespace

import numpy as np
from PIL import Image


class RecognitionError(RuntimeError):
    pass


class DeviceExecutionError(RecognitionError):
    """A failed accelerator can be retried on another device."""


class RecognitionCancelled(Exception):
    pass


@dataclass(frozen=True)
class OCRSettings:
    weights: str
    device: str = "cpu"
    layout: str = "auto"
    adapter_luid: str | None = None


def split_text_lines(gray: np.ndarray) -> list[np.ndarray]:
    """Projection-based line segmentation for upright, single-column documents.

    Small components are kept so Vietnamese accents survive. This is deliberately
    a line splitter, not a general document-layout or scene-text detector.
    """
    import cv2
    height, width = gray.shape
    scale = min(1.0, 1600 / width)
    small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    _, ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = np.zeros(count, dtype=bool)
    char_heights = []
    for label in range(1, count):
        _, _, component_width, component_height, area = stats[label]
        if area < 3 or component_height < 2:
            continue
        # Remove long page borders and rules from the projection.
        if component_height > small.shape[0] * 0.7 and component_width < 4:
            continue
        if component_width > small.shape[1] * 0.8 and component_height < 4:
            continue
        keep[label] = True
        if component_height >= 5:
            char_heights.append(component_height)
    clean = (keep[labels] * 255).astype(np.uint8)
    if not np.any(clean):
        return []

    typical_height = float(np.percentile(char_heights, 65)) if char_heights else 8.0
    rows = (np.count_nonzero(clean, axis=1) >= max(2, int(small.shape[1] * 0.0015))).astype(np.uint8)
    gap = max(3, int(typical_height * 0.45))
    rows = cv2.morphologyEx(rows[:, None], cv2.MORPH_CLOSE, np.ones((gap, 1), np.uint8)).ravel()
    changes = np.diff(np.pad(rows, (1, 1)).astype(np.int8))
    starts, ends = np.where(changes == 1)[0], np.where(changes == -1)[0]
    spans = [(int(top), int(bottom)) for top, bottom in zip(starts, ends) if bottom - top >= 3]
    lines = []
    for index, (top, bottom) in enumerate(spans):
        occupied = np.where(np.any(clean[top:bottom], axis=0))[0]
        if not len(occupied):
            continue
        pad = max(3, int((bottom - top) * 0.25))
        # Padding ends halfway into a gap, so it cannot include the next line.
        lower_limit = (spans[index - 1][1] + top) // 2 if index else 0
        upper_limit = (bottom + spans[index + 1][0]) // 2 if index + 1 < len(spans) else len(rows)
        y1 = max(lower_limit, top - pad)
        y2 = min(upper_limit, bottom + pad)
        x1, x2 = max(0, int(occupied[0]) - pad), min(small.shape[1], int(occupied[-1]) + pad + 1)
        lines.append(gray[max(0, int(y1 / scale)):min(height, int(y2 / scale)),
                          max(0, int(x1 / scale)):min(width, int(x2 / scale))].copy())
    return lines


class OCRService:
    def __init__(self) -> None:
        self._engine = None
        self._model_key: tuple[str, str, str | None] | None = None
        self.device_id = None

    def load(self, settings: OCRSettings) -> None:
        path = Path(settings.weights).expanduser().resolve()
        if not path.is_file():
            raise RecognitionError(
                "Không tìm thấy file trọng số .pth. Chép file model vào thư mục model/ "
                f"(xem README) hoặc mở 'Cài đặt model' để chọn file khác.\n{path}"
            )
        key = (str(path), settings.device, settings.adapter_luid)
        if self._engine is not None and self._model_key == key:
            return
        try:
            api = importlib.import_module("AI")
            if settings.device.startswith("cuda"):
                torch = importlib.import_module("torch")
                if not torch.cuda.is_available():
                    raise RecognitionError("CUDA chưa khả dụng. Hãy chọn CPU trong Cài đặt model.")
            with warnings.catch_warnings(record=True) as caught:
                if settings.device.startswith("directml:"):
                    from .onnx_directml import DirectMLPredictor
                    predictor = DirectMLPredictor(path, int(settings.device.split(":")[1]),
                                                  adapter_luid=settings.adapter_luid)
                    dip = api.VietOCR_DIP_Pipeline()
                    engine = SimpleNamespace(predictor=predictor, dip=dip,
                                             predict=lambda image: predictor.predict(Image.fromarray(dip.process_image(image))))
                else:
                    engine = api.VietHandOCR(weight_path=str(path), device=settings.device)
            if engine.predictor is None:
                error = getattr(engine, "load_error", None)
                if error is not None:
                    raise RecognitionError(f"Không thể nạp model.\n{error}") from error
                details = str(caught[-1].message) if caught else "Predictor chưa được khởi tạo."
                raise RecognitionError(f"Không thể nạp model.\n{details}")
            self._engine, self._model_key = engine, key
            self.device_id = (f"directml:{engine.predictor.device_index}"
                              if settings.device.startswith("directml:") else settings.device)
        except RecognitionError:
            raise
        except ImportError as exc:
            raise RecognitionError(
                "Thiếu thư viện AI. Hãy dùng Python 3.11 và cài requirements.txt.\n"
                f"{exc}"
            ) from exc
        except Exception as exc:
            raise RecognitionError(f"Không thể nạp model: {exc}") from exc

    def recognize(
        self,
        image: Image.Image,
        settings: OCRSettings,
        cancel: threading.Event,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> str:
        import cv2
        if cancel.is_set():
            raise RecognitionCancelled()
        self.load(settings)
        bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        if settings.layout == "auto":
            gray = self._engine.dip.process_image(bgr)
            if gray is None:
                raise RecognitionError("Không thể tiền xử lý ảnh này.")
            lines = split_text_lines(gray)
        else:
            lines = [bgr]
        if not lines:
            raise RecognitionError("Không tìm thấy dòng chữ. Hãy chụp rõ hơn hoặc thử chế độ Một dòng.")
        results = []
        for index, line in enumerate(lines, 1):
            if cancel.is_set():
                raise RecognitionCancelled()
            if on_progress:
                on_progress(index, len(lines))
            try:
                with warnings.catch_warnings(record=True) as caught:
                    if settings.layout == "auto":
                        # The page already passed through AI.py's DIP pipeline.
                        # Do not deskew/resample every crop a second time.
                        value = self._engine.predictor.predict(Image.fromarray(line))
                    else:
                        value = self._engine.predict(line)
            except Exception as exc:
                if settings.device != "cpu":
                    raise DeviceExecutionError(f"{settings.device}: {type(exc).__name__}: {exc}") from exc
                raise RecognitionError(f"Không nhận diện được dòng {index}/{len(lines)}: {exc}") from exc
            if not value or not value.strip():
                accelerator_warning = next((str(w.message) for w in caught if
                    "Quá trình model nhận diện thất bại" in str(w.message)), None)
                if accelerator_warning and settings.device != "cpu":
                    raise DeviceExecutionError(f"{settings.device}: {accelerator_warning}")
                if settings.layout == 'auto':
                    continue  # An empty border/noise crop must not discard valid lines.
                details = str(caught[-1].message) if caught else "Model không trả về văn bản."
                raise RecognitionError(f"Không nhận diện được dòng {index}/{len(lines)}. {details}")
            results.append(value.strip())
        if not results:
            raise RecognitionError('AI không đọc được chữ trong ảnh. Thử cắt sát vùng chữ hoặc chế độ Một dòng.')
        if cancel.is_set():
            raise RecognitionCancelled()
        return "\n".join(results)
