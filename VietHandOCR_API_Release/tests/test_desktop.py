import tempfile
import threading
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from desktop.domain import BatchFullError, ImageBatch, load_image, prepare_image
from desktop.ocr_service import (
    OCRService, OCRSettings, RecognitionCancelled, RecognitionError, split_text_lines,
)


class ImageBatchTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (120, 80), "white")
        self.batch = ImageBatch()

    def test_upload_and_camera_share_the_ten_image_limit(self):
        for index in range(10):
            self.batch.add(self.image, f"{index}.jpg", "Camera" if index % 2 else "upload.jpg")
        with self.assertRaises(BatchFullError):
            self.batch.add(self.image, "eleventh.jpg")
        self.assertEqual(len(self.batch.items), 10)
        self.batch.remove(self.batch.items[0].id)
        self.batch.add(self.image, "replacement.jpg")
        self.assertEqual(self.batch.remaining, 0)

    def test_preflight_rejects_an_oversized_selection_without_mutating_queue(self):
        self.batch.add(self.image, "first.jpg")
        with self.assertRaises(BatchFullError):
            self.batch.check_capacity(10)
        self.assertEqual(len(self.batch.items), 1)

    def test_phone_exif_orientation_is_applied(self):
        self.image.getexif()[274] = 6
        self.assertEqual(prepare_image(self.image).size, (80, 120))

    def test_transparency_is_composited_on_white(self):
        image = prepare_image(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_rotation_invalidates_previous_recognition(self):
        item = self.batch.add(self.image, "note.jpg")
        item.status, item.text, item.error, item.seconds = "done", "old text", "old error", 2.5
        item.rotate()
        self.assertEqual(item.image.size, (80, 120))
        self.assertEqual((item.status, item.text, item.error, item.seconds), ("ready", "", "", 0.0))

    def test_export_keeps_image_order_and_edited_vietnamese(self):
        first = self.batch.add(self.image, "first.jpg")
        self.batch.add(self.image, "no-result.jpg")
        last = self.batch.add(self.image, "last.jpg")
        first.text, last.text = "Chữ đã sửa", "Tiếng Việt"
        self.assertEqual(self.batch.combined_text(),
                         "--- Ảnh 1: first.jpg ---\nChữ đã sửa\n\n--- Ảnh 3: last.jpg ---\nTiếng Việt")

    def test_unicode_file_names_load_and_resize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chữ viết tay.png"
            Image.new("RGB", (3200, 100), "white").save(path)
            result = load_image(path)
        self.assertEqual(result.width, 2800)
        self.assertLess(result.height, 100)


class SegmentationTests(unittest.TestCase):
    def test_two_lines_keep_their_accents_and_reading_order(self):
        page = np.full((180, 500), 255, dtype=np.uint8)
        cv2.putText(page, "VIET OCR", (25, 66), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
        cv2.rectangle(page, (37, 35), (41, 38), 0, -1)
        cv2.putText(page, "SECOND LINE", (25, 140), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
        lines = split_text_lines(page)
        self.assertEqual(len(lines), 2)
        self.assertLess(lines[0].shape[1], lines[1].shape[1])
        # The isolated mark above the first line must survive cropping.
        self.assertEqual(np.count_nonzero(lines[0] == 0), np.count_nonzero(page[:90] == 0))

    def test_blank_paper_does_not_go_to_the_model(self):
        self.assertEqual(split_text_lines(np.full((400, 300), 255, np.uint8)), [])

    def test_single_line_is_not_split_into_characters(self):
        page = np.full((70, 400), 255, dtype=np.uint8)
        cv2.putText(page, "hello world", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
        self.assertEqual(len(split_text_lines(page)), 1)


class FakeEngine:
    instances = []

    def __init__(self, **kwargs):
        self.predictor = SimpleNamespace(predict=self.predict)
        self.dip = SimpleNamespace(process_image=lambda image: cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        self.images = []
        self.instances.append(self)

    def predict(self, image):
        self.images.append(image)
        return "Tiếng Việt"


class OCRServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.weight_path = Path(self.temp.name) / "weights.pth"
        self.weight_path.touch()
        self.settings = OCRSettings(str(self.weight_path), layout="line")
        FakeEngine.instances = []
        self.patch = patch("desktop.ocr_service.importlib.import_module", return_value=SimpleNamespace(VietHandOCR=FakeEngine))
        self.mock_import = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.service = OCRService()

    def test_model_is_reused_and_rgb_is_converted_to_opencv_bgr(self):
        image = Image.new("RGB", (10, 10), "red")
        for _ in range(2):
            self.assertEqual(self.service.recognize(image, self.settings, threading.Event()), "Tiếng Việt")
        self.assertEqual(len(FakeEngine.instances), 1)
        np.testing.assert_array_equal(FakeEngine.instances[0].images[0][0, 0], [0, 0, 255])

    def test_missing_model_gives_an_actionable_error(self):
        with self.assertRaisesRegex(RecognitionError, "Cài đặt model"):
            self.service.load(OCRSettings(str(self.weight_path.parent / "missing.pth")))

    def test_cancellation_before_start_does_not_load_model(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(RecognitionCancelled):
            self.service.recognize(Image.new("RGB", (10, 10)), self.settings, cancel)
        self.assertEqual(FakeEngine.instances, [])

    def test_cancel_during_a_line_discards_the_partial_result(self):
        cancel = threading.Event()
        with self.assertRaises(RecognitionCancelled):
            self.service.recognize(Image.new("RGB", (10, 10)), self.settings, cancel,
                                   lambda *_: cancel.set())

    def test_swallowed_api_error_is_reported_as_an_error(self):
        self.service.load(self.settings)

        def failing_predict(_):
            warnings.warn("model inference failed")
            return ""

        self.service._engine.predict = failing_predict
        with self.assertRaisesRegex(RecognitionError, "model inference failed"):
            self.service.recognize(Image.new("RGB", (10, 10)), self.settings, threading.Event())

    def test_predictor_load_error_preserves_original_exception(self):
        original = RuntimeError("checkpoint tensor shape mismatch")
        broken = SimpleNamespace(VietHandOCR=lambda **_: SimpleNamespace(predictor=None, load_error=original))
        self.mock_import.return_value = broken
        with self.assertRaisesRegex(RecognitionError, "checkpoint tensor shape mismatch") as raised:
            self.service.load(self.settings)
        self.assertIs(raised.exception.__cause__, original)

    def test_multi_line_text_is_joined_with_line_breaks(self):
        page = np.full((170, 420), 255, dtype=np.uint8)
        cv2.putText(page, "FIRST", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
        cv2.putText(page, "SECOND", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
        progress = []
        result = self.service.recognize(Image.fromarray(page), OCRSettings(str(self.weight_path)),
                                        threading.Event(), lambda *event: progress.append(event))
        self.assertEqual(result, "Tiếng Việt\nTiếng Việt")
        self.assertEqual(progress, [(1, 2), (2, 2)])


if __name__ == "__main__":
    unittest.main()
