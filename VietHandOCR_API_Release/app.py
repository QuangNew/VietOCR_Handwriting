"""Run the desktop app with the Python interpreter in .venv."""

import argparse
import logging
import multiprocessing
import signal
import sys
import threading
from pathlib import Path


def run_mainloop(root, app):
    """Ctrl+C requests the same cleanup as closing the window, without a traceback."""
    requested = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: requested.set())
    timer = None

    def check_interrupt():
        nonlocal timer
        if requested.is_set():
            app.close(reason='terminal_SIGINT')
        elif not app.closing:
            timer = root.after(100, check_interrupt)

    timer = root.after(100, check_interrupt)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.close(reason='terminal_KeyboardInterrupt')
        root.mainloop()
    finally:
        signal.signal(signal.SIGINT, previous)
        try:
            root.after_cancel(timer)
        except Exception:
            pass  # Tk may already have been destroyed.


def main() -> int:
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="VietOCR Handwriting desktop · Camera OV5640 và hàng đợi OCR")
    parser.add_argument("images", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--camera", type=int, default=0, help="Chỉ số webcam, mặc định 0")
    args = parser.parse_args()
    if not 0 <= args.camera <= 9:
        parser.error("Chỉ số camera phải từ 0 đến 9.")
    from desktop.diagnostics import LOG_DIRECTORY, configure_logging
    configure_logging()
    logger = logging.getLogger("vietocr_desktop")
    logger.info("Starting server-only desktop: Python %s", sys.version)
    try:
        import tkinter as tk
        from desktop.application import Application
    except (ImportError, OSError) as exc:
        logger.exception("Desktop dependency import failed")
        print(f"Thiếu thư viện: {exc}\nDùng Python 3.11 và cài: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    root = app = None
    try:
        from desktop.theme import enable_crisp_scaling
        enable_crisp_scaling()
        root = tk.Tk()
        app = Application(root, "", "server", args.camera)
        if args.images:
            root.after(200, lambda: app.import_files(args.images))
        run_mainloop(root, app)
    except Exception:
        logger.exception("Desktop failed")
        print(f"Ứng dụng gặp lỗi. Xem log: {LOG_DIRECTORY / 'vietocr.log'}", file=sys.stderr)
        return 1
    finally:
        if app is not None and not app.closing:
            app.close()
            root.mainloop()
        elif app is None and root is not None:
            root.destroy()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
