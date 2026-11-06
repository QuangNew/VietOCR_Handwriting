"""Publish the small, dependency-free transports to existing application trees."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
for source, target in [
    (ROOT / "clients/python/vietocr_remote.py", ROOT.parent / "VietHandOCR_API_Release/desktop/remote_transport.py"),
    (ROOT / "clients/dart/vietocr_remote.dart", ROOT.parent / "Mobile/lib/services/vietocr_remote.dart"),
]:
    shutil.copy2(source, target)
    print(f"Synced {target.relative_to(ROOT.parent)}")
