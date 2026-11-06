"""Install the preserved original FP32 exports, with a matching asset manifest."""
import hashlib
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / '.toolchain/fp32-models'
assets = root / 'Mobile/assets/models'
original = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
current = json.loads((assets / 'manifest.json').read_text(encoding='utf-8'))
if (original.get('source_sha256'),original.get('image_height')) != (current.get('source_sha256'),current.get('image_height')):
    raise RuntimeError('Bản backup FP32 thuộc model cũ. Không ghi đè ML_s44. Dùng export_onnx.py để xuất lại checkpoint hiện tại.')
for role, model in original['models'].items():
    path = source / model['file']
    with path.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    if path.stat().st_size != model['bytes'] or checksum != model['sha256']:
        raise RuntimeError(f'Invalid original FP32 model: {role}')
for model in original['models'].values():
    shutil.copy2(source / model['file'], assets / model['file'])
original['precision'] = 'FP32 weights and compute; original verified export, no weight compression'
original['release'] = '1.4.0+6'
(assets / 'manifest.json').write_text(json.dumps(original, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Restored original FP32 models:', sum(model['bytes'] for model in original['models'].values()), 'bytes')
