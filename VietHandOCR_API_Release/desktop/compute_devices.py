"""Device discovery runs only inside the disposable AI process, never Tk."""

import importlib.util
import logging
import re
import sys
from dataclasses import dataclass

logger = logging.getLogger("vietocr_desktop.devices")


@dataclass(frozen=True)
class ComputeDevice:
    id: str
    name: str
    kind: str  # discrete, integrated, cpu
    adapter_luid: str | None = None


CPU = ComputeDevice("cpu", "CPU", "cpu")


def validate_device(value: str) -> str:
    if value not in ("auto", "cpu", "integrated", "cuda", "xpu", "directml") and not re.fullmatch(
        r"(?:cuda|xpu|directml):\d+", value
    ):
        raise ValueError("Thiết bị phải là auto, cpu, integrated, cuda[:N], xpu[:N] hoặc directml[:N].")
    return value


def select_devices(devices, policy):
    validate_device(policy)
    rank = {"discrete": 0, "integrated": 1, "cpu": 2}
    backend_rank = {"cuda": 0, "xpu": 1, "directml": 2, "cpu": 3}
    ordered = sorted(devices, key=lambda d: (rank[d.kind], backend_rank[d.id.split(":")[0]]))
    if policy == "auto":
        return [d for d in ordered if d.kind != "cpu"] + [CPU]
    if policy == "cpu":
        return [CPU]
    if policy == "integrated":
        return [d for d in ordered if d.kind == "integrated"]
    return [d for d in ordered if d.id == policy or d.id.startswith(policy + ":")]


def discover_devices():
    import torch
    devices = []
    logger.info("Runtime torch=%s CUDA_build=%s", torch.__version__, torch.version.cuda)
    for backend_name in ("cuda", "xpu"):
        try:
            backend = getattr(torch, backend_name, None)
            if backend is None or not backend.is_available():
                logger.info("%s unavailable in this runtime/driver", backend_name)
                continue
            for index in range(backend.device_count()):
                props = backend.get_device_properties(index)
                integrated = bool(getattr(props, "is_integrated", False))
                devices.append(ComputeDevice(f"{backend_name}:{index}", props.name,
                                             "integrated" if integrated else "discrete"))
        except Exception:
            logger.exception("Cannot enumerate %s devices", backend_name)
    if sys.platform == "win32" and importlib.util.find_spec("onnxruntime") is not None:
        try:
            import onnxruntime as ort
            if "DmlExecutionProvider" in ort.get_available_providers():
                from .windows_gpu import directml_adapters
                devices.extend(ComputeDevice(f"directml:{a['index']}", a['name'],
                                             "integrated" if a['integrated'] else "discrete", a['luid'])
                               for a in directml_adapters())
            else:
                logger.info("DirectML unavailable: install onnxruntime-directml for Windows GPUs")
        except Exception:
            logger.exception("Cannot enumerate DirectML devices")
    devices.append(CPU)
    for device in devices:
        logger.info("Compute candidate: %s | %s | %s", device.id, device.kind, device.name)
    return devices
