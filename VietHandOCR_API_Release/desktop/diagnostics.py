"""Small rotating logs plus native crash traces, without importing the AI stack."""

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIRECTORY = Path(__file__).resolve().parents[1] / ".logs"
_fault_stream = None
logging.getLogger("vietocr_desktop").addHandler(logging.NullHandler())


def configure_logging(directory: Path = LOG_DIRECTORY, *, worker: bool = False) -> None:
    global _fault_stream
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / ("ocr-worker.log" if worker else "vietocr.log"),
                                      maxBytes=2_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(process)d/%(threadName)s %(name)s: %(message)s"))
        logger = logging.getLogger("vietocr_desktop")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logging.getLogger("py.warnings").addHandler(handler)
        logging.captureWarnings(True)
        _fault_stream = (directory / ("ocr-crash.log" if worker else "app-crash.log")).open("a", encoding="utf-8")
        faulthandler.enable(file=_fault_stream)
    except OSError:
        logging.getLogger("vietocr_desktop").addHandler(logging.StreamHandler())
