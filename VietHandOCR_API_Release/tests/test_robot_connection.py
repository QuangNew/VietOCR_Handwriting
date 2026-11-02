"""BLE integration tests with an asynchronous GATT peripheral (no radio required)."""

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from desktop.bluetooth_transport import (BLEProtocol, RobotProtocolError, RobotLinkLost, SERVICE_UUID, RX_UUID, TX_UUID,
                                         scan_robots, validate_address)
from desktop.domain import AssistantState as State
from desktop.preferences import read_preferences, update_preferences
from desktop.robot_connection import RobotClient, RobotSnapshot, state_commands
from desktop.theme import load_theme, save_theme


class FakeBLE:
    address = "AA:BB:CC:DD:EE:01"

    def __init__(self, *, drop_on=None, wrong_first=False, no_reply=(), find_delay=0, scan_delay=0, legacy_theme=False, disconnect_delay=0,
                 camera_status='READY'):
        self.condition = threading.Condition()
        self.commands, self.clients, self.sessions = [], [], 0
        self.drop_on, self.dropped, self.wrong_first = drop_on, False, wrong_first
        self.no_reply, self.find_delay, self.scan_delay = no_reply, find_delay, scan_delay
        self.find_started, self.scan_cancelled = threading.Event(), threading.Event()
        self.reply_override = None
        self.legacy_theme = legacy_theme
        self.camera_status = camera_status
        self.wifi_response = 'WIFI STATUS READY 127.0.0.1 ' + 'a' * 32 + ' 61'
        self.scan_error = None
        self.disconnect_delay = disconnect_delay
        self.disconnect_started = threading.Event()
        self.advertisements = {
            self.address: self.advertisement(self.address, "VietOCR-Assistant", -45),
        }
        peripheral = self

        class Scanner:
            @staticmethod
            async def discover(**kwargs):
                assert kwargs["return_adv"] and "service_uuids" not in kwargs
                try:
                    await asyncio.sleep(peripheral.scan_delay)
                    if peripheral.scan_error:
                        raise peripheral.scan_error
                    return peripheral.advertisements
                except asyncio.CancelledError:
                    peripheral.scan_cancelled.set()
                    raise

            @staticmethod
            async def find_device_by_address(address, **kwargs):
                assert "service_uuids" not in kwargs, "Target address must not depend on advertised UUIDs"
                peripheral.find_started.set()
                await asyncio.sleep(peripheral.find_delay)
                return SimpleNamespace(address=address, name="VietOCR-Assistant")

        class Client:
            def __init__(self, device, *, disconnected_callback, services, **kwargs):
                assert device.address == peripheral.address and services == [SERVICE_UUID]
                assert not kwargs or kwargs == {"winrt": {"use_cached_services": False}}
                self.callback, self.is_connected = disconnected_callback, False
                self.loop, self.notify = None, None
                self.received, self.state = bytearray(), "sleep"
                peripheral.clients.append(self)

            def check_loop(self):
                assert self.loop is asyncio.get_running_loop(), "A connection must use a single asyncio loop"

            async def connect(self):
                self.loop = asyncio.get_running_loop()
                self.is_connected = True
                with peripheral.condition:
                    peripheral.sessions += 1
                    self.session = peripheral.sessions

            async def start_notify(self, uuid, callback):
                self.check_loop()
                assert uuid == TX_UUID
                self.notify = callback

            async def write_gatt_char(self, uuid, data, *, response):
                self.check_loop()
                assert uuid == RX_UUID and response is True and len(data) <= 20 and self.notify
                self.received.extend(data)
                while b"\n" in self.received:
                    raw, _, self.received = self.received.partition(b"\n")
                    command = raw.decode("ascii")
                    with peripheral.condition:
                        peripheral.commands.append((self.session, command))
                        peripheral.condition.notify_all()
                    if command == peripheral.drop_on and not peripheral.dropped:
                        peripheral.dropped = True
                        self.is_connected = False
                        self.callback(self)
                        return
                    if command in peripheral.no_reply:
                        continue
                    if command == "PROCESS":
                        self.state = "processing"
                    if command.startswith("PROGRESS ") and self.state != "processing":
                        reply = b"ERR PROGRESS_REQUIRES_PROCESSING\r\n"
                    elif peripheral.legacy_theme and command.startswith("THEME "):
                        reply = b"ERR INVALID_COMMAND: send HELP\r\n"
                    elif peripheral.wrong_first and self.session == 1:
                        reply = b"OTHER DEVICE\r\n"
                    elif command == 'CAM STATUS':
                        reply = (('CAM STATUS ' + peripheral.camera_status if peripheral.camera_status is not None
                                  else 'ERR CAMERA_REQUEST: invalid command') + '\r\n').encode('ascii')
                    elif command == 'WIFI STATUS':
                        reply = (peripheral.wifi_response + '\r\n').encode('ascii')
                    elif command == 'WIFI SAVED':
                        reply = b'WIFI SAVED 1 61\r\n'
                    else:
                        reply = (("PONG" if command == "PING" else "OK " + command) + "\r\n").encode("ascii")
                    if peripheral.reply_override is not None:
                        reply = peripheral.reply_override
                    # Notifications can arrive before write_gatt_char finishes.
                    for offset in range(0, len(reply), 3):
                        self.notify(TX_UUID, bytearray(reply[offset:offset + 3]))
                await asyncio.sleep(0)

            async def disconnect(self):
                if self.loop is not None:
                    self.check_loop()
                peripheral.disconnect_started.set()
                await asyncio.sleep(peripheral.disconnect_delay)
                self.is_connected = False
                self.callback(self)

        self.scanner, self.client_type = Scanner, Client

    @staticmethod
    def advertisement(address, name, rssi, services=None):
        return (SimpleNamespace(address=address, name=name),
                SimpleNamespace(local_name=name, rssi=rssi, service_uuids=services or [SERVICE_UUID]))

    def __enter__(self):
        self.patcher = patch("desktop.bluetooth_transport._backend", return_value=(self.scanner, self.client_type))
        self.patcher.start()
        return self

    def __exit__(self, *_):
        self.patcher.stop()

    def wait_for(self, command, *, session=None, timeout=3):
        with self.condition:
            if not self.condition.wait_for(
                lambda: any(text == command and (session is None or number == session)
                            for number, text in self.commands), timeout):
                raise AssertionError(f"Missing {command!r} for session {session}: {self.commands}")


class RobotProtocolTests(unittest.TestCase):
    def test_handshake_followed_by_immediate_loss_keeps_backoff_increasing(self):
        failed = threading.Event()
        class Unstable:
            client = None
            def __init__(self, *args): self.woken = False
            async def connect(self): pass
            async def disconnect(self): pass
            async def request(self, command, *args, **kwargs):
                if command == 'WAKE': self.woken = True; return 'OK WAKE'
                if self.woken: raise RobotLinkLost('temporary driver cancellation')
                return 'PONG'
        failures = []
        def status(phase, detail):
            if phase == 'offline':
                failures.append(detail)
                if len(failures) == 3: failed.set()
        client = RobotClient(FakeBLE.address, status, protocol_factory=Unstable, heartbeat=.01, retry_delay=.05)
        client.start()
        try:
            self.assertTrue(failed.wait(3))
            self.assertEqual(client._failures, 3)
            self.assertAlmostEqual(client.retry_seconds, .2)
        finally:
            client.stop(); self.assertTrue(client.closed.wait(2))
    def test_replacement_waits_until_previous_native_disconnect_finishes(self):
        lock = threading.Lock()
        with FakeBLE(disconnect_delay=0.35) as radio:
            first = RobotClient(radio.address, lambda *_: None, radio_lock=lock)
            second = RobotClient(radio.address, lambda *_: None, radio_lock=lock)
            first.start()
            try:
                self.assertTrue(first.connected.wait(2))
                first.stop()
                second.start()
                self.assertTrue(radio.disconnect_started.wait(1))
                self.assertFalse(second.connected.wait(0.1))
                self.assertEqual(len(radio.clients), 1)
                self.assertTrue(second.connected.wait(2))
                self.assertFalse(radio.clients[0].is_connected)
                self.assertEqual(radio.sessions, 2)
            finally:
                first.stop(); second.stop()
                self.assertTrue(first.closed.wait(2))
                self.assertTrue(second.closed.wait(2))

    def test_manual_retry_wakes_existing_thread_from_backoff(self):
        failed = threading.Event()
        calls = []
        class Missing:
            client = None
            def __init__(self, *args): pass
            async def connect(self):
                calls.append(time.monotonic())
                raise RobotProtocolError("no advertisement")
            async def disconnect(self): pass
        client = RobotClient(FakeBLE.address, lambda status, _: failed.set() if status == "offline" else None,
                             protocol_factory=Missing, retry_delay=10)
        client.start()
        thread = client._thread
        try:
            self.assertTrue(failed.wait(2))
            self.assertEqual(len(calls), 1)
            client.retry_now()
            deadline = time.monotonic() + 2
            while (len(calls) < 2 or client.retry_seconds != 20) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(calls), 2)
            self.assertIs(client._thread, thread)
            self.assertEqual(client.retry_seconds, 20)
        finally:
            client.stop()
            self.assertTrue(client.closed.wait(2))
    def test_old_firmware_rejects_theme_without_disconnect_loop(self):
        with FakeBLE(legacy_theme=True) as radio:
            client = RobotClient(radio.address, lambda *_: None, retry_delay=0.01)
            client.set_theme("dark")
            client.start()
            try:
                radio.wait_for("THEME DARK")
                client.set_state(State.PROCESSING, 2)
                radio.wait_for("PROCESS")
                client.set_theme("light")
                client.set_state(State.DONE, 2)
                radio.wait_for("DONE")
                self.assertEqual(radio.sessions, 1)
                self.assertEqual(sum(text.startswith("THEME ") for _, text in radio.commands), 1)
            finally:
                client.stop()
                self.assertTrue(client.closed.wait(3))

    def test_theme_syncs_in_place_and_after_reconnect(self):
        radio = FakeBLE(drop_on="THEME LIGHT")
        with radio:
            client = RobotClient(radio.address, lambda *_: None, retry_delay=0.01, heartbeat=0.1)
            client.set_theme("light")
            client.start()
            try:
                radio.wait_for("THEME LIGHT", session=2)
                client.set_theme("dark")
                radio.wait_for("THEME DARK", session=2)
            finally:
                client.stop()
                self.assertTrue(client.closed.wait(3))
    def test_ble_identifiers_and_old_ip_rejected(self):
        self.assertEqual(validate_address(" " + FakeBLE.address + " "), FakeBLE.address)
        identifier = "a5b82fed-0d6e-4214-b7c3-cb0e37948354"
        self.assertEqual(validate_address(identifier), identifier)
        for value in ("", "192.168.1.42", "192.168.1.42:7777", "robot.local", "AA:BB:CC", "hello world"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_address(value)

    def test_state_restoration_and_progress_does_not_restart_processing(self):
        awake = RobotSnapshot()
        processing = RobotSnapshot(State.PROCESSING, 3, 45)
        self.assertEqual(state_commands(processing, awake), ["RECEIVED 3", "PROCESS", "PROGRESS 45"])
        self.assertEqual(state_commands(RobotSnapshot(State.PROCESSING, 3, 80), processing), ["PROGRESS 80"])
        self.assertEqual(state_commands(processing, processing), [])
        self.assertEqual(state_commands(RobotSnapshot(State.DONE, 3), processing), ["DONE"])
        self.assertEqual(state_commands(RobotSnapshot(State.ERROR, 2), awake), ["RECEIVED 2", "ERROR"])
        self.assertEqual(state_commands(RobotSnapshot(State.SLEEP), processing), ["SLEEP"])

    def test_ble_events_heartbeat_beep_and_graceful_sleep(self):
        with FakeBLE() as server:
            client = RobotClient(server.address, lambda *_: None, heartbeat=0.08, timeout=0.5)
            client.start()
            try:
                server.wait_for("WAKE")
                self.assertTrue(client.connected.wait(1))
                client.set_state(State.RECEIVED, 3)
                server.wait_for("RECEIVED 3")
                client.set_state(State.PROCESSING, 3)
                server.wait_for("PROCESS")
                client.set_progress(45)
                server.wait_for("PROGRESS 45")
                client.set_state(State.PROCESSING, 3)
                client.set_progress(80)
                server.wait_for("PROGRESS 80")
                client.set_state(State.DONE, 3)
                server.wait_for("DONE")
                client.beep()
                server.wait_for("BEEP")
                with server.condition:
                    self.assertTrue(server.condition.wait_for(
                        lambda: sum(text == "PING" for _, text in server.commands) >= 2, 1))
                self.assertEqual(sum(text == "PROCESS" for _, text in server.commands), 1)
            finally:
                client.stop()
                self.assertTrue(client.closed.wait(2))
            server.wait_for("SLEEP")
            self.assertFalse(client.connected.is_set())
            self.assertFalse(any(peer.is_connected for peer in server.clients))

    def test_reconnect_restores_latest_snapshot_in_correct_order(self):
        notifications = []
        with FakeBLE(drop_on="BEEP") as server:
            client = RobotClient(server.address, lambda *event: notifications.append(event),
                                 timeout=0.3, heartbeat=0.1, retry_delay=0.05)
            client.set_state(State.PROCESSING, 2)
            client.set_progress(50)
            client.start()
            try:
                server.wait_for("PROGRESS 50", session=1)
                client.beep()
                server.wait_for("PROGRESS 50", session=2)
                restored = [text for number, text in server.commands if number == 2]
                self.assertEqual(restored[:5], ["PING", "WAKE", "RECEIVED 2", "PROCESS", "PROGRESS 50"])
                self.assertEqual(sum(text == "BEEP" for _, text in server.commands), 1)
                self.assertTrue(any(status == "offline" for status, _ in notifications))
            finally:
                client.stop()
                self.assertTrue(client.closed.wait(2))

    def test_fast_ocr_keeps_state_events_in_order(self):
        with FakeBLE() as server:
            client = RobotClient(server.address, lambda *_: None, timeout=0.5)
            client.start()
            try:
                self.assertTrue(client.connected.wait(1))
                client.set_state(State.RECEIVED, 1)
                client.set_state(State.PROCESSING, 1)
                client.set_progress(100)
                client.set_state(State.DONE, 1)
                server.wait_for("DONE")
                commands = [text for _, text in server.commands]
                self.assertLess(commands.index("RECEIVED 1"), commands.index("PROCESS"))
                self.assertLess(commands.index("PROCESS"), commands.index("DONE"))
            finally:
                client.stop()
                self.assertTrue(client.closed.wait(2))

    def test_wrong_device_gets_no_ocr_commands_and_can_retry(self):
        notifications = []
        with FakeBLE(wrong_first=True) as server:
            client = RobotClient(server.address, lambda *event: notifications.append(event),
                                 timeout=0.3, retry_delay=0.05)
            client.start()
            try:
                server.wait_for("WAKE", session=2)
                self.assertEqual([text for number, text in server.commands if number == 1], ["PING"])
                self.assertTrue(any(status == "offline" for status, _ in notifications))
            finally:
                client.stop()
                self.assertTrue(client.closed.wait(2))

    def test_stop_cancels_discovery_promptly(self):
        with FakeBLE(find_delay=30) as server:
            client = RobotClient(server.address, lambda *_: None)
            client.start()
            self.assertTrue(server.find_started.wait(1))
            client.stop()
            self.assertTrue(client.closed.wait(1))
            self.assertEqual(server.commands, [])

    def test_stop_cancels_an_unanswered_command(self):
        with FakeBLE(no_reply={"PROCESS"}) as server:
            client = RobotClient(server.address, lambda *_: None, timeout=30)
            client.set_state(State.PROCESSING, 1)
            client.start()
            try:
                server.wait_for("PROCESS")
            finally:
                client.stop()
                self.assertTrue(client.closed.wait(2))
            server.wait_for("SLEEP")

    def test_offline_events_restore_only_latest_state(self):
        with FakeBLE(find_delay=0.1) as server:
            client = RobotClient(server.address, lambda *_: None)
            client.set_state(State.RECEIVED, 4)
            client.set_state(State.PROCESSING, 4)
            client.set_progress(70)
            client.set_state(State.DONE, 4)
            client.start()
            try:
                server.wait_for("DONE")
                self.assertNotIn("PROCESS", [text for _, text in server.commands])
                self.assertEqual([text for _, text in server.commands][:4], ["PING", "WAKE", "RECEIVED 4", "DONE"])
            finally:
                client.stop()
                self.assertTrue(client.closed.wait(2))

    def test_preferences_preserve_theme_and_ble_device(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            update_preferences(path, robot_ble_address=FakeBLE.address, robot_ble_name="VietOCR-Assistant")
            save_theme(path, "light")
            self.assertEqual(read_preferences(path)["robot_ble_address"], FakeBLE.address)
            update_preferences(path, robot_ble_address="")
            self.assertEqual(load_theme(path), "light")
            for broken in ("not json", "[]"):
                path.write_text(broken, encoding="utf-8")
                update_preferences(path, robot_ble_address="")
                self.assertEqual(read_preferences(path), {"robot_ble_address": ""})


class BLETransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_winrt_cancel_after_peer_ack_does_not_resend_credentials_or_drop_link(self):
        with FakeBLE() as radio:
            original = radio.client_type.write_gatt_char
            async def cancelled_completion(client, uuid, data, *, response):
                await original(client, uuid, data, response=response)
                if b'\n' in data:
                    raise OSError(-2147023673, 'The operation was canceled by the user.')
            with patch.object(radio.client_type, 'write_gatt_char', cancelled_completion):
                protocol = BLEProtocol(radio.address, timeout=1)
                try:
                    await protocol.connect()
                    self.assertEqual(await protocol.request('PING'), 'PONG')
                    command = 'WIFI PASS ' + '61' * 24
                    await protocol.request(command, expected_prefix='OK WIFI PASS')
                    self.assertEqual(await protocol.request('WAKE'), 'OK WAKE')
                    self.assertEqual(sum(line == command for _, line in radio.commands), 1)
                    self.assertIsNone(protocol._error)
                finally:
                    await protocol.disconnect()

    async def test_winrt_cancel_without_peer_ack_requires_new_session_and_never_replays(self):
        with FakeBLE() as radio:
            async def cancelled(client, uuid, data, *, response):
                raise OSError(-2147023673, 'The operation was canceled by the user.')
            with patch.object(radio.client_type, 'write_gatt_char', cancelled) as write:
                protocol = BLEProtocol(radio.address, timeout=1)
                try:
                    await protocol.connect()
                    with self.assertRaisesRegex(RobotLinkLost, 'chưa nhận ACK'):
                        await protocol.request('PING')
                    with self.assertRaises(RobotLinkLost):
                        await protocol.request('WAKE')
                    self.assertEqual(radio.commands, [])
                finally:
                    await protocol.disconnect()

    async def test_other_driver_errors_are_not_treated_as_a_canceled_write(self):
        with FakeBLE() as radio:
            async def failed(client, uuid, data, *, response): raise OSError(123, 'different failure')
            with patch.object(radio.client_type, 'write_gatt_char', failed):
                protocol = BLEProtocol(radio.address)
                try:
                    await protocol.connect()
                    with self.assertRaises(OSError): await protocol.request('PING')
                finally:
                    await protocol.disconnect()
    async def test_scan_accepts_named_assistant_with_missing_service_advertisement(self):
        with FakeBLE() as radio:
            device, advertisement = radio.advertisement(radio.address, "VietOCR-Assistant", -45)
            advertisement.service_uuids = []
            radio.advertisements = {radio.address: (device, advertisement)}
            self.assertEqual((await scan_robots())[0].address, radio.address)

    async def test_scan_filters_services_and_sorts_signal_strength(self):
        with FakeBLE() as server:
            server.advertisements["second"] = server.advertisement("AA:BB:CC:DD:EE:02", "VietOCR-2", -30)
            server.advertisements["other"] = server.advertisement("AA:BB:CC:DD:EE:03", "Other", -10, ["180f"])
            devices = await scan_robots()
            self.assertEqual([device.name for device in devices], ["VietOCR-2", "VietOCR-Assistant"])
            self.assertIn("-30 dBm", devices[0].description)

    async def test_scan_cancel_releases_scanner(self):
        with FakeBLE(scan_delay=30) as server:
            cancel = threading.Event()
            task = asyncio.create_task(scan_robots(cancel=cancel))
            await asyncio.sleep(0.01)
            cancel.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            self.assertTrue(server.scan_cancelled.is_set())

    async def test_scan_errors_are_reported(self):
        with FakeBLE() as server:
            server.scan_error = RuntimeError("Bluetooth is off")
            with self.assertRaisesRegex(RuntimeError, "Bluetooth is off"):
                await scan_robots()

    async def test_fragmented_notifications_before_write_returns(self):
        with FakeBLE() as server:
            protocol = BLEProtocol(server.address)
            try:
                await protocol.connect()
                await protocol.request("PING")
                await protocol.request("WAKE")
                await protocol.request("RECEIVED 10")
                await protocol.request("PROCESS")
                await protocol.request("PROGRESS 100")
            finally:
                await protocol.disconnect()

    async def test_notification_stream_reassembles_long_and_multiple_lines(self):
        protocol = BLEProtocol(FakeBLE.address)
        status = 'STATUS {"state":"processing","progress":42,"images":10,"muted":false,"demo":false}'
        data = (status + "\r\nPONG\n").encode("ascii")
        for offset in range(0, len(data), 20):
            protocol._notification(TX_UUID, bytearray(data[offset:offset + 20]))
        self.assertEqual(await protocol._lines.get(), status)
        self.assertEqual(await protocol._lines.get(), "PONG")

    async def test_invalid_or_excessive_notification_data_is_rejected(self):
        for data in (b"P\xffNG\n", b"x" * 1025, b"x" * 1025 + b"\n", b"PONG\n" * 20):
            with self.subTest(data=data[:10]), FakeBLE() as server:
                server.reply_override = data
                protocol = BLEProtocol(server.address, timeout=0.2)
                try:
                    await protocol.connect()
                    with self.assertRaises(RobotProtocolError):
                        await protocol.request("PING")
                finally:
                    await protocol.disconnect()

    async def test_missing_reply_times_out(self):
        with FakeBLE(no_reply={"PING"}) as server:
            protocol = BLEProtocol(server.address, timeout=0.05)
            try:
                await protocol.connect()
                with self.assertRaisesRegex(RobotProtocolError, "không phản hồi"):
                    await protocol.request("PING")
            finally:
                await protocol.disconnect()

    async def test_disconnect_wakes_pending_request(self):
        with FakeBLE(drop_on="PING") as server:
            protocol = BLEProtocol(server.address)
            try:
                await protocol.connect()
                with self.assertRaises(ConnectionError):
                    await asyncio.wait_for(protocol.request("PING"), 0.3)
            finally:
                await protocol.disconnect()


if __name__ == "__main__":
    unittest.main()
