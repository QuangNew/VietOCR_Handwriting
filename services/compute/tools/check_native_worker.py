"""Exercise the real worker and model over the same pipes as the C# server."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "worker/native/fixtures"


def check(device: str):
    with TemporaryDirectory(prefix="vietocr-worker-") as directory:
        spool = Path(directory)
        page = spool / "page.png"
        shutil.copyfile(FIXTURES / "sample_page.png", page)
        blank = spool / "blank.png"
        Image.new("RGB", (750, 600), "white").save(blank)
        single = spool / "single.png"
        large = spool / "camera-size.jpg"
        with Image.open(page) as source:
            # Top line from the handoff's two-line sample.
            source.crop((220, 224, 800, 312)).save(single)
            source.resize((3300, 1770), Image.Resampling.LANCZOS).save(large, quality=95)
        command = [sys.executable, "-X", "utf8", "-u", str(ROOT / "worker/main.py"),
                   "--model", str(ROOT / "models/ML_s44"), "--spool", str(spool), "--device", device]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   encoding="utf-8", text=True)
        try:
            ready = json.loads(process.stdout.readline())
            assert ready["type"] == "ready" and ready["device"] == device, ready
            print(json.dumps(ready, ensure_ascii=False), flush=True)
            cases = [("page", page, "auto", 2), ("blank", blank, "auto", 0),
                     ("single", single, "line", 1), ("camera-size", large, "auto", 2),
                     ("repeat", page, "auto", 2)]
            for job, path, layout, count in cases:
                process.stdin.write(json.dumps({"id": job, "path": str(path), "layout": layout}) + "\n")
                process.stdin.flush()
                progress = []
                while True:
                    result = json.loads(process.stdout.readline())
                    assert result.get("id") == job, result
                    if result["type"] != "progress":
                        break
                    progress.append((result["completed"], result["total"]))
                assert result["type"] == "result" and result["ok"] == bool(count), result
                assert progress == [(index, count) for index in range(1, count + 1)], progress
                if layout == "auto" and count:
                    actual = result["text"].replace("trơi", "trời")
                    assert actual == (FIXTURES / "reference.txt").read_text(encoding="utf-8").strip(), result
                if layout == "line":
                    assert "trong xanh" in result["text"], result
                print(json.dumps(result, ensure_ascii=False), flush=True)
            process.stdin.write('{"action":"shutdown"}\n')
            process.stdin.flush()
            assert process.wait(timeout=15) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cpu")
    check(parser.parse_args().device)
