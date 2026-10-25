import asyncio
import os
import tempfile
import time
from pathlib import Path
import unittest

from desktop.bluetooth_process import _Session
from desktop.bluetooth_transport import RobotCommandRejected, RobotProtocolError


def crash_worker(pipe):
    pipe.recv()
    os._exit(23)


def echo_worker(pipe):
    try:
        while True:
            request_id, command, data = pipe.recv()
            if command == "close":
                return
            if command == "reject":
                pipe.send({"id": request_id, "ok": False, "error": "ERR INVALID_COMMAND: send HELP", "rejected": True})
            else:
                if command == "stale":
                    pipe.send({"id": request_id - 1, "ok": True, "value": "stale"})
                pipe.send({"id": request_id, "ok": True, "value": data})
    finally:
        pipe.close()


class SlowNativeProtocol:
    def __init__(self, address, timeout): self.marker = Path(timeout)
    async def connect(self):
        self.marker.with_suffix(".started").touch()
        try: await asyncio.sleep(30)
        finally: self.marker.with_suffix(".cancelled").touch()
    async def disconnect(self):
        await asyncio.sleep(0.65)  # Longer than the previous 0.3 second kill deadline.
        self.marker.with_suffix(".closed").touch()


def slow_native_worker(pipe):
    import desktop.bluetooth_process as backend
    backend.BLEProtocol = SlowNativeProtocol
    asyncio.run(backend._serve(pipe))
    pipe.close()


class BluetoothProcessTests(unittest.TestCase):
    def test_close_cancels_active_native_operation_and_allows_graceful_cleanup(self):
        async def run(marker):
            session = _Session(target=slow_native_worker)
            pending = asyncio.create_task(session.call("connect", {"address": "AA:BB:CC:DD:EE:01", "timeout": str(marker)}, 10))
            try:
                deadline = time.monotonic() + 5
                while not marker.with_suffix(".started").exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.02)
                self.assertTrue(marker.with_suffix(".started").exists())
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError): await pending
                await session.close()
                self.assertTrue(marker.with_suffix(".cancelled").exists())
                self.assertTrue(marker.with_suffix(".closed").exists())
            finally:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                await session.close()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(run(Path(directory) / "native"))

    def test_stale_rpc_response_is_not_used_for_next_command(self):
        async def run():
            session = _Session(target=echo_worker)
            try:
                self.assertEqual(await session.call("stale", {"fresh": True}, 5), {"fresh": True})
            finally:
                await session.close()
        asyncio.run(run())
    def test_native_worker_crash_does_not_kill_parent_and_next_session_works(self):
        async def run():
            crashed = _Session(target=crash_worker)
            try:
                with self.assertRaises(RobotProtocolError):
                    await crashed.call("scan", {}, 5)
            finally:
                await crashed.close()
            session = _Session(target=echo_worker)
            process = session.process
            try:
                with self.assertRaises(RobotCommandRejected) as error:
                    await session.call("reject", {}, 5)
                self.assertEqual(error.exception.code, "INVALID_COMMAND")
                self.assertEqual(await session.call("PING", {"test": "Tiếng Việt"}, 5), {"test": "Tiếng Việt"})
            finally:
                await session.close()
            self.assertTrue(process._closed)
        asyncio.run(run())

    def test_cancelled_scan_stops_its_worker(self):
        import threading
        async def run():
            session = _Session(target=echo_worker)
            cancelled = threading.Event()
            cancelled.set()
            try:
                with self.assertRaises(asyncio.CancelledError):
                    await session.call("scan", {}, 5, cancelled)
            finally:
                await session.close()
        asyncio.run(run())
