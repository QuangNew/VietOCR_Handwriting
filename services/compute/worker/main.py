"""One persistent, serial ML_s44 replica. Private NDJSON over inherited pipes.

stdout is protocol only; model warnings/logs go to stderr. The C# coordinator is
the only network-facing process. A native CUDA failure kills this child only.
"""
import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import threading

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
PROTOCOL = sys.stdout


def send(event, **values):
    PROTOCOL.write(json.dumps({"type": event, **values}, ensure_ascii=False, allow_nan=False) + "\n")
    PROTOCOL.flush()


def watch_parent(parent_pid):
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, parent_pid)
        if not handle:
            os._exit(71)
        try:
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
            os._exit(0)  # Release CUDA even if the host was killed during inference.
        finally:
            kernel.CloseHandle(handle)
    else:
        while True:
            if os.getppid() != parent_pid:
                os._exit(0)
            time.sleep(1)


def memory(torch, device):
    data = dict(allocatedMiB=0, reservedMiB=0, peakMiB=0, ramMiB=0, deviceUsedMiB=0)
    if device.startswith("cuda"):
        free, total = torch.cuda.mem_get_info(device)
        data.update(allocatedMiB=torch.cuda.memory_allocated(device) / 1048576,
                    reservedMiB=torch.cuda.memory_reserved(device) / 1048576,
                    peakMiB=torch.cuda.max_memory_reserved(device) / 1048576,
                    deviceUsedMiB=(total - free) / 1048576)
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in ("peak", "working", "pmin", "pmax", "pnmin", "pnmax", "page", "peakpage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        from ctypes import wintypes
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not get_info(current(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        data["ramMiB"] = counters.working / 1048576
    else:
        import resource
        data["ramMiB"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return data


def run(args):
    started = time.perf_counter()
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import cv2
        from PIL import Image
        from core.document_pipeline import prepare_lines, read_document
        from core.recognizer import LineRecognizer
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        cv2.setNumThreads(1)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False  # Dynamic widths: avoid expensive per-shape autotuning.
        config = json.loads((args.model / "model_config.json").read_text(encoding="utf-8"))
        weights = args.model / config["weights_file"]
        with weights.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != config["weights_sha256"]:
                raise ValueError("Checkpoint hash mismatch")
        if args.device.startswith('directml:'):
            from core.directml import DirectMLRecognizer
            recognizer=DirectMLRecognizer(args.model,int(args.device.split(':')[1]),threads=2)
        else:
            recognizer = LineRecognizer.from_settings(config, weights, device=args.device)
        # Exercise max-width encoder activations, not just a tiny input. Decoder
        # grows per job; the admission safety margin remains necessary.
        if args.device.startswith('directml:'):
            recognizer.warmup()
        else:
            tensor = torch.zeros((1, 3, config["image_height"], config["image_max_width"]), device=args.device)
            with torch.inference_mode():
                encoded = recognizer.model.transformer.forward_encoder(recognizer.model.cnn(tensor))
                recognizer.model.transformer.forward_decoder(torch.ones((8, 1), dtype=torch.long, device=args.device), encoded)
            del tensor, encoded
        if args.device.startswith("cuda"):
            torch.cuda.synchronize(args.device)
        Image.MAX_IMAGE_PIXELS = args.max_pixels
        corrector_dir = args.corrector_model if args.corrector_model else (args.model.parent / "Bartpho_v2_fp16")
        corrector_cache = {"instance": None, "failed": False}

        def get_corrector():
            if corrector_cache["instance"] is not None:
                return corrector_cache["instance"]
            if corrector_cache["failed"] or not corrector_dir.exists():
                return None
            try:
                from core.text_corrector import BartphoCorrector
                t_c = time.perf_counter()
                corrector_cache["instance"] = BartphoCorrector(corrector_dir, device=args.device)
                print(
                    f"Loaded Bartpho_v2_fp16 on {corrector_cache['instance'].device} "
                    f"in {(time.perf_counter() - t_c) * 1000:.0f} ms",
                    file=sys.stderr,
                    flush=True,
                )
                return corrector_cache["instance"]
            except Exception as err:
                corrector_cache["failed"] = True
                print(f"Bartpho_v2_fp16 unavailable ({type(err).__name__}: {err}); fallback to ML_s44 only", file=sys.stderr, flush=True)
                return None

        send("ready", pid=os.getpid(), model=config["name"], device=args.device, pipeline="native-2026.11.19",
             loadMs=(time.perf_counter() - started) * 1000, memory=memory(torch, args.device),
             correctionAvailable=corrector_dir.exists())
        for line in sys.stdin:
            request = json.loads(line)
            if request.get("action") == "shutdown":
                break
            job_id = request["id"]
            use_correction = bool(request.get("correct", False))
            begun = time.perf_counter()
            try:
                path = Path(request["path"]).resolve()
                path.relative_to(args.spool.resolve())
                image = read_document(path, args.max_pixels)
                width, height = image.size
                pre = time.perf_counter()
                total, lines = prepare_lines(image, request.get("layout", "auto"))
                del image
                preprocess_ms = (time.perf_counter() - pre) * 1000
                texts = []
                for index in range(1, total + 1):
                    pre = time.perf_counter()
                    crop = next(lines)
                    preprocess_ms += (time.perf_counter() - pre) * 1000
                    text = recognizer.predict(crop)
                    if text.strip():
                        texts.append(text.strip())
                    del crop
                    send("progress", id=job_id, completed=index, total=total)
                if not texts:
                    raise ValueError("Model không đọc được chữ trong ảnh.")
                correction_ms = 0.0
                if use_correction:
                    corr = get_corrector()
                    if corr is not None:
                        t_corr = time.perf_counter()
                        texts = corr.correct_lines(texts)
                        correction_ms = (time.perf_counter() - t_corr) * 1000
                if args.device.startswith("cuda"):
                    torch.cuda.synchronize(args.device)
                send("result", id=job_id, ok=True, text="\n".join(texts), width=width, height=height,
                     elapsedMs=(time.perf_counter()-begun)*1000, preprocessingMs=preprocess_ms,
                     correctionMs=correction_ms, corrected=bool(use_correction and corrector_cache["instance"] is not None),
                     memory=memory(torch, args.device))
            except (ValueError, OSError, Image.DecompressionBombError) as error:
                send("result", id=job_id, ok=False, error=str(error)[:400], recoverable=True,
                     elapsedMs=(time.perf_counter()-begun)*1000, memory=memory(torch, args.device))
            except Exception as error:
                # A poisoned CUDA context must never be returned to the pool.
                send("fatal", id=job_id, error=f"{type(error).__name__}: worker failure",
                     memory=memory(torch, args.device))
                raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--corrector-model", type=Path, default=None)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--max-pixels", type=int, default=16_000_000)
    parser.add_argument("--parent-pid", type=int)
    options = parser.parse_args()
    if options.parent_pid:
        threading.Thread(target=watch_parent, args=(options.parent_pid,), daemon=True).start()
    try:
        run(options)
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        send("fatal", error=f"{type(exc).__name__}: {str(exc)[:400]}")
        sys.exit(1)
