"""Run in a separate Python process: inspect advertisements, optionally test PING."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


async def diagnose(address, duration, connect):
    from bleak import BleakScanner
    from desktop.bluetooth_transport import BLEProtocol, SERVICE_UUID
    report = {"target": address, "scan_seconds": duration, "scan_filter": "none"}
    discovered = await BleakScanner.discover(timeout=duration, return_adv=True)
    candidates = []
    for device, advertisement in discovered.values():
        name = advertisement.local_name or device.name or ""
        uuids = [value.lower() for value in advertisement.service_uuids]
        if device.address.casefold() == address.casefold() or SERVICE_UUID in uuids or "vietocr" in name.casefold():
            candidates.append({"address": device.address, "name": name,
                               "rssi": advertisement.rssi, "service_uuids": uuids})
    report.update(advertising_devices=len(discovered), candidates=candidates,
                  target_seen=any(row["address"].casefold() == address.casefold() for row in candidates))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if connect and report["target_seen"]:
        protocol = BLEProtocol(address)
        try:
            await protocol.connect()
            await protocol.request("PING")
            print("PASS GATT + TX Notify + PING/PONG", flush=True)
        finally:
            await protocol.disconnect()


def main():
    from desktop.diagnostics import configure_logging
    from desktop.preferences import read_preferences
    from desktop.theme import PREFERENCES_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default=read_preferences(PREFERENCES_PATH).get("robot_ble_address", ""))
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--connect", action="store_true", help="Test only PING, no WAKE or buzzer")
    args = parser.parse_args()
    configure_logging(role="bluetooth-probe")
    asyncio.run(diagnose(args.address, args.seconds, args.connect))


if __name__ == "__main__":
    main()
