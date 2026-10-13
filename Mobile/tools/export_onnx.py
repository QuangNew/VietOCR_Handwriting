"""Export the existing VietOCR weights for offline Flutter, then verify real inference.

Run with the project's Python 3.11 after installing requirements-export.txt.
Uses standard attention ops so sequence lengths stay dynamic on mobile runtimes.
"""

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from PIL import Image
from torch import nn
from torch.nn import functional as F

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "VietHandOCR_API_Release"
sys.path.insert(0, str(API))
from AI import VietHandOCR
from vietocr.tool.translate import process_input


def attention(module, query, key, value, causal=False):
    dim = module.embed_dim
    weights, biases = module.in_proj_weight.chunk(3), module.in_proj_bias.chunk(3)
    q, k, v = [F.linear(data, weight, bias) for data, weight, bias in zip((query, key, value), weights, biases)]
    head_dim = dim // module.num_heads
    q, k, v = [data.reshape(data.shape[0], data.shape[1], module.num_heads, head_dim).permute(1, 2, 0, 3)
               for data in (q, k, v)]
    scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(head_dim)
    if causal:
        blocked = torch.arange(q.shape[2], device=q.device)[:, None] < torch.arange(k.shape[2], device=k.device)[None, :]
        scores = scores.masked_fill(blocked, float("-inf"))
    output = torch.matmul(torch.softmax(scores, dim=-1), v)
    output = output.permute(2, 0, 1, 3).reshape(query.shape[0], query.shape[1], dim)
    return module.out_proj(output)


class Encoder(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.cnn = model.cnn
        self.language = model.transformer

    def forward(self, image):
        # Explicit positive axes avoid legacy export of permute(-1, 0, 1).
        backbone = self.cnn.model
        conv = backbone.last_conv_1x1(backbone.dropout(backbone.features(image)))
        features = conv.transpose(2, 3).flatten(2).permute(2, 0, 1)
        x = self.language.pos_enc(features * math.sqrt(self.language.d_model))
        encoder = self.language.transformer.encoder
        for layer in encoder.layers:
            x = layer.norm1(x + attention(layer.self_attn, x, x, x))
            x = layer.norm2(x + layer.linear2(layer.activation(layer.linear1(x))))
        return encoder.norm(x)


class Decoder(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.language = model.transformer

    def forward(self, tokens, memory):
        x = self.language.pos_enc(self.language.embed_tgt(tokens) * math.sqrt(self.language.d_model))
        decoder = self.language.transformer.decoder
        for layer in decoder.layers:
            x = layer.norm1(x + attention(layer.self_attn, x, x, x, causal=True))
            x = layer.norm2(x + attention(layer.multihead_attn, x, memory, memory))
            x = layer.norm3(x + layer.linear2(layer.activation(layer.linear1(x))))
        logits = self.language.fc(decoder.norm(x)[-1])
        return logits, torch.argmax(logits, dim=-1)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def session(path):
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def decode(encoder, decoder, image, vocab):
    memory = encoder.run(None, {"image": image})[0]
    tokens = [1]
    for _ in range(129):
        _, predicted = decoder.run(None, {"tokens": np.asarray(tokens, dtype=np.int64)[:, None], "memory": memory})
        token = int(predicted[0])
        tokens.append(token)
        if token == 2:
            break
    return vocab.decode(tokens), tokens


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, default=API / "vgg_transformer_final.pth")
    parser.add_argument("--output", type=Path, default=ROOT / "Mobile/assets/models")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.backends.mha.set_fastpath_enabled(False)
    args.output.mkdir(parents=True, exist_ok=True)
    samples = ROOT / "Mobile/assets/samples"
    samples.mkdir(parents=True, exist_ok=True)
    engine = VietHandOCR(str(args.weights), device="cpu")
    if engine.predictor is None:
        raise RuntimeError(f"Cannot load original weights: {engine.load_error}")
    model = engine.predictor.model.eval()
    encoder, decoder = Encoder(model).eval(), Decoder(model).eval()
    encoder_path, decoder_path = args.output / "vietocr_encoder.onnx", args.output / "vietocr_decoder.onnx"
    image = torch.rand(1, 3, 32, 128)
    with torch.inference_mode():
        reference_memory = model.transformer.forward_encoder(model.cnn(image))
        custom_memory = encoder(image)
        np.testing.assert_allclose(custom_memory.numpy(), reference_memory.numpy(), atol=2e-5, rtol=2e-4)
        tokens = torch.tensor([[1], [5], [10]], dtype=torch.long)
        original_logits = model.transformer.forward_decoder(tokens, reference_memory)[0][:, -1]
        custom_logits = decoder(tokens, custom_memory)[0]
        np.testing.assert_allclose(custom_logits.numpy(), original_logits.numpy(), atol=3e-5, rtol=3e-4)
        if not args.verify_only:
            print("Exporting encoder and decoder (opset 17)...", flush=True)
            torch.onnx.export(encoder, (image,), str(encoder_path), input_names=["image"], output_names=["memory"],
                              dynamic_axes={"image": {3: "image_width"}, "memory": {0: "memory_length"}},
                              opset_version=17, dynamo=False)
            torch.onnx.export(decoder, (tokens, custom_memory), str(decoder_path),
                              input_names=["tokens", "memory"], output_names=["logits", "next_token"],
                              dynamic_axes={"tokens": {0: "token_count"}, "memory": {0: "memory_length"}},
                              opset_version=17, dynamo=False)
    for path in (encoder_path, decoder_path):
        onnx.checker.check_model(str(path))
    encoder_session, decoder_session = session(encoder_path), session(decoder_path)
    # Verify shapes other than the export example, including the first decoding step.
    maximum_error = 0.0
    with torch.inference_mode():
        for width in (32, 90, 256, 510, 1024):
            tensor = torch.rand(1, 3, 32, width)
            original = model.transformer.forward_encoder(model.cnn(tensor))
            converted = encoder_session.run(None, {"image": tensor.numpy()})[0]
            maximum_error = max(maximum_error, float(np.abs(original.numpy() - converted).max()))
            np.testing.assert_allclose(converted, original.numpy(), atol=1e-4, rtol=1e-3)
            for count in (1, 2, 8, 17):
                ids = torch.ones(count, 1, dtype=torch.long)
                reference = model.transformer.forward_decoder(ids, original)[0][:, -1]
                actual = decoder_session.run(None, {"tokens": ids.numpy(), "memory": converted})[0]
                np.testing.assert_allclose(actual, reference.numpy(), atol=2e-4, rtol=1e-3)
    results = []
    for index, filename in enumerate(("test.jpg", "test2.jpg", "test3.jpg", "test4.jpg")):
        path = API / filename
        if not path.is_file():
            continue
        from desktop.domain import load_image
        bgr = np.asarray(load_image(path))[:, :, ::-1].copy()
        gray = engine.dip.process_image(bgr)
        prepared = process_input(Image.fromarray(gray), 32, 32, 1024).numpy()
        expected = engine.predictor.predict(Image.fromarray(gray))
        started = time.monotonic()
        actual, ids = decode(encoder_session, decoder_session, prepared, engine.predictor.vocab)
        if actual != expected:
            raise AssertionError(f"Converted model differs for {filename}: {expected!r} != {actual!r}")
        results.append({"sample": filename, "same_text": True, "seconds": round(time.monotonic()-started, 3)})
        print(f"PASS {filename}: identical text, {len(ids)-1} decoding steps", flush=True)
        if index == 0:
            prepared.astype("<f4").tofile(samples / "reference.f32")
            (samples / "reference.json").write_text(json.dumps({"width": prepared.shape[3], "text": actual},
                                                               ensure_ascii=False, indent=2), encoding="utf-8")
        if index < 2:
            (samples / filename).write_bytes(path.read_bytes())
    manifest = {
        "version": 1, "architecture": "vgg19_bn_transformer", "opset": 17,
        "source_sha256": digest(args.weights), "image_height": 32, "min_width": 32, "max_width": 1024,
        "width_multiple": 10, "max_tokens": 129, "sos": 1, "eos": 2,
        "vocabulary": [engine.predictor.vocab.i2c[index] for index in range(len(engine.predictor.vocab))],
        "models": {"encoder": {"file": encoder_path.name, "bytes": encoder_path.stat().st_size, "sha256": digest(encoder_path)},
                   "decoder": {"file": decoder_path.name, "bytes": decoder_path.stat().st_size, "sha256": digest(decoder_path)}},
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"dynamic_widths": [32, 90, 256, 510, 1024], "token_lengths": [1, 2, 8, 17],
              "max_encoder_absolute_error": maximum_error, "samples": results,
              "total_model_bytes": sum(value["bytes"] for value in manifest["models"].values())}
    (args.output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"PASS: converted model verified; {report['total_model_bytes']/1024**2:.1f} MiB", flush=True)


if __name__ == "__main__":
    main()
