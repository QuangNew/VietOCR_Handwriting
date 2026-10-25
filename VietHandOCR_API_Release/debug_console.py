"""Independent console supervisor: a GUI/native crash cannot close this process."""

import os
import signal
import subprocess
import sys
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent


def run_once(command, directory=BASE / ".logs"):
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"console-{stamp}.log"
    # Keep recent console sessions without touching the rotating diagnostic logs.
    for old in sorted(directory.glob("console-*.log"), reverse=True)[19:]:
        try:
            old.unlink()
        except OSError:
            pass
    with path.open("w", encoding="utf-8", buffering=1) as log:
        def emit(line):
            print(line, flush=True)
            log.write(line + "\n")

        emit(f"VietOCR debug console | {datetime.now().isoformat(timespec='seconds')}")
        emit(f"Log: {path}")
        environment = os.environ.copy()
        environment.update(PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        try:
            child = subprocess.Popen(command, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", bufsize=1, env=environment)
        except OSError as error:
            emit(f"Cannot start app: {error}")
            return 1
        lines = queue.Queue()
        finished = threading.Event()
        def read_output():
            try:
                for line in child.stdout:
                    lines.put(line.rstrip("\r\n"))
            finally:
                child.stdout.close()
                finished.set()
        threading.Thread(target=read_output, name="debug-output", daemon=True).start()
        exited_at = None
        while True:
            try:
                emit(lines.get(timeout=0.1))
            except queue.Empty:
                pass
            if child.poll() is not None:
                exited_at = exited_at or time.monotonic()
                # A crashed GUI's descendant can still hold the stdout pipe open.
                if lines.empty() and (finished.is_set() or time.monotonic() - exited_at > 0.5):
                    break
        code = child.wait()
        emit(f"App exited: {code} (0x{code & 0xFFFFFFFF:08X}). Console remains open.")
        if code:
            for name in ("app-crash.log", "bluetooth-crash.log", "ocr-crash.log"):
                file = directory / name
                try:
                    if file.is_file() and file.stat().st_size:
                        emit(f"--- Recent {name} ---")
                        emit("\n".join(file.read_text(encoding="utf-8", errors="replace").splitlines()[-45:]))
                except OSError:
                    pass
        return code


def supervise(arguments, read_input=input):
    # Ctrl+C is delivered to both console processes. The GUI performs normal cleanup;
    # the supervisor keeps reading output and never raises KeyboardInterrupt.
    previous = signal.signal(signal.SIGINT, lambda *_: None)
    try:
        while True:
            run_once([sys.executable, "-u", "-X", "utf8", "-X", "faulthandler", str(BASE / "app.py"), *arguments])
            try:
                choice = read_input("Enter: reopen app | Q: close debug console > ")
            except EOFError:
                # Run-VietOCR.cmd also pauses on a nonzero supervisor exit.
                return 1
            if choice.strip().lower() in ("q", "quit", "exit"):
                return 0
    finally:
        signal.signal(signal.SIGINT, previous)


if __name__ == "__main__":
    raise SystemExit(supervise(sys.argv[1:]))
