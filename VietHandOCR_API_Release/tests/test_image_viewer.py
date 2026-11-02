import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from desktop.domain import ImageBatch
from desktop.image_viewer import ImageViewport


class NativeImageTests(unittest.TestCase):
    def test_thumbnails_crop_rotate_and_export_preserve_original_jpeg(self):
        output = io.BytesIO()
        Image.new('RGB', (2048, 1536), (30, 70, 140)).save(output, 'JPEG', quality=100)
        jpeg = output.getvalue()
        batch = ImageBatch()
        with tempfile.TemporaryDirectory() as directory:
            item = batch.add_jpeg(jpeg, 'OV3660.jpg')
            for _ in range(3):
                self.assertLessEqual(item.thumbnail().width, 54)
            self.assertEqual(item.image.size, (2048, 1536))
            item.status, item.text = 'done', 'old OCR'
            item.replace_image(item.image.crop((500, 200, 1800, 1200)))
            self.assertEqual(item.image.size, (1300, 1000))
            self.assertEqual((item.status, item.text), ('ready', ''))
            item.rotate()
            self.assertEqual(item.image.size, (1000, 1300))
            raw, edited = Path(directory)/'raw.jpg', Path(directory)/'crop.png'
            item.export(raw, original=True)
            item.export(edited)
            self.assertEqual(raw.read_bytes(), jpeg)
            with Image.open(edited) as image:
                self.assertEqual(image.size, (1000, 1300))
            original_path = item.original_path
            batch.remove(item.id)
            self.assertFalse(original_path.exists())

    def test_zoom_keeps_cursor_image_position_and_crop_uses_native_coordinates(self):
        view = ImageViewport(2048, 1536)
        view.fit(1024, 768)
        self.assertEqual(view.point(400, 300), (800, 600))
        before = view.point(400, 300)
        view.zoom(4, 400, 300)
        self.assertEqual(view.point(400, 300), before)
        start = view.point(view.x+200*view.scale, view.y+100*view.scale)
        end = view.point(view.x+1800*view.scale, view.y+1300*view.scale)
        self.assertEqual(view.crop_box(end, start), (200, 100, 1800, 1300))
        self.assertEqual(view.point(-1e5, 1e5), (0, 1536))
        self.assertIsNone(view.crop_box(start, start))

