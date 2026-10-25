"""Optional real Windows scan smoke check; no pairing or GATT connection."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.bluetooth_process import scan_robots_isolated
from desktop.diagnostics import configure_logging


async def check():
    for attempt in range(2):
        devices = await scan_robots_isolated(timeout=2)
        print(f"PASS isolated scan {attempt + 1}: {len(devices)} matching devices", flush=True)


if __name__ == '__main__':
    configure_logging()
    asyncio.run(check())
