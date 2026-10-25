"""Verify JNI callback classes survive a minimized release APK, not just Java tests."""
import argparse
from pathlib import Path
import re
import zipfile

REQUIRED = {'OnnxTensor', 'TensorInfo', 'OnnxJavaType', 'OrtException', 'OrtSession', 'NodeInfo', 'ValueInfo'}


def verify(apk, mapping):
    classes = dict(re.findall(r'^(ai\.onnxruntime\.[^\s]+) -> ([^:]+):$', mapping.read_text(encoding='utf-8'), re.M))
    # R8 generates its own helper/lambda classes after applying keep rules.
    # JNI cannot reference these generated names; only original ORT classes
    # must retain the names hard-coded in the native library.
    generated = {name for name in classes if '$$ExternalSynthetic' in name}
    classes = {name: target for name, target in classes.items() if name not in generated}
    missing = {f'ai.onnxruntime.{name}' for name in REQUIRED} - classes.keys()
    renamed = {name: target for name, target in classes.items() if name != target}
    if missing or renamed:
        raise AssertionError(f'Unsafe ONNX JNI release: missing={sorted(missing)}, renamed={renamed}')
    with zipfile.ZipFile(apk) as archive:
        dex = [archive.read(name) for name in archive.namelist() if re.fullmatch(r'classes\d*\.dex', name)]
        for name in REQUIRED:
            descriptor = f'Lai/onnxruntime/{name};'.encode()
            assert any(descriptor in data for data in dex), f'Missing DEX JNI callback: {name}'
    # JNI calls this constructor by descriptor after the very first encoder run.
    block = re.search(r'^ai\.onnxruntime\.TensorInfo -> ai\.onnxruntime\.TensorInfo:\n(.*?)(?=^\S+ -> [^\n]+:\n|\Z)',
                      mapping.read_text(encoding='utf-8'), re.M | re.S)
    assert block and '<init>(long[],java.lang.String[],int)' in block[1], 'Missing JNI TensorInfo constructor'
    return {'onnx_classes_preserved': len(classes), 'r8_generated_helpers_excluded': len(generated),
            'jni_classes_verified_in_dex': sorted(REQUIRED),
            'tensor_info_constructor_preserved': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('apk', type=Path)
    parser.add_argument('mapping', type=Path)
    args = parser.parse_args()
    print(verify(args.apk, args.mapping))
