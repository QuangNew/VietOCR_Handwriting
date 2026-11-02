"""DirectML inference using the already validated offline ONNX export.

Only the bundled checkpoint (or its verified compact copy) may use this
export. Custom weights must have their own matching export, never silently
run the bundled model instead of the selected checkpoint.
"""

import hashlib
import json
import logging
import math
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger("vietocr_desktop.directml")
SOURCE_SHA = "1c8d0a9ef0ff2272b0b03774abc5b153c4023436a36006397ed6a935a8499bf9"
COMPACT_SHA = "7a1c1c8a96c770cec95e783c9c99da6b3cb44814db21c019a49d56412b501004"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def find_export(weights, directory=None):
    base = Path(__file__).resolve().parents[1]
    directories = [Path(directory)] if directory is not None else [base / "models", base.parent / "Mobile/assets/models"]
    weights_sha = digest(weights)
    for folder in directories:
        path = folder / "manifest.json"
        if not path.is_file():
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        source = manifest.get("source_sha256")
        if weights_sha != source and not (source == SOURCE_SHA and weights_sha == COMPACT_SHA):
            continue
        for name in ("encoder", "decoder"):
            record = manifest["models"][name]
            model = (folder / record["file"]).resolve()
            if model.parent != folder.resolve() or digest(model) != record["sha256"]:
                raise RuntimeError(f"ONNX {name}: file hoặc SHA256 không hợp lệ")
        return folder, manifest
    raise RuntimeError("Chưa có bản ONNX khớp file trọng số đã chọn. DirectML cần models/manifest.json và encoder/decoder đã xuất từ model này.")


class DirectMLPredictor:
    def __init__(self, weights, index, *, adapter_luid=None, directory=None, profile_prefix=None):
        import onnxruntime as ort
        if "DmlExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("Chưa cài ONNX Runtime DirectML")
        if adapter_luid:
            from .windows_gpu import resolve_adapter
            index = resolve_adapter(adapter_luid)["index"]
        self.device_index = index
        folder, self.manifest = find_export(weights, directory)
        providers = [("DmlExecutionProvider", {"device_id": str(index)}), "CPUExecutionProvider"]
        self.sessions = []
        for name in ("encoder", "decoder"):
            options = ort.SessionOptions()
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            if profile_prefix:
                options.enable_profiling = True
                options.profile_file_prefix = f"{profile_prefix}-{name}"
            session = ort.InferenceSession(str(folder / self.manifest["models"][name]["file"]),
                                           sess_options=options, providers=providers)
            session.disable_fallback()
            if session.get_providers()[0] != "DmlExecutionProvider":
                raise RuntimeError(f"{name}: DirectML không được kích hoạt")
            self.sessions.append(session)
        logger.info("DirectML device_id=%s export=%s; GPU kernels with CPU support for unsupported operators", index, folder)

    def predict(self, image):
        m = self.manifest
        width = min(m["max_width"], max(m["min_width"],
                    math.ceil(m["image_height"] * image.width / image.height / m["width_multiple"]) * m["width_multiple"]))
        image = image.convert("RGB").resize((width, m["image_height"]), Image.Resampling.LANCZOS)
        tensor = np.ascontiguousarray(np.asarray(image).transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        encoder, decoder = self.sessions
        memory = encoder.run(None, {"image": tensor})[0]
        tokens = [m["sos"]]
        for _ in range(m["max_tokens"]):
            _, predicted = decoder.run(None, {"tokens": np.asarray(tokens, dtype=np.int64)[:, None], "memory": memory})
            value = int(predicted[0])
            if value == m["eos"]:
                break
            tokens.append(value)
        return "".join(m["vocabulary"][value] for value in tokens[1:] if value > 2)
