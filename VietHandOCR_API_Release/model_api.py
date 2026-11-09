"""AI release adapter, independent of the retired desktop/IoT application.

Keeps the AI team's LineRecognizer and V2c preprocessing unchanged. The active
network worker lives in Server/worker; this adapter is for offline model checks.
"""
import json
from pathlib import Path


def lite_model_dir(weight_path):
    path = Path(weight_path).resolve()
    config = path.parent / 'model_config.json'
    if not config.is_file():
        return None
    settings = json.loads(config.read_text(encoding='utf-8'))
    if settings.get('weights_file') != path.name:
        return None
    return path.parent


def release_weights(base):
    directory = Path(base) / 'model'
    config = directory / 'model_config.json'
    if not config.is_file():
        return None
    name = json.loads(config.read_text(encoding='utf-8'))['weights_file']
    if Path(name).name != name:
        raise ValueError('Unsafe model filename')
    weights = directory / name
    return weights if weights.is_file() else None


class LitePredictor:
    def __init__(self, model_dir, device='cpu'):
        from viethandocr_lite import LineRecognizer
        self.recognizer = LineRecognizer(model_dir, device=device, threads=2)

    def predict(self, image):
        return self.recognizer.read(image, pre='v2c')
