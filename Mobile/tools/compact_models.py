"""Build smaller offline models, verify decoded text, and optionally install them.

Original FP32 files are retained outside Flutter assets before replacement.
Example: python Mobile/tools/compact_models.py --install
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from onnxruntime.quantization import QuantType, quantize_dynamic

from export_onnx import API, ROOT, decode, session


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def compact(source, output, mode):
    if mode == 'mixed-int8':
        quantize_dynamic(str(source), str(output), weight_type=QuantType.QInt8,
                         per_channel=True, op_types_to_quantize=['MatMul'],
                         extra_options={'MatMulConstBOnly': True})
    else:
        shutil.copy2(source, output)
    graph = onnx.load(str(output))
    weights = {node.input[1] for node in graph.graph.node if node.op_type in ('Conv', 'MatMul')}
    replacements = []
    for weight in graph.graph.initializer:
        if weight.name not in weights or weight.data_type != TensorProto.FLOAT:
            continue
        # Storage only: Conv still computes FP32 on CPU after this explicit cast.
        old = weight.name
        small = old + '_stored_fp16'
        value = numpy_helper.to_array(weight).astype(np.float16)
        weight.CopyFrom(numpy_helper.from_array(value, small))
        replacements.append(helper.make_node('Cast', [small], [old], to=TensorProto.FLOAT))
    nodes = list(graph.graph.node)
    del graph.graph.node[:]
    graph.graph.node.extend(replacements + nodes)
    onnx.checker.check_model(graph)
    onnx.save(graph, str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--mode', choices=['fp16-storage', 'mixed-int8'], default='fp16-storage')
    args = parser.parse_args()
    assets = ROOT / 'Mobile/assets/models'
    backup = ROOT / '.toolchain/fp32-models'
    output = ROOT / '.toolchain/compact-models'
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((assets / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('compression') and not backup.exists():
        raise RuntimeError('Original FP32 backup missing; export the original models first.')
    sources = {}
    for role, model in manifest['models'].items():
        sources[role] = (backup if manifest.get('compression') else assets) / model['file']
        compact(sources[role], output / model['file'], args.mode)
    original_encoder, original_decoder = session(sources['encoder']), session(sources['decoder'])
    encoder = session(output / manifest['models']['encoder']['file'], android_options=True)
    decoder = session(output / manifest['models']['decoder']['file'], android_options=True)
    sys.path.insert(0, str(API))
    from AI import VietOCR_DIP_Pipeline
    from vietocr.model.vocab import Vocab
    from vietocr.tool.translate import process_input
    from desktop.domain import load_image
    from PIL import Image
    from AI import MODEL_CONFIG
    vocab, dip = Vocab(MODEL_CONFIG['vocab']), VietOCR_DIP_Pipeline()
    results = []
    for name in ['test.jpg', 'test2.jpg', 'test3.jpg', 'test4.jpg']:
        image = dip.process_image(np.asarray(load_image(API / name))[:, :, ::-1].copy())
        tensor = process_input(Image.fromarray(image), 32, 32, 1024).numpy()
        expected, _ = decode(original_encoder, original_decoder, tensor, vocab)
        actual, _ = decode(encoder, decoder, tensor, vocab)
        if expected != actual:
            raise AssertionError(f'Compact model changes decoded text for {name}; not installing.')
        results.append({'sample': name, 'same_text': True})
        print(f'PASS compact model: {name}', flush=True)
    # Exercise all supported widths and the very first autoregressive step.
    for width in [32, 90, 256, 510, 1024]:
        memory = encoder.run(None, {'image': np.ones((1, 3, 32, width), dtype=np.float32)})[0]
        for count in [1, 2, 8, 17]:
            logits, token = decoder.run(None, {'tokens': np.ones((count, 1), dtype=np.int64), 'memory': memory})
            assert np.isfinite(logits).all() and token.shape == (1,)
    # Include exact tensors produced by the mobile preprocessing if available.
    fixtures = ROOT / 'Mobile/build/verification/fixtures.json'
    if fixtures.exists():
        for case in json.loads(fixtures.read_text()):
            for line in case['tensors']:
                image = np.fromfile(fixtures.parent / line['file'], dtype='<f4').reshape(1, 3, 32, line['width'])
                expected, _ = decode(original_encoder, original_decoder, image, vocab)
                actual, _ = decode(encoder, decoder, image, vocab)
                if expected != actual:
                    raise AssertionError(f'Compact model changes text for Dart fixture {line["file"]}; not installing.')
            results.append({'sample': Path(case['source']).name, 'mobile_split': case['split'], 'same_text': True})
    report = {'format': 'FP16 weight storage, explicit Cast to FP32 compute' if args.mode == 'fp16-storage' else 'INT8 constant MatMul weights + FP16 Conv weight storage',
              'original_bytes': sum(path.stat().st_size for path in sources.values()),
              'compact_bytes': sum((output / model['file']).stat().st_size for model in manifest['models'].values()),
              'samples': results, 'dynamic_widths': [32, 90, 256, 510, 1024],
              'limits': 'Lossy compression. Sample parity is not an accuracy evaluation on unseen handwriting.'}
    (output / 'compression_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if args.install:
        backup.mkdir(parents=True, exist_ok=True)
        if not manifest.get('compression'):
            shutil.copy2(assets / 'manifest.json', backup / 'manifest.json')
            for role, path in sources.items(): shutil.copy2(path, backup / path.name)
        for model in manifest['models'].values():
            target = output / model['file']
            shutil.copy2(target, assets / target.name)
            model.update(bytes=target.stat().st_size, sha256=sha(target))
        manifest['compression'] = report['format']
        (assets / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        shutil.copy2(output / 'compression_verification.json', assets / 'compression_verification.json')
    print(f'PASS: {report["original_bytes"]/1024**2:.1f} -> {report["compact_bytes"]/1024**2:.1f} MiB', flush=True)


if __name__ == '__main__':
    main()
