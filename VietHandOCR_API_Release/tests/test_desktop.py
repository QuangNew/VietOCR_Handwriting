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



class ImageBatchTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (120, 80), "white")
        self.batch = ImageBatch()

    def test_queue_accepts_more_than_ten_and_keeps_full_images_on_disk(self):
        for index in range(25):
            self.batch.add(self.image, f"{index}.jpg", "Camera" if index % 2 else "upload.jpg")
        self.assertEqual(len(self.batch.items), 25)
        self.assertTrue(all(item.image_path.is_file() for item in self.batch.items))
        self.assertNotIn('image', vars(self.batch.items[0]))
        self.assertEqual(self.batch.items[0].image.size, self.image.size)
        path = self.batch.items[0].image_path
        self.batch.remove(self.batch.items[0].id)
        self.assertFalse(path.exists())
        self.batch.add(self.image, "replacement.jpg")
        self.assertEqual(len(self.batch.items), 25)

    def test_preflight_has_no_arbitrary_image_count_cap(self):
        self.batch.add(self.image, "first.jpg")
        self.batch.check_capacity(1000)
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
