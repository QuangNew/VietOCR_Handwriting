"""Small rotating logs plus native crash traces, without importing the AI stack."""

import faulthandler
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIRECTORY = Path(__file__).resolve().parents[1] / ".logs"
_fault_stream = None
logging.getLogger("vietocr_desktop").addHandler(logging.NullHandler())


def configure_logging(directory: Path = LOG_DIRECTORY, *, worker: bool = False, role: str | None = None) -> None:
    global _fault_stream
    try:
        directory.mkdir(parents=True, exist_ok=True)
        name = role or ("ocr-worker" if worker else "vietocr")
        logger = logging.getLogger("vietocr_desktop")
        # Reconfiguration must not duplicate handlers or keep an old crash file open.
        for old in list(logger.handlers):
            if getattr(old, "_vietocr_owned", False):
                logger.removeHandler(old)
                logging.getLogger("py.warnings").removeHandler(old)
                old.close()
        handler = RotatingFileHandler(directory / f"{name}.log",
                                      maxBytes=2_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(process)d/%(threadName)s %(name)s: %(message)s"))
        handler._vietocr_owned = True
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        console = logging.StreamHandler(sys.stderr)
        console._vietocr_owned = True
        console.setFormatter(handler.formatter)
        logger.addHandler(console)
        logging.getLogger("py.warnings").addHandler(handler)
        logging.captureWarnings(True)
        if _fault_stream is not None:
            faulthandler.disable()
            _fault_stream.close()
        crash_name = f"{role}-crash.log" if role else ("ocr-crash.log" if worker else "app-crash.log")
        _fault_stream = (directory / crash_name).open("a", encoding="utf-8")
        faulthandler.enable(file=_fault_stream)
    except OSError:
        logging.getLogger("vietocr_desktop").addHandler(logging.StreamHandler())
