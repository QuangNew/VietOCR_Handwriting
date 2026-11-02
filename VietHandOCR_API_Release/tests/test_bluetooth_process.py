import asyncio
import os
import signal
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
                if command == 'progress':
                    pipe.send({"id": request_id, "progress": (10, 100)})
                    pipe.send({"id": request_id, "progress": (100, 100)})
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


class OfflineWifiProtocol:
    def __init__(self, address, timeout): pass
    async def connect(self): pass
    async def disconnect(self): pass
    async def request(self, command, *args, **kwargs):
        if command == 'PING': return 'PONG'
        if command == 'WIFI SCAN': raise RobotCommandRejected('ERR WIFI_SCAN_FAILED: cannot start scan; retry')
        if command == 'WIFI STATUS': return 'WIFI STATUS OFFLINE 1 201'
        raise AssertionError('Sensor should not start before LAN is ready')


def offline_wifi_worker(pipe):
    import desktop.bluetooth_process as backend
    backend.BLEProtocol = OfflineWifiProtocol
    asyncio.run(backend._serve(pipe))
    pipe.close()


def orientation_worker(pipe):
    import desktop.bluetooth_process as backend
    from unittest.mock import patch
    class Protocol:
        def __init__(self, *args): self.commands = []
        async def connect(self): pass
        async def disconnect(self): pass
        async def request(self, command, *args, **kwargs):
            if command == 'COMMANDS': return self.commands
            self.commands.append(command)
            if command == 'WIFI STATUS': return 'WIFI STATUS READY 127.0.0.1 ' + 'a' * 32 + ' 61'
            return 'OK ' + command
    backend.BLEProtocol = Protocol
    with patch('desktop.wifi_camera.check_http'):
        asyncio.run(backend._serve(pipe))
    pipe.close()


def slow_native_worker(pipe):
    import desktop.bluetooth_process as backend
    backend.BLEProtocol = SlowNativeProtocol
    asyncio.run(backend._serve(pipe))
    pipe.close()


def interrupt_worker(pipe):
    import desktop.bluetooth_process as backend
    from unittest.mock import patch

    original = backend._serve

    async def serve(connection):
        # Exercise the real worker's handler and IPC loop, without a BLE radio.
        signal.raise_signal(signal.SIGINT)
        await original(connection)

    with patch.object(backend, "_serve", serve):
        backend._worker(pipe)


class BluetoothProcessTests(unittest.TestCase):
    def test_camera_orientation_crosses_real_worker_ipc_before_stream_opens(self):
        async def run():
            session = _Session(target=orientation_worker)
            try:
                await session.call('connect', {'address': 'test', 'timeout': 1}, 5)
                endpoint = await session.call('network', {'action': 'camera_open', 'mirror': True, 'flip': False}, 5)
                self.assertEqual(endpoint.ip, '127.0.0.1')
                commands = await session.call('request', {'command': 'COMMANDS', 'timeout': 1}, 5)
                self.assertEqual(commands, ['WIFI STATUS', 'CAM ORIENT 1 0', 'CAM OPEN'])
            finally:
                await session.close()
        asyncio.run(run())

    def test_reported_wifi_errors_leave_the_real_worker_loop_alive_and_ping_usable(self):
        async def run():
            session = _Session(target=offline_wifi_worker)
            try:
                await session.call('connect', {'address': 'test', 'timeout': 1}, 5)
                for action in ('wifi_scan', 'wifi_status', 'stream_info', 'camera_open'):
                    with self.assertRaises(ValueError):
                        await session.call('network', {'action': action}, 5)
                    self.assertTrue(session.process.is_alive())
                    self.assertEqual(await session.call('request', {'command': 'PING', 'timeout': 1}, 5), 'PONG')
            finally:
                await session.close()
        asyncio.run(run())
    def test_capture_progress_is_forwarded_without_consuming_final_reply(self):
        async def run():
            progress = []
            session = _Session(target=echo_worker)
            try:
                value = await session.call('progress', {'complete': True}, 5,
                                           on_progress=lambda *values: progress.append(values))
                self.assertEqual(value, {'complete': True})
                self.assertEqual(progress, [(10, 100), (100, 100)])
            finally:
                await session.close()
        asyncio.run(run())
    def test_console_interrupt_does_not_kill_worker_or_prevent_close(self):
        async def run():
            session = _Session(target=interrupt_worker)
            try:
                with self.assertRaisesRegex(RobotProtocolError, "Invalid Bluetooth worker operation"):
                    await session.call("invalid", {}, 5)
                self.assertTrue(session.process.is_alive())
            finally:
                await session.close()
        asyncio.run(run())

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
