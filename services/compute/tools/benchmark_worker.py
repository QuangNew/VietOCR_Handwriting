"""Measure actual isolated-worker load, inference and memory; never downloads.

Run only when enough host RAM is free. All child processes are reaped on exit.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]


def benchmark(args):
    processes = []
    spool = ROOT / "runtime/images"
    spool.mkdir(parents=True, exist_ok=True)
    image = spool / "benchmark.image"
    image.write_bytes(args.image.read_bytes())
    report = {"replicas": args.workers, "device": args.device, "workers": [], "runs": []}
    try:
        for _ in range(args.workers):
            p = subprocess.Popen([sys.executable, "-X", "utf8", "-u", str(ROOT / "worker/main.py"),
                "--model", str(ROOT / "models/ML_s44"), "--device", args.device, "--spool", str(spool)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", cwd=ROOT)
            processes.append(p)
            event = json.loads(p.stdout.readline())
            if event["type"] != "ready":
                raise RuntimeError("Worker failed to initialise")
            report["workers"].append(event)
        def run(p, n):
            p.stdin.write(json.dumps({"id": str(n), "path": str(image), "layout": "line"}) + "\n")
            p.stdin.flush()
            while True:
                event = json.loads(p.stdout.readline())
                if event["type"] != "progress":
                    event.pop("text", None)  # Do not retain recognised text in measurements.
                    return event
        for iteration in range(3):
            start = time.perf_counter()
            with ThreadPoolExecutor(args.workers) as pool:
                results = list(pool.map(lambda pair: run(*pair), [(p, iteration * args.workers + i) for i, p in enumerate(processes)]))
            elapsed = time.perf_counter() - start
            report["runs"].append({"wallSeconds": elapsed, "imagesPerSecond": args.workers / elapsed, "results": results})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"workers": args.workers, "lastImagesPerSecond": report["runs"][-1]["imagesPerSecond"],
                          "memory": [r["memory"] for r in report["runs"][-1]["results"]]}, indent=2))
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=20)
        image.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "validation/worker-benchmark.json")
    benchmark(parser.parse_args())
