"""Compatibility entry point. The desktop is now the native Tauri application."""
from pathlib import Path
import subprocess
import sys


def main():
    executable = Path(__file__).resolve().parents[1] / 'Desktop/dist/vietocr-desktop.exe'
    if not executable.is_file():
        print('Build/download the refactor Windows artifact, then open Desktop/Run-Desktop.cmd.', file=sys.stderr)
        return 1
    try:
        return subprocess.call([str(executable)])
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
