"""viethandocr-lite release (model/): locating it and running it behind the predictor interface.

A release is a folder holding model_config.json (vocabulary, image size, CNN pooling, SHA-256 of
the checkpoint) and the checkpoint it names. AI.VietHandOCR sends such a checkpoint to
LitePredictor; any other .pth is a legacy VietOCR checkpoint and keeps using TorchPredictor.

Only the standard library is imported at load time. torch/scipy (through viethandocr_lite) are
imported inside LitePredictor, so the Tk process never loads them.
"""
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger('vietocr_desktop.ocr')

RELEASE_FOLDER = 'model'
CONFIG_FILE = 'model_config.json'
CONFIG_FORMAT = 'viethandocr-lite-v1'


def _read_config(folder):
    try:
        config = json.loads((Path(folder) / CONFIG_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict) or config.get('format') != CONFIG_FORMAT:
        return None
    name = config.get('weights_file')
    return config if isinstance(name, str) and name and Path(name).name == name else None


def release_weights(base):
    """Checkpoint named by base/model/model_config.json, or None when no release is installed there.

    The name comes from the config, so swapping the release (FP16 -> FP32, a newer model) is a file
    copy; the file itself may still be missing (weights are not in Git).
    """
    config = _read_config(Path(base) / RELEASE_FOLDER)
    return Path(base) / RELEASE_FOLDER / config['weights_file'] if config else None


def lite_model_dir(weights):
    """Folder of the release that `weights` belongs to, or None for a legacy VietOCR checkpoint."""
    path = Path(weights)
    config = _read_config(path.parent)
    # normcase: Windows file names are case-insensitive, and a missed match would silently run the
    # checkpoint under the legacy 32 px config (same tensor shapes, so it loads without an error).
    same_file = config and os.path.normcase(config['weights_file']) == os.path.normcase(path.name)
    return path.parent if same_file else None


class LitePredictor:
    """predict(PIL image) -> text, the call OCRService makes on TorchPredictor.

    LineRecognizer.read applies the V2c margin crop the model was trained with, then decodes
    greedily. The FP16 checkpoint is upcast to FP32 on load (as TorchPredictor does for the compact
    legacy one), so precision follows the project: FP32 compute. `device` is passed through as is.
    """

    def __init__(self, model_dir, device='cpu'):
        try:
            from viethandocr_lite import LineRecognizer
        except ImportError as error:
            raise RuntimeError(f'Thiếu thư viện cho model ML_s44 ({error}). '
                               'Chạy lại: python -m pip install -r requirements.txt') from error
        started = time.perf_counter()
        self.device = device
        self.recognizer = LineRecognizer(model_dir, device=device)
        dtype = next(self.recognizer.model.parameters()).dtype
        logger.info('Lite model initialized in %.3fs (%s, %s)', time.perf_counter() - started, device, dtype)

    def predict(self, image):
        return self.recognizer.read(image)
