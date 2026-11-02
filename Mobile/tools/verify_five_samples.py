"""Compare Dart-preprocessed images on FP32 and compact ONNX; keep actual text.

Run prepare_fixtures.dart with test.jpg through test5.jpg first. This checks
runtime parity, not handwriting accuracy on an Android phone.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from export_onnx import decode, session, ROOT


def main():
    directory = ROOT / 'Mobile/build/verification'
    manifest = json.loads((ROOT / 'Mobile/assets/models/manifest.json').read_text(encoding='utf-8'))
    vocab = manifest['vocabulary']
    class Vocabulary:
        def decode(self, ids):
            return ''.join(vocab[i] for i in ids if i > 2).strip()
    original = ROOT / '.toolchain/fp32-models'
    compact = ROOT / '.toolchain/compact-models'
    encoder, decoder = session(original / 'vietocr_encoder.onnx', android_options=True), session(original / 'vietocr_decoder.onnx', android_options=True)
    small_encoder, small_decoder = session(compact / 'vietocr_encoder.onnx', android_options=True), session(compact / 'vietocr_decoder.onnx', android_options=True)
    rows = []
    for case in json.loads((directory / 'fixtures.json').read_text(encoding='utf-8')):
        expected, actual = [], []
        for line in case['tensors']:
            tensor = np.fromfile(directory / line['file'], dtype='<f4').reshape(1, 3, 32, line['width'])
            text, _ = decode(encoder, decoder, tensor, Vocabulary())
            small_text, _ = decode(small_encoder, small_decoder, tensor, Vocabulary())
            expected.append(text); actual.append(small_text)
        row = {'sample': Path(case['source']).name, 'imported': case['imported'], 'split': case['split'],
               'lines': len(expected), 'fp32_text': '\n'.join(expected), 'compact_text': '\n'.join(actual), 'same_text': expected == actual}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    assert len({row['sample'] for row in rows}) == 5
    assert any(row['sample'] == 'test.jpg' and row['fp32_text'] == 'KHÁI QUÁT VỀ BIỂN ĐẢO VIỆT NAM' for row in rows)
    result = {'date': '2026-10-27', 'runtime': 'Windows x64 Python ORT, Android session options',
              'samples': rows, 'compact_matches_fp32_on_all_cases': all(row['same_text'] for row in rows),
              'android_device_test': False, 'note': 'Matching host outputs does not prove correctness of an installed APK or Android ARM kernels.'}
    target = ROOT / 'Mobile/assets/models/five_sample_verification.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__': main()
