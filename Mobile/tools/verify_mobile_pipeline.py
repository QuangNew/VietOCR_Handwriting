"""Check Dart-preprocessed images with both original PyTorch and converted ONNX.

First run: dart run tools/prepare_fixtures.dart
Then use the desktop Python environment to run this script from Mobile/.
"""
import json
import sys
from pathlib import Path
import numpy as np
import torch
from export_onnx import API, decode, session


def main():
    sys.path.insert(0, str(API))
    from AI import VietHandOCR
    from vietocr.tool.translate import translate

    torch.set_num_threads(2)
    mobile = Path(__file__).resolve().parents[1]
    engine = VietHandOCR(str(API / "vgg_transformer_final.pth"), device="cpu")
    if engine.predictor is None:
        raise RuntimeError(engine.load_error)
    encoder = session(mobile / "assets/models/vietocr_encoder.onnx", android_options=True)
    decoder = session(mobile / "assets/models/vietocr_decoder.onnx", android_options=True)
    output = mobile / "build/verification"
    report = []
    for case in json.loads((output / "fixtures.json").read_text()):
        lengths = []
        for line in case["tensors"]:
            image = np.fromfile(output / line["file"], dtype="<f4").reshape(1, 3, 32, line["width"])
            with torch.inference_mode():
                ids, _ = translate(torch.from_numpy(image), engine.predictor.model)
            expected = engine.predictor.vocab.decode(ids[0].tolist())
            actual, _ = decode(encoder, decoder, image, engine.predictor.vocab)
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
