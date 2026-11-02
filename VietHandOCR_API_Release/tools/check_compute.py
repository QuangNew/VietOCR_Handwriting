"""Run real offline OCR through each requested device and verify DirectML kernels.

python tools/check_compute.py --device cpu --device auto --device integrated
No BLE connection, Tk window, installation or model download is performed.
"""

import argparse
import hashlib
import importlib.metadata
import json
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from app import default_weights
from desktop.diagnostics import configure_logging
from desktop.ocr_process import OCRProcessService
from desktop.ocr_service import OCRSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", action="append")
    parser.add_argument("--weights", type=Path, default=default_weights(BASE))
    parser.add_argument("--report", type=Path, default=BASE.parent / ".toolchain/desktop-gpu-validation.json")
    parser.add_argument("--profile-directml", action="store_true")
    parser.add_argument("--expect-discrete", action="store_true", help="Fail if auto does not use a discrete GPU")
    parser.add_argument("--samples", nargs="+", default=["test.jpg", "test2.jpg"])
    args = parser.parse_args()
    logs = args.report.parent / "desktop-gpu-validation-logs"
    configure_logging(logs)
    report = {"date": datetime.now(timezone(timedelta(hours=7))).date().isoformat(), "versions": {}, "cases": []}
    for name in ("torch", "torchvision", "onnxruntime-directml"):
        try:
            report["versions"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    reference = None
    integrated_index = None
    for policy in args.device or ("cpu", "auto", "integrated"):
        service = OCRProcessService(log_directory=logs)
        try:
            settings = OCRSettings(str(args.weights), policy, "line")
            started = time.perf_counter()
            service.load(settings)
            row = {"policy": policy, "actual": service.device_info,
                   "load_seconds": round(time.perf_counter() - started, 3), "samples": []}
            texts = []
            for name in args.samples:
                with Image.open(BASE / name) as opened:
                    image = opened.convert("RGB")
                started = time.perf_counter()
                text = service.recognize(image, settings, threading.Event())
                if not text.strip():
                    raise AssertionError(f"{policy}: empty OCR result for {name}")
                texts.append(text)
                row["samples"].append({"file": name, "seconds": round(time.perf_counter()-started, 3),
                                       "text_sha256": hashlib.sha256(text.encode()).hexdigest()})
            row["actual"] = service.device_info
            if policy == "cpu":
                reference = texts
            row["same_text_as_cpu"] = texts == reference if reference is not None else None
            if policy == "auto" and args.expect_discrete and row["actual"]["kind"] != "discrete":
                raise AssertionError("Auto did not use a discrete GPU")
            if policy == "integrated" and row["actual"]["kind"] != "integrated":
                raise AssertionError("The forced integrated policy did not run on the integrated GPU")
            if row["actual"]["id"].startswith("directml:") and row["actual"]["kind"] == "integrated":
                integrated_index = int(row["actual"]["id"].split(":")[1])
            report["cases"].append(row)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(row, ensure_ascii=False), flush=True)
        finally:
            service.close()
            if not service.closed.wait(5):
                raise AssertionError("AI worker did not close")
    if args.profile_directml and integrated_index is not None:
        from desktop.onnx_directml import DirectMLPredictor
        predictor = DirectMLPredictor(args.weights, integrated_index, profile_prefix=logs / "integrated-profile")
        with Image.open(BASE / args.samples[0]) as image:
            predictor.predict(image)
        report["directml_kernel_providers"] = {}
        for name, session in zip(("encoder", "decoder"), predictor.sessions):
            path = Path(session.end_profiling())
            counters = Counter(event.get("args", {}).get("provider") for event in json.loads(path.read_text())
                               if event.get("args", {}).get("provider"))
            report["directml_kernel_providers"][name] = dict(counters)
            if not counters.get("DmlExecutionProvider"):
                raise AssertionError(f"No actual DirectML kernels were recorded for {name}")
        print(json.dumps(report["directml_kernel_providers"]), flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: report {args.report}", flush=True)


if __name__ == "__main__":
    main()
