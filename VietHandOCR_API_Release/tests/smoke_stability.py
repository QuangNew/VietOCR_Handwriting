"""Manual stress check: real weights, full batches, reload, cancellation and UI lifetime.

Run from VietHandOCR_API_Release: .venv/Scripts/python.exe -X utf8 tests/smoke_stability.py
Uses no webcam or Bluetooth radio. Prints no OCR contents.
"""

import argparse
import gc
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from PIL import Image

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from desktop.application import Application
from desktop.domain import load_image


def pump(root, predicate, timeout=180):
    deadline = time.monotonic() + timeout
    ticks = 0
    while not predicate() and time.monotonic() < deadline:
        root.update()
        ticks += 1
        time.sleep(0.01)
    if not predicate():
        raise AssertionError("UI task timed out")
    return ticks


def close_app(root, app):
    app.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            root.update()
            if not root.winfo_exists():
                return
        except tk.TclError:
            return
        time.sleep(0.01)
    raise AssertionError("Window failed to close")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10:
        parser.error("rounds must be 1..10")
    weights = BASE / "vgg_transformer_final.pth"
    samples = [load_image(BASE / filename) for filename in ("test.jpg", "test2.jpg")]
    page = Image.new("RGB", (max(image.width for image in samples)+100,
                             sum(image.height for image in samples)+180), "white")
    page.paste(samples[0], (50, 40))
    page.paste(samples[1], (50, samples[0].height+120))
    total_results = 0
    with tempfile.TemporaryDirectory() as directory:
        for round_index in range(args.rounds):
            root = tk.Tk()
            root.withdraw()
            app = Application(root, str(weights), preferences_path=Path(directory) / f"prefs-{round_index}.json")
            errors = []
            started = time.monotonic()
            try:
                for index in range(9):
                    app.batch.add(samples[index % 2], f"sample-{index+1}.jpg")
                app.batch.add(page, "two-lines.png")
                with patch("desktop.application.messagebox.showerror", side_effect=lambda *values, **_: errors.append(values)):
                    if round_index == 0:
                        app.start_recognition()
                        root.after(75, app.cancel_recognition)
                        pump(root, lambda: not app.running)
                        assert app.service._process is None, "Cancelled model remained alive"
                    app.start_recognition()
                    ticks = pump(root, lambda: not app.running)
                    assert not errors, errors
                    assert all(item.status == "done" and item.text for item in app.batch.items)
                    assert app.batch.items[-1].text.count("\n") == 1
                    pid = app.service._process.pid
                    app.start_recognition([app.batch.items[0]])
                    ticks += pump(root, lambda: not app.running)
                    assert app.batch.items[0].status == "done"
                    assert app.service._process.pid == pid, "Warm recognition reloaded the model"
                    assert "torch" not in sys.modules, "AI imported into the Tk process"
                    total_results += 11
                print(f"Round {round_index+1}: 10-image batch + warm reuse PASS; UI ticks={ticks}; "
                      f"elapsed={time.monotonic()-started:.1f}s", flush=True)
            finally:
                service = app.service
                close_app(root, app)
                assert service.closed.wait(3), "AI process was not released"
                del app, root
                gc.collect()  # Tcl ownership is released on this UI thread.
    print(f"PASS: {args.rounds} cold loads, {total_results} real OCR results, cancel/retry and shutdown", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
