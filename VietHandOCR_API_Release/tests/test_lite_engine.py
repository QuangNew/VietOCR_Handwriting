"""ML_s44 (viethandocr-lite) integration: release discovery, engine choice, device plumbing, real model.

The real-model tests run in child processes (as the app does) and are skipped when the weights,
which are not in Git, or torch/scipy are missing.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

import AI
from app import default_weights
from desktop.lite_predictor import LitePredictor, lite_model_dir, release_weights

BASE = Path(__file__).resolve().parents[1]


def make_release(folder, weights_file="ml_s44_fp16.pth", **config):
    """A viethandocr-lite folder: model_config.json plus the checkpoint file it names."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    values = {"format": "viethandocr-lite-v1", "weights_file": weights_file, **config}
    (folder / "model_config.json").write_text(json.dumps(values), encoding="utf-8")
    (folder / weights_file).write_bytes(b"checkpoint")
    return folder / weights_file


class TemporaryBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def touch(self, name):
        path = self.base / name
        path.write_bytes(b"legacy checkpoint")
        return path


class ReleaseDiscoveryTests(TemporaryBase):
    def test_checkpoint_named_by_the_config_belongs_to_the_release(self):
        weights = make_release(self.base / "model")
        self.assertEqual(lite_model_dir(weights), weights.parent)
        self.assertEqual(release_weights(self.base), weights)

    def test_any_other_checkpoint_is_a_legacy_one(self):
        make_release(self.base / "model")
        beside_config = self.base / "model" / "vgg_transformer_final.pth"
        beside_config.write_bytes(b"legacy")
        self.assertIsNone(lite_model_dir(beside_config))
        self.assertIsNone(lite_model_dir(self.touch("vgg_transformer_final.pth")))

    @unittest.skipUnless(os.name == "nt", "file names are case-insensitive only on Windows")
    def test_file_name_case_does_not_matter_on_windows(self):
        weights = make_release(self.base / "model")
        self.assertEqual(lite_model_dir(weights.with_name("ML_S44_FP16.PTH")), weights.parent)

    def test_missing_broken_or_foreign_config_means_no_release(self):
        folder = self.base / "model"
        folder.mkdir()
        weights = folder / "ml_s44_fp16.pth"
        weights.write_bytes(b"x")
        self.assertIsNone(lite_model_dir(weights))
        self.assertIsNone(release_weights(self.base))
        for text in ("{not json", "[]", json.dumps({"format": "other", "weights_file": weights.name}),
                     json.dumps({"format": "viethandocr-lite-v1"}),
                     json.dumps({"format": "viethandocr-lite-v1", "weights_file": "../ml_s44_fp16.pth"})):
            with self.subTest(config=text):
                (folder / "model_config.json").write_text(text, encoding="utf-8")
                self.assertIsNone(lite_model_dir(weights))
                self.assertIsNone(release_weights(self.base))

    def test_a_swapped_in_fp32_release_is_found_by_its_config_not_by_a_fixed_name(self):
        weights = make_release(self.base / "model", "ml_s44_fp32.pth")
        self.assertEqual(release_weights(self.base), weights)
        self.assertEqual(lite_model_dir(weights), weights.parent)
        self.assertEqual(default_weights(self.base), weights)


class DefaultWeightsTests(TemporaryBase):
    def test_installed_release_wins_over_legacy_checkpoints(self):
        weights = make_release(self.base / "model")
        self.touch("vgg_transformer_compact.pth")
        self.touch("vgg_transformer_final.pth")
        self.assertEqual(default_weights(self.base), weights)

    def test_legacy_checkpoints_keep_working_until_the_release_weights_are_copied(self):
        # model_config.json is tracked in Git, the .pth is not: pulling must not break an existing setup.
        make_release(self.base / "model").unlink()
        final = self.touch("vgg_transformer_final.pth")
        self.assertEqual(default_weights(self.base), final)
        compact = self.touch("vgg_transformer_compact.pth")
        self.assertEqual(default_weights(self.base), compact)

    def test_nothing_installed_points_at_the_file_to_copy(self):
        weights = make_release(self.base / "model")
        weights.unlink()
        self.assertEqual(default_weights(self.base), weights)
        self.assertEqual(default_weights(self.base / "empty"), self.base / "empty" / "vgg_transformer_final.pth")


class FakeLite:
    calls = []

    def __init__(self, model_dir, device):
        self.calls.append((model_dir, device))
        self.images = []

    def predict(self, image):
        self.images.append(image)
        return "Tiếng Việt"


class EngineSelectionTests(TemporaryBase):
    def setUp(self):
        super().setUp()
        FakeLite.calls = []

    def test_release_checkpoint_goes_to_the_lite_predictor_with_the_chosen_device(self):
        weights = make_release(self.base / "model")
        with patch("desktop.lite_predictor.LitePredictor", FakeLite), \
             patch("desktop.torch_predictor.TorchPredictor") as legacy:
            engine = AI.VietHandOCR(str(weights), device="cuda:0")
        self.assertEqual(FakeLite.calls, [(weights.parent, "cuda:0")])
        legacy.assert_not_called()
        self.assertIsInstance(engine.predictor, FakeLite)
        self.assertIsNone(engine.load_error)

    def test_other_checkpoints_keep_the_legacy_predictor_and_config(self):
        weights = self.touch("vgg_transformer_final.pth")
        with patch("desktop.lite_predictor.LitePredictor", FakeLite), \
             patch("desktop.torch_predictor.TorchPredictor") as legacy:
            engine = AI.VietHandOCR(str(weights), device="cpu")
        self.assertEqual(FakeLite.calls, [])
        config = legacy.call_args.args[0]
        self.assertEqual((config["weights"], config["device"], config["dataset"]["image_height"]),
                         (str(weights), "cpu", 32))
        self.assertIs(engine.predictor, legacy.return_value)

    def test_default_weights_resolve_next_to_ai_py(self):
        if release_weights(BASE) is None:
            self.skipTest("model/model_config.json is not installed")
        with patch("desktop.lite_predictor.LitePredictor", FakeLite):
            AI.VietHandOCR(device="cpu")
        self.assertEqual(FakeLite.calls, [(BASE / "model", "cpu")])

    def test_load_failure_is_kept_for_the_service_to_report(self):
        weights = make_release(self.base / "model")
        error = RuntimeError("Thiếu thư viện")
        with patch("desktop.lite_predictor.LitePredictor", side_effect=error), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            engine = AI.VietHandOCR(str(weights))
        self.assertIsNone(engine.predictor)
        self.assertIs(engine.load_error, error)

    def test_pipeline_feeds_the_lite_predictor_the_deskewed_gray_page(self):
        weights = make_release(self.base / "model")
        with patch("desktop.lite_predictor.LitePredictor", FakeLite):
            engine = AI.VietHandOCR(str(weights))
        page = np.full((60, 300, 3), 255, np.uint8)
        page[20:30, 40:200] = 0
        self.assertEqual(engine.predict(page), "Tiếng Việt")
        sent = engine.predictor.images[0]
        self.assertEqual((sent.mode, sent.size), ("L", (300, 60)))


class FakeRecognizer:
    created = []

    def __init__(self, model_dir, device="cpu", threads=None):
        self.created.append((model_dir, device))
        self.model = SimpleNamespace(parameters=lambda: iter([SimpleNamespace(dtype="float32")]))

    def read(self, image):
        return f"read {image.size}"


class LitePredictorTests(unittest.TestCase):
    def setUp(self):
        FakeRecognizer.created = []
        patcher = patch.dict(sys.modules, {"viethandocr_lite": SimpleNamespace(LineRecognizer=FakeRecognizer)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_folder_and_device_reach_the_recognizer_unchanged(self):
        LitePredictor(Path("model"), "cuda:0")
        self.assertEqual(FakeRecognizer.created, [(Path("model"), "cuda:0")])

    def test_predict_is_read_which_applies_the_v2c_crop(self):
        self.assertEqual(LitePredictor(Path("model")).predict(Image.new("L", (30, 10))), "read (30, 10)")

    def test_missing_library_gives_an_actionable_error(self):
        with patch.dict(sys.modules, {"viethandocr_lite": None}):
            with self.assertRaisesRegex(RuntimeError, "pip install -r requirements.txt"):
                LitePredictor(Path("model"))


def edit_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def simplify(text):
    """Case, edge spaces and the trailing full stop the model likes to add do not matter here."""
    return unicodedata.normalize("NFC", text).casefold().strip().rstrip(".").strip()


def real_model_unavailable():
    weights = release_weights(BASE)
    if weights is None or not weights.is_file():
        return "ML_s44 weights are not in model/ (they are not in Git)"
    if any(importlib.util.find_spec(name) is None for name in ("torch", "scipy")):
        return "torch/scipy are not installed"
    return None


TWO_LINE_PAGE = """
import sys, threading
from PIL import Image
from desktop.domain import load_image
from desktop.ocr_service import OCRService, OCRSettings
first, second = load_image('test.jpg'), load_image('test2.jpg')
page = Image.new('RGB', (max(first.width, second.width) + 100, first.height + second.height + 180), 'white')
page.paste(first, (50, 40))
page.paste(second, (50, first.height + 120))
print(OCRService().recognize(page, OCRSettings(sys.argv[1], 'cpu', 'auto'), threading.Event()))
"""

LOADED_DTYPES = """
import sys
from pathlib import Path
from desktop.lite_predictor import LitePredictor
model = LitePredictor(Path(sys.argv[1]).parent, 'cpu').recognizer.model
print(sorted({str(t.dtype) for t in [*model.parameters(), *model.buffers()] if t.is_floating_point()}))
"""

UNAVAILABLE = real_model_unavailable()


@unittest.skipIf(UNAVAILABLE is not None, UNAVAILABLE)
class RealModelTests(unittest.TestCase):
    def run_python(self, *arguments):
        result = subprocess.run([sys.executable, "-X", "utf8", *arguments], cwd=BASE, capture_output=True,
                                text=True, encoding="utf-8", timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return result.stdout

    def test_cli_reads_single_line_images_on_cpu(self):
        for image, expected in (("test.jpg", "khái quát về biển đảo việt nam"),
                                ("demo/images/co_be_ban_diem.png", "cô bé bán diêm")):
            with self.subTest(image=image):
                output = self.run_python("AI.py", "--image", image, "--device", "cpu")
                text = output.split("----------------------")[1].strip()
                self.assertLessEqual(edit_distance(simplify(text), expected), 1, text)

    def test_auto_layout_splits_and_reads_a_two_line_page(self):
        output = self.run_python("-c", TWO_LINE_PAGE, str(release_weights(BASE)))
        lines = output.strip().splitlines()
        self.assertEqual(len(lines), 2, output)
        self.assertLessEqual(edit_distance(simplify(lines[0]), "khái quát về biển đảo việt nam"), 2, lines[0])
        self.assertTrue(lines[1].startswith("Chương trình"), lines[1])

    def test_fp16_checkpoint_is_computed_in_fp32(self):
        self.assertEqual(self.run_python("-c", LOADED_DTYPES, str(release_weights(BASE))).strip(), "['torch.float32']")


if __name__ == "__main__":
    unittest.main()
