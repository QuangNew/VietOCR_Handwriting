"""Validate local weights on bundled samples against VietOCR's reference decoder.

No downloads. Run from the project with .venv/Scripts/python.exe -X utf8
tools/validate_model.py --device cpu --report validation/model-cpu.json
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from model_api import release_weights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', type=Path, default=release_weights(BASE))
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    import cv2
    import torch
    from PIL import Image
    from AI import VietHandOCR
    cv2.setNumThreads(1)
    torch.set_num_threads(2)
    report = dict(model=args.weights.name, sha256=hashlib.sha256(args.weights.read_bytes()).hexdigest(),
                  device=args.device, torch=torch.__version__, cases=[], errors=[])
    try:
        start=time.perf_counter()
        engine=VietHandOCR(str(args.weights), args.device)
        if engine.predictor is None: raise RuntimeError(engine.load_error)
        report['load_seconds']=time.perf_counter()-start
        for suffix in ('', '2', '3', '4', '5'):
            sample=BASE/f'test{suffix}.jpg'
            gray=engine.dip.process_image(str(sample))
            start=time.perf_counter()
            text=engine.predictor.predict(Image.fromarray(gray))
            seconds=time.perf_counter()-start
            row=dict(image=sample.name,text=text,seconds=seconds,
                     engine='ML_s44 release',image_height=engine.predictor.recognizer.height)
            report['cases'].append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    except Exception as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return bool(report['errors'])


if __name__=='__main__': raise SystemExit(main())
