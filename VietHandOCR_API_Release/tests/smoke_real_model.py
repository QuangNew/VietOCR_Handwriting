"""Manual end-to-end check with actual weights; runs in a desktop session.

From VietHandOCR_API_Release:
    .venv/Scripts/python.exe -X utf8 tests/smoke_real_model.py
"""

import sys
import time
import tkinter as tk
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from desktop.application import Application
from desktop.domain import load_image


def main() -> int:
    weights = BASE / "vgg_transformer_final.pth"
    if not weights.is_file():
        print(f"Missing model weights: {weights}", file=sys.stderr)
        return 1
    samples = [BASE / f"test{suffix}.jpg" for suffix in ("", "2", "3", "4")]
    if not all(path.is_file() for path in samples[:2]):
        print("test.jpg and test2.jpg are required for the two-line check.", file=sys.stderr)
        return 1
    samples = [path for path in samples if path.is_file()]
    root = tk.Tk()
    root.withdraw()
    app = Application(root, str(weights))
    for path in samples:
        app.batch.add(load_image(path), path.name, str(path))
    first, second = load_image(samples[0]), load_image(samples[1])
    page = Image.new("RGB", (max(first.width, second.width)+100, first.height+second.height+180), "white")
    page.paste(first, (50, 40))
    page.paste(second, (50, first.height+120))
    app.batch.add(page, "two-line-document.png", "Generated from test.jpg and test2.jpg")
    app.select_item(app.batch.items[0].id)
    app.start_recognition()
    ticks = 0
    deadline = time.monotonic() + 180
    while app.running and time.monotonic() < deadline:
        root.update()
        ticks += 1
        time.sleep(0.02)
    root.update()
    passed = not app.running and all(item.status == "done" and item.text for item in app.batch.items)
    for item in app.batch.items:
        print(f"{item.name} [{item.status}] {item.seconds:.2f}s: {item.text!r}", flush=True)
    if app.batch.items[-1].text.count("\n") != 1:
        passed = False
        print("FAIL: the two-line document did not produce two lines.", flush=True)
    print(f"UI event loop: {ticks} iterations during inference", flush=True)
    print("PASS" if passed else "FAIL", flush=True)
    app.close()
    root.mainloop()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
