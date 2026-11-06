"""Check Dart-preprocessed images with both original PyTorch and converted ONNX.

First run: dart run tools/prepare_fixtures.dart
Then use the desktop Python environment to run this script from Mobile/.
"""
import json
import sys
from pathlib import Path
import numpy as np
import torch
from PIL import Image
from export_onnx import API, decode, session


def main():
    sys.path.insert(0, str(API))
    from AI import VietHandOCR
    from viethandocr_lite import prepare_image

    torch.set_num_threads(2)
    mobile = Path(__file__).resolve().parents[1]
    engine = VietHandOCR(str(API / "model/ml_s44_fp16.pth"), device="cpu")
    if engine.predictor is None:
        raise RuntimeError(engine.load_error)
    encoder = session(mobile / "assets/models/vietocr_encoder.onnx", android_options=True)
    decoder = session(mobile / "assets/models/vietocr_decoder.onnx", android_options=True)
    output = mobile / "build/verification"
    report = []
    recognizer=engine.predictor.recognizer
    manifest=json.loads((mobile/'assets/models/manifest.json').read_text(encoding='utf-8'))
    vocab=manifest['vocabulary']
    for case in json.loads((output / "fixtures.json").read_text()):
        lengths = []
        for line in case["tensors"]:
            image = np.fromfile(output / line["file"], dtype="<f4").reshape(1, 3, 64, line["width"])
            with Image.open(output/(line['file']+'.png')) as gray:
                ready=recognizer.input_image(prepare_image(gray)[0])
                reference=(np.asarray(ready).transpose(2,0,1)/255).astype(np.float32)[None]
            if image.shape!=reference.shape:raise AssertionError(f'V2c shape differs {image.shape} != {reference.shape}')
            np.testing.assert_allclose(image,reference,atol=2.01/255,rtol=0,err_msg='Dart V2c differs from original ML_s44 preprocessing')
            with torch.inference_mode():
                memory=recognizer.model.transformer.forward_encoder(recognizer.model.cnn(torch.from_numpy(image)))
                ids=[1]
                for _ in range(257):
                    ids.append(int(recognizer.model.transformer.forward_decoder(torch.tensor(ids)[:,None],memory)[0,-1].argmax()))
                    if ids[-1]==2:break
            expected=''.join(vocab[i] for i in ids[1:] if i!=2).strip()
            actual, _ = decode(encoder, decoder, image, vocab)
            if actual != expected:
                raise AssertionError(f"Different decoded text for {line['file']}")
            if not actual.strip():
                raise AssertionError(f"Empty result for {line['file']}")
            lengths.append(len(actual))
        report.append({"sample": Path(case["source"]).name, "imported": case.get("imported", False), "split": case["split"], "same_text": True,
                       "lines": len(lengths), "characters": lengths,
                       "runtime_options": "Android CPU / BASIC optimization / arena and memory pattern disabled"})
        print(f"PASS {Path(case['source']).name}, imported={case.get('imported', False)}, split={case['split']}, {len(lengths)} lines", flush=True)
    (mobile / "assets/models/mobile_preprocessing_verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
