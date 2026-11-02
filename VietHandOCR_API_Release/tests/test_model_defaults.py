"""New weights must win over old files without breaking explicit overrides."""
import tempfile
import unittest
from pathlib import Path
from app import default_weights
from desktop.ocr_service import OCRSettings


class ModelDefaultTests(unittest.TestCase):
    def test_updated_checkpoint_wins_over_both_legacy_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            self.assertEqual(default_weights(base).name, 'vgg_transformer_final.pth')
            for name in ('vgg_transformer_final.pth', 'vgg_transformer_compact.pth'):
                (base/name).touch()
                self.assertEqual(default_weights(base), base/name)
            import json
            release=base/'model';release.mkdir()
            (release/'model_config.json').write_text(json.dumps({'format':'viethandocr-lite-v1','weights_file':'ml_s44_fp16.pth'}))
            (release/'ml_s44_fp16.pth').touch()
            self.assertEqual(default_weights(base),release/'ml_s44_fp16.pth')
            explicit = OCRSettings(str(base/'custom.pth'))
            self.assertEqual(explicit.weights, str(base/'custom.pth'))
