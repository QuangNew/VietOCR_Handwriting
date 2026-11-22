"""One persistent, serial ML_s44 replica. Private NDJSON over inherited pipes.

stdout is protocol only; model warnings/logs go to stderr. The C# coordinator is
the only network-facing process. A native CUDA failure kills this child only.
"""
import argparse
import contextlib
import ctypes
import gc
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


def _process_ram_mib():
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
        return counters.working / 1048576.0
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _host_total_ram_mib():
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / 1048576.0
        return 0.0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for row in handle:
                if row.startswith("MemTotal:"):
                    return int(row.split()[1]) / 1024.0
    except OSError:
        pass
    return 0.0


def memory(torch, device, corrector_cache=None):
    data = dict(allocatedMiB=0, reservedMiB=0, peakMiB=0, ramMiB=0, deviceUsedMiB=0)
    if device.startswith("cuda"):
        free, total = torch.cuda.mem_get_info(device)
        data.update(allocatedMiB=torch.cuda.memory_allocated(device) / 1048576,
                    reservedMiB=torch.cuda.memory_reserved(device) / 1048576,
                    peakMiB=torch.cuda.max_memory_reserved(device) / 1048576,
                    deviceUsedMiB=(total - free) / 1048576)
    data["ramMiB"] = _process_ram_mib()
    loaded = bool(corrector_cache and corrector_cache.get("instance") is not None)
    bartpho_ram = float(corrector_cache.get("ram_mib", 0.0)) if loaded else 0.0
    bartpho_vram = float(corrector_cache.get("vram_mib", 0.0)) if loaded else 0.0
    total_ram = _host_total_ram_mib()
    bartpho_pct = round(min(100.0, max(0.0, (bartpho_ram / total_ram) * 100.0)), 2) if (loaded and total_ram > 0) else 0.0
    data.update(
        bartphoLoaded=loaded,
        bartphoRamMiB=round(bartpho_ram, 2),
        bartphoRamPercent=bartpho_pct,
        bartphoVramMiB=round(bartpho_vram, 2),
        bartphoDevice=corrector_cache.get("device") if loaded else None,
    )
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
        corrector_cache = {
            "instance": None,
            "failed": False,
            "baseline_ram_mib": None,
            "ram_mib": 0.0,
            "vram_mib": 0.0,
            "device": None,
            "steady_measured": False,
        }

        def get_corrector():
            if corrector_cache["instance"] is not None:
                return corrector_cache["instance"]
            if corrector_cache["failed"] or not corrector_dir.exists():
                return None
            try:
                gc.collect()
                if args.device.startswith("cuda"):
                    torch.cuda.synchronize(args.device)
                ram_before = _process_ram_mib()
                vram_before = (torch.cuda.memory_allocated(args.device) / 1048576.0) if args.device.startswith("cuda") else 0.0
                from core.text_corrector import BartphoCorrector
                t_c = time.perf_counter()
                instance = BartphoCorrector(corrector_dir, device=args.device)
                gc.collect()
                if str(instance.device).startswith("cuda"):
                    torch.cuda.synchronize(instance.device)
                ram_after = _process_ram_mib()
                vram_after = (torch.cuda.memory_allocated(instance.device) / 1048576.0) if str(instance.device).startswith("cuda") else 0.0
                model_mib = instance.parameter_mib()
                ram_delta = max(0.0, ram_after - ram_before)
                if instance.device.type == "cpu":
                    ram_delta = max(ram_delta, model_mib)
                vram_delta = max(0.0, vram_after - vram_before, model_mib) if instance.device.type == "cuda" else 0.0
                corrector_cache["instance"] = instance
                corrector_cache["baseline_ram_mib"] = ram_before
                corrector_cache["ram_mib"] = round(ram_delta, 2)
                corrector_cache["vram_mib"] = round(vram_delta, 2)
                corrector_cache["device"] = str(instance.device)
                print(
                    f"Loaded Bartpho_v2_fp16 on {instance.device} "
                    f"in {(time.perf_counter() - t_c) * 1000:.0f} ms "
                    f"(+{ram_delta:.1f} MiB RAM, +{vram_delta:.1f} MiB VRAM)",
                    file=sys.stderr,
                    flush=True,
                )
                return instance
            except Exception as err:
                corrector_cache["failed"] = True
                print(f"Bartpho_v2_fp16 unavailable ({type(err).__name__}: {err}); fallback to ML_s44 only", file=sys.stderr, flush=True)
                return None

        send("ready", pid=os.getpid(), model=config["name"], device=args.device, pipeline="native-2026.11.19",
             loadMs=(time.perf_counter() - started) * 1000, memory=memory(torch, args.device, corrector_cache),
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
                        if not corrector_cache["steady_measured"] and corrector_cache["baseline_ram_mib"] is not None:
                            steady_delta = max(0.0, _process_ram_mib() - corrector_cache["baseline_ram_mib"])
                            corrector_cache["ram_mib"] = round(max(corrector_cache["ram_mib"], steady_delta), 2)
                            corrector_cache["steady_measured"] = True
                if args.device.startswith("cuda"):
                    torch.cuda.synchronize(args.device)
                send("result", id=job_id, ok=True, text="\n".join(texts), width=width, height=height,
                     elapsedMs=(time.perf_counter()-begun)*1000, preprocessingMs=preprocess_ms,
                     correctionMs=correction_ms, corrected=bool(use_correction and corrector_cache["instance"] is not None),
                     memory=memory(torch, args.device, corrector_cache))
            except (ValueError, OSError, Image.DecompressionBombError) as error:
                send("result", id=job_id, ok=False, error=str(error)[:400], recoverable=True,
                     elapsedMs=(time.perf_counter()-begun)*1000, memory=memory(torch, args.device, corrector_cache))
            except Exception as error:
                # A poisoned CUDA context must never be returned to the pool.
                send("fatal", id=job_id, error=f"{type(error).__name__}: worker failure",
                     memory=memory(torch, args.device, corrector_cache))
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
