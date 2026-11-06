"""Compare the production Java OCR core with Python ORT using Dart fixtures.

Requires prepare_fixtures.dart, the official onnxruntime-1.23.2.jar and JDK 21.
All generated tensors/classes/text stay under ignored build/verification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from export_onnx import decode, session


def main():
    mobile = Path(__file__).resolve().parents[1]
    root = mobile.parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, default=root / '.toolchain/onnx-java/onnxruntime-1.23.2.jar')
    parser.add_argument('--java-home', type=Path, default=next((root / '.toolchain/java').glob('jdk-21*')))
    args = parser.parse_args()
    fixtures = mobile / 'build/verification'
    manifest = json.loads((mobile / 'assets/models/manifest.json').read_text(encoding='utf-8'))
    vocab = manifest['vocabulary']
    (fixtures / 'vocabulary.txt').write_text('\n'.join(vocab), encoding='utf-8')

    encoder = session(mobile / 'assets/models/vietocr_encoder.onnx', android_options=True)
    decoder = session(mobile / 'assets/models/vietocr_decoder.onnx', android_options=True)
    rows = []
    for case in json.loads((fixtures / 'fixtures.json').read_text(encoding='utf-8')):
        for line in case['tensors']:
            image = np.fromfile(fixtures / line['file'], dtype='<f4').reshape(1, 3, manifest['image_height'], line['width'])
            expected, _ = decode(encoder, decoder, image, vocab)
            name = line['file'] + '.expected.txt'
            (fixtures / name).write_text(expected, encoding='utf-8')
            rows.append(f"{line['file']}\t{line['width']}\t{name}")
    (fixtures / 'java-cases.tsv').write_text('\n'.join(rows), encoding='utf-8')
    classes = fixtures / 'java'
    classes.mkdir(exist_ok=True)
    core = mobile / 'android/app/src/main/java/vn/pbl4/vietocr_mobile/OnnxRecognizer.java'
    harness = mobile / 'tools/JavaOcrSmoke.java'
    subprocess.run([str(args.java_home / 'bin/javac.exe'), '-encoding', 'UTF-8', '-cp', str(args.runtime),
                    '-d', str(classes), str(core), str(harness)], check=True)
    temporary = root / '.toolchain/onnx-java/native'
    temporary.mkdir(exist_ok=True)
    result = subprocess.run([str(args.java_home / 'bin/java.exe'), '-Xmx1024m', f'-Djava.io.tmpdir={temporary}',
                             '-cp', f'{classes};{args.runtime}', 'JavaOcrSmoke',
                             str(mobile / 'assets/models/vietocr_encoder.onnx'),
                             str(mobile / 'assets/models/vietocr_decoder.onnx'), str(fixtures)],
                            check=True, capture_output=True, text=True, encoding='utf-8')
    print(result.stdout, flush=True)
    assert result.stdout.count('PASS ') == len(rows) + 1
    report = {'date': '2026-11-03', 'runtime': 'ONNX Runtime Java/JNI 1.23.2, Windows x64',
              'production_core': str(core.relative_to(mobile)).replace('\\', '/'),
              'core_sha256': hashlib.sha256(core.read_bytes()).hexdigest(),
              'same_text_as_python_ort': True, 'tensors_checked': len(rows),
              'includes_import_normalization': True, 'invalid_tensor_rejected': True,
              'android_device_test': 'Not performed; host Java/JNI does not verify Android drivers, ABI or RAM.'}
    (mobile / 'assets/models/java_runtime_verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
