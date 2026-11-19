"""Small disposable discovery process: no PyTorch import or model allocation."""
import json,sys
from pathlib import Path
rows=[]
try:
    import onnxruntime as ort
    from core.windows_gpu import directml_adapters
    model=Path(__file__).resolve().parents[1]/'models/ML_s44'
    matching=False
    try:
        manifest=json.loads((model/'onnx/manifest.json').read_text())
        config=json.loads((model/'model_config.json').read_text())
        matching=manifest.get('source_sha256')==config['weights_sha256'] and manifest.get('precision')=='FP32' and all(
            (model/'onnx'/manifest['models'][name]['file']).is_file() for name in ('encoder','decoder'))
    except (OSError,ValueError,KeyError):pass
    if sys.platform=='win32' and 'DmlExecutionProvider' in ort.get_available_providers():
        for a in directml_adapters():
            if a['integrated']:
                rows.append({'id':f"directml:{a['index']}",'name':a['name'],'kind':'integrated',
                    'available':matching,'reason':None if matching else 'Matching FP32 ONNX export is missing'})
except Exception:
    pass
print(json.dumps(rows))
