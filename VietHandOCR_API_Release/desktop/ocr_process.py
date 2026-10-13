"""A persistent, cancellable AI process. Tk and PyTorch never share a process."""

import logging
import multiprocessing
import os
import signal
import threading
import time
from pathlib import Path

from .diagnostics import LOG_DIRECTORY, configure_logging
from .ocr_service import OCRService, OCRSettings, RecognitionCancelled, RecognitionError

logger = logging.getLogger("vietocr_desktop.ocr")


def _serve_ocr(connection, log_directory, engine_factory):
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Parent handles Ctrl+C and cancellation.
    configure_logging(Path(log_directory), worker=True)
    threads = min(4, max(1, (os.cpu_count() or 2) // 2))
    os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(threads))
    service = None
    try:
        while True:
            operation, payload = connection.recv()
            try:
                if service is None:
                    if engine_factory is None:
                        import torch
                        torch.set_num_threads(threads)
                        service = OCRService()
                    else:
                        service = engine_factory()
                if operation == "load":
                    logger.info("Loading model: %s (%s)", payload.weights, payload.device)
                    service.load(payload)
                    connection.send(("loaded", None))
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
                connection.send(("error", str(exc)[:3000] or type(exc).__name__))
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
                    if kind == "progress" and operation == "recognize":
                        last_activity = time.monotonic()
                        if on_progress:
                            on_progress(*value)
                    elif kind == ("loaded" if operation == "load" else "result"):
                        return value
                elif not self._process.is_alive():
                    raise EOFError
                if time.monotonic() - last_activity > timeout:
                    self._dispose_worker()
                    action = "Nạp model" if operation == "load" else "Nhận diện"
                    raise RecognitionError(f"{action} quá {timeout:g} giây không phản hồi. Hãy thử lại hoặc chọn CPU.")
        except (EOFError, BrokenPipeError, OSError) as exc:
            self._check_cancelled(cancel)
            code = self._process.exitcode if self._process is not None else None
            logger.error("AI process stopped unexpectedly, exit=%s", code, exc_info=True)
            self._dispose_worker()
            detail = f" (mã {code})" if code is not None else ""
            raise RecognitionError(
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
            try:
                self._request("load", OCRSettings(str(path), settings.device, settings.layout), cancel, self.load_timeout)
            except Exception:
                self._dispose_worker()
                raise
            self._model_key = key

    def recognize(self, image, settings: OCRSettings, cancel: threading.Event, on_progress=None):
        with self._lock:
            self.load(settings, cancel)
            return self._request("recognize", (image, settings), cancel, self.recognition_timeout, on_progress)

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
