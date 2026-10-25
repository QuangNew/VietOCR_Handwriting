"""Store Conv/Linear weights as FP16, retain FP32 inference, verify before saving.

Run from repository root with the desktop Python 3.11 environment.
The original vgg_transformer_final.pth is never modified.
"""
import gc
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import torch
from PIL import Image

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from AI import VietHandOCR
from desktop.domain import load_image


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    torch.set_num_threads(2)
    source = BASE / 'vgg_transformer_final.pth'
    output = BASE / 'vgg_transformer_compact.pth'
    engine = VietHandOCR(str(source), device='cpu')
    if engine.predictor is None: raise RuntimeError(engine.load_error)
    state = engine.predictor.model.state_dict()
    compact = {key: value.half() if value.dtype == torch.float32 and value.ndim in (2, 4)
               and key.endswith('weight') and 'embed' not in key else value for key, value in state.items()}
    samples, expected = [], []
    for name in ['test.jpg', 'test2.jpg', 'test3.jpg', 'test4.jpg']:
        image = engine.dip.process_image(np.asarray(load_image(BASE / name))[:, :, ::-1].copy())
        samples.append((name, Image.fromarray(image)))
        expected.append(engine.predictor.predict(samples[-1][1]))
    temporary = BASE.parent / '.toolchain/compact-desktop.tmp'
    temporary.parent.mkdir(parents=True, exist_ok=True)
    torch.save(compact, temporary)
    del compact, state, engine
    gc.collect()
    engine = VietHandOCR(str(temporary), device='cpu')
    if engine.predictor is None: raise RuntimeError(engine.load_error)
    for (name, image), text in zip(samples, expected):
        if engine.predictor.predict(image) != text:
            temporary.unlink()
            raise AssertionError(f'Compact weights change text for {name}; not installed.')
        print(f'PASS desktop compact model: {name}', flush=True)
    temporary.replace(output)
    report = {'source': source.name, 'source_bytes': source.stat().st_size, 'source_sha256': digest(source),
              'compact': output.name, 'compact_bytes': output.stat().st_size, 'compact_sha256': digest(output),
              'format': 'FP16 storage for Conv/Linear weights; model parameters and inference stay FP32',
              'samples': [{'file': name, 'same_text': True} for name, _ in samples],
              'limits': 'Sample parity, not a full accuracy evaluation on unseen handwriting.'}
    (BASE / 'docs/compact-model-verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: {source.stat().st_size/1024**2:.1f} -> {output.stat().st_size/1024**2:.1f} MiB', flush=True)


if __name__ == '__main__':
    main()
