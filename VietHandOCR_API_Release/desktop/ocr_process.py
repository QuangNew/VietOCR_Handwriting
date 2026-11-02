"""A persistent, cancellable AI process. Tk and PyTorch never share a process."""

import logging
import multiprocessing
import os
import signal
import threading
import time
from pathlib import Path

from .diagnostics import LOG_DIRECTORY, configure_logging
from .ocr_service import OCRService, OCRSettings, RecognitionCancelled, RecognitionError, DeviceExecutionError
from .compute_devices import CPU, ComputeDevice, select_devices, validate_device

logger = logging.getLogger("vietocr_desktop.ocr")


class OCRWorkerStopped(RecognitionError):
    pass


def _serve_ocr(connection, log_directory, engine_factory):
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Parent handles Ctrl+C and cancellation.
    configure_logging(Path(log_directory), worker=True)
    threads = min(2, max(1, (os.cpu_count() or 2) // 2))
    os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(threads))
    service = None
    try:
        while True:
            operation, payload = connection.recv()
            try:
                if service is None:
                    if engine_factory is None:
                        logger.info('AI worker boot: pid=%s phase=import_torch threads=%s', os.getpid(), threads)
                        import cv2
                        cv2.setNumThreads(1)
                        import torch
                        torch.set_num_threads(threads)
                        service = OCRService()
                    else:
                        service = engine_factory()
                if operation == "devices":
                    from .compute_devices import discover_devices
                    connection.send(("devices", discover_devices() if engine_factory is None else [CPU]))
                elif operation == "load":
                    logger.info("Loading model: %s (%s)", payload.weights, payload.device)
                    service.load(payload)
                    connection.send(("loaded", getattr(service, "device_id", payload.device)))
                    logger.info("Model ready")
                elif operation == "recognize":
                    image, settings = payload
                    result = service.recognize(image, settings, threading.Event(),
                                               lambda line, total: connection.send(("progress", (line, total))))
                    connection.send(("result", result))
                else:
                    raise ValueError("Unknown OCR operation")
            except Exception as exc:
                logger.exception("OCR %s failed", operation)
                connection.send(("device_error" if isinstance(exc, DeviceExecutionError) else "error",
                                 str(exc)[:3000] or type(exc).__name__))
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


class OCRProcessService:
    def __init__(self, *, log_directory: Path = LOG_DIRECTORY, load_timeout: float = 180,
                 recognition_timeout: float = 180, engine_factory=None):
        self.log_directory = Path(log_directory)
        self.load_timeout, self.recognition_timeout = load_timeout, recognition_timeout
        self._engine_factory = engine_factory
        self._context = multiprocessing.get_context("spawn")
        self._lock = threading.RLock()
        self._process = self._connection = None
        self._model_key = None
        self._selection_key = None
        self._candidates = []
        self._candidate_index = 0
        self.device_info = None
        self._closing = threading.Event()
        self.closed = threading.Event()

    def _start_worker(self):
        if self._process is not None and self._process.is_alive():
            return
        self._dispose_worker()
        parent, child = self._context.Pipe()
        process = self._context.Process(target=_serve_ocr, args=(child, str(self.log_directory), self._engine_factory),
                                        name="VietOCR-AI", daemon=True)
        try:
            process.start()
        except Exception:
            parent.close()
            child.close()
            process.close()
            raise
        child.close()
        self._connection, self._process = parent, process
        logger.info("Started AI process pid=%s", process.pid)

    def _dispose_worker(self):
        process, connection = self._process, self._connection
        self._process = self._connection = self._model_key = None
        self.device_info = None
        if connection is not None:
            connection.close()
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=0.75)
            if process.is_alive():
                process.kill()
                process.join(timeout=0.75)
            if not process.is_alive():
                process.close()

    def _check_cancelled(self, cancel):
        if self._closing.is_set() or (cancel is not None and cancel.is_set()):
            self._dispose_worker()
            raise RecognitionCancelled()

    def _request(self, operation, payload, cancel, timeout, on_progress=None):
        self._check_cancelled(cancel)
        try:
            self._start_worker()
        except Exception as exc:
            logger.exception("Could not start AI process")
            self._dispose_worker()
            raise RecognitionError(
                "Không thể khởi động tiến trình AI. Đóng bớt ứng dụng rồi thử lại.\n"
                f"Chi tiết: {self.log_directory / 'vietocr.log'}"
            ) from exc
        last_activity = time.monotonic()
        try:
            self._connection.send((operation, payload))
            while True:
                self._check_cancelled(cancel)
                if self._connection.poll(0.05):
                    kind, value = self._connection.recv()
                    self._check_cancelled(cancel)
                    if kind == "error":
                        raise RecognitionError(value)
                    if kind == "device_error":
                        raise DeviceExecutionError(value)
                    if kind == "progress" and operation == "recognize":
                        last_activity = time.monotonic()
                        if on_progress:
                            on_progress(*value)
                    elif kind == {"load": "loaded", "recognize": "result", "devices": "devices"}[operation]:
                        return value
                elif not self._process.is_alive():
                    raise EOFError
                if time.monotonic() - last_activity > timeout:
                    self._dispose_worker()
                    action = "Nạp model" if operation == "load" else "Nhận diện"
                    raise OCRWorkerStopped(f"{action} quá {timeout:g} giây không phản hồi. Hãy thử lại hoặc chọn CPU.")
        except (EOFError, BrokenPipeError, OSError) as exc:
            self._check_cancelled(cancel)
            if self._process is not None:
                self._process.join(timeout=0.1)
            code = self._process.exitcode if self._process is not None else None
            hexadecimal = f'0x{code & 0xffffffff:08X}' if code is not None else 'unknown'
            logger.error("AI process stopped unexpectedly, exit=%s", code, exc_info=True)
            self._dispose_worker()
            detail = f" (mã {code}, {hexadecimal}; bước {operation})" if code is not None else ""
            raise OCRWorkerStopped(
                f"Tiến trình AI đã dừng bất thường{detail}. Giao diện vẫn hoạt động; bấm nhận diện để thử lại.\n"
                f"Chi tiết: {self.log_directory / 'ocr-worker.log'} và ocr-crash.log"
            ) from exc
        except MemoryError as exc:
            self._dispose_worker()
            raise RecognitionError("Không đủ bộ nhớ để nhận diện. Thử ảnh nhỏ hơn hoặc đóng bớt ứng dụng rồi thử lại.") from exc
        except Exception:
            # A failed inference may leave CUDA/native state unusable. A callback
            # exception also leaves unread replies in the pipe; reusing it would
            # let the next image receive this request's result.
            self._dispose_worker()
            raise

    def _discover_devices(self, cancel):
        try:
            return self._request("devices", None, cancel, self.load_timeout)
        except RecognitionError:
            logger.exception("GPU discovery failed in isolated worker; trying CPU")
            self._dispose_worker()
            return [CPU]

    def _load_remaining(self, settings, key, cancel):
        while self._candidate_index < len(self._candidates):
            device = self._candidates[self._candidate_index]
            logger.info("Trying compute device: %s | %s | %s", device.id, device.kind, device.name)
            try:
                actual_id = self._request("load", OCRSettings(key[0], device.id, settings.layout, device.adapter_luid), cancel, self.load_timeout)
            except RecognitionError as exc:
                self._dispose_worker()
                self._candidate_index += 1
                logger.warning("Device %s could not load model: %s", device.id, exc)
                if self._candidate_index == len(self._candidates):
                    raise
            else:
                self._model_key = key
                self.device_info = {"id": actual_id or device.id, "name": device.name, "kind": device.kind,
                                    "adapter_luid": device.adapter_luid}
                logger.info("Active compute device: %s | %s", self.device_info["id"], device.name)
                return

    def load(self, settings: OCRSettings, cancel: threading.Event | None = None):
        with self._lock:
            self._check_cancelled(cancel)
            path = Path(settings.weights).expanduser().resolve()
            try:
                stat = path.stat()
            except OSError as exc:
                raise RecognitionError(f"Không tìm thấy file trọng số .pth. Mở Cài đặt model để chọn lại.\n{path}") from exc
            if not path.is_file() or not stat.st_size:
                raise RecognitionError(f"File trọng số rỗng hoặc không hợp lệ. Mở Cài đặt model để chọn lại.\n{path}")
            key = (str(path), settings.device, stat.st_mtime_ns, stat.st_size)
            if self._model_key == key and self._process is not None and self._process.is_alive():
                return
            # Replacing a model first releases its RAM/VRAM, including allocator caches.
            self._dispose_worker()
            validate_device(settings.device)
            if self._selection_key != key or self._candidate_index >= len(self._candidates):
                devices = [CPU] if settings.device == "cpu" else self._discover_devices(cancel)
                self._candidates = select_devices(devices, settings.device)
                self._candidate_index = 0
                self._selection_key = key
            if not self._candidates:
                self._dispose_worker()
                raise RecognitionError(f"Thiết bị {settings.device} chưa khả dụng. Chọn Tự động hoặc CPU; xem log về runtime/driver.")
            self._load_remaining(settings, key, cancel)

    def recognize(self, image, settings: OCRSettings, cancel: threading.Event, on_progress=None):
        with self._lock:
            self.load(settings, cancel)
            key = self._model_key
            while True:
                device = self._candidates[self._candidate_index]
                effective = OCRSettings(settings.weights, device.id, settings.layout, device.adapter_luid)
                try:
                    return self._request("recognize", (image, effective), cancel, self.recognition_timeout, on_progress)
                except (DeviceExecutionError, OCRWorkerStopped) as exc:
                    if settings.device != "auto" or device.kind == "cpu" or self._candidate_index + 1 == len(self._candidates):
                        raise
                    logger.warning("Device %s failed during inference; retrying the whole image on the next device: %s", device.id, exc)
                    self._dispose_worker()
                    self._candidate_index += 1
                    self._load_remaining(settings, key, cancel)

    def close(self):
        if self._closing.is_set():
            return
        self._closing.set()

        def cleanup():
            try:
                with self._lock:
                    self._dispose_worker()
            except Exception:
                logger.exception("Could not release AI process during shutdown")
            finally:
                self.closed.set()

        threading.Thread(target=cleanup, name="VietOCR-AI-close", daemon=True).start()
