"""Importable spawn-process fixtures. Deliberate failures stay in the AI child."""

import os
import time
from pathlib import Path


class ProcessEngine:
    def __init__(self):
        self.calls = 0
        self.settings = None
        self.poisoned = False

    def load(self, settings):
        path = Path(settings.weights)
        if path.stem == "bad":
            raise RuntimeError("invalid checkpoint fixture")
        if path.stem == "crash-load":
            marker = path.with_suffix(".crashed")
            if not marker.exists():
                marker.touch()
                os._exit(17)
        if path.stem == "slow":
            path.with_suffix(".started").touch()
            time.sleep(30)
        self.settings = settings

    def recognize(self, image, settings, cancel, on_progress):
        path = Path(settings.weights)
        if path.stem == "error-inference":
            marker = path.with_suffix(".failed")
            if not marker.exists():
                marker.touch()
                self.poisoned = True
                raise RuntimeError("simulated CUDA failure")
            if self.poisoned:
                raise RuntimeError("model state remains poisoned")
        if path.stem == "crash-inference":
            os._exit(19)
        if path.stem == "slow-inference":
            path.with_suffix(".started").touch()
            time.sleep(30)
        on_progress(1, 2)
        on_progress(2, 2)
        self.calls += 1
        return f"Tiếng Việt {self.calls} · {os.getpid()} · {image.getpixel((0, 0))}"
