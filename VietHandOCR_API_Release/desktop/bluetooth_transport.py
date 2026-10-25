"""Nordic UART Service over BLE. Each connection lives on one asyncio loop."""

import asyncio
import logging
import re
import sys
import threading
from dataclasses import dataclass

SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
LOGGER = logging.getLogger("vietocr_desktop.ble")


def _backend():
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        raise RobotProtocolError("Thiếu Bleak. Chạy pip install -r requirements.txt.") from None
    return BleakScanner, BleakClient


def validate_address(address: str) -> str:
    """Windows/Linux use a MAC; macOS uses a UUID. Never interpret an old IP."""
    address = address.strip()
    if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}|"
                        r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", address):
        raise ValueError("Quét Bluetooth rồi chọn thiết bị VietOCR-Assistant.")
    return address


@dataclass(frozen=True)
class RobotDevice:
    address: str
    name: str
    rssi: int | None = None

    @property
    def description(self) -> str:
        signal = f" · {self.rssi} dBm" if self.rssi is not None else ""
        return f"{self.name} · {self.address}{signal}"


class RobotProtocolError(Exception):
    pass


class RobotCommandRejected(RobotProtocolError):
    def __init__(self, response: str):
        super().__init__(response)
        match = re.match(r"^ERR\s+([^:\s]+)", response)
        self.code = match.group(1) if match else "UNKNOWN"


async def scan_robots(timeout: float = 5.0, *, cancel: threading.Event | None = None) -> list[RobotDevice]:
    scanner, _ = _backend()
    # Some firmware/Windows advertisements expose the name before service UUIDs.
    # Scan broadly, then filter candidates; validate NUS + PING before WAKE.
    operation = asyncio.create_task(scanner.discover(timeout=timeout, return_adv=True))
    try:
        while not operation.done():
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            await asyncio.wait([operation], timeout=0.1)
        discovered = await operation
    finally:
        if not operation.done():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
    devices = {}
    for device, advertisement in discovered.values():
        name = advertisement.local_name or device.name or ""
        if (SERVICE_UUID not in {uuid.lower() for uuid in advertisement.service_uuids}
                and name.casefold() not in ("vietocr-assistant", "vietocr assistant")):
            continue
        name = name or "Thiết bị UART BLE"
        devices[device.address.casefold()] = RobotDevice(device.address, name, advertisement.rssi)
        LOGGER.info("Scan candidate: address=%s name=%s rssi=%s uuids=%s",
                    device.address, name, advertisement.rssi, advertisement.service_uuids)
    LOGGER.info("Scan complete: advertising_devices=%d candidates=%d", len(discovered), len(devices))
    return sorted(devices.values(), key=lambda device: (-(device.rssi if device.rssi is not None else -999),
                                                       device.name, device.address))


class BLEProtocol:
    def __init__(self, address: str, timeout: float = 2.0):
        self.address, self.timeout = validate_address(address), timeout
        self.client = None
        self._buffer = bytearray()
        self._lines = asyncio.Queue(maxsize=16)
        self._error = None

    async def connect(self) -> None:
        scanner, client_type = _backend()
        # Resolve again on this loop; GUI scan results contain only portable IDs.
        LOGGER.info("Resolve target: address=%s, timeout=8s, no advertisement UUID filter", self.address)
        device = await scanner.find_device_by_address(self.address, timeout=8.0)
        if device is None:
            raise RobotProtocolError(f"Không thấy quảng bá BLE từ {self.address} sau 8 giây. "
                                     "Kiểm tra TFT đang Chờ kết nối; nếu vừa nạp firmware, quét và chọn lại thiết bị.")
        LOGGER.info("Target found: address=%s name=%s; opening GATT", device.address, device.name)
        options = {"winrt": {"use_cached_services": False}} if sys.platform == "win32" else {}
        self.client = client_type(device, disconnected_callback=self._disconnected, services=[SERVICE_UUID], **options)
        try:
            await asyncio.wait_for(self.client.connect(), 15.0)
        except TimeoutError:
            raise RobotProtocolError(f"Tìm thấy {self.address} nhưng mở GATT quá 15 giây.") from None
        LOGGER.info("GATT connected: %s; enabling TX notifications", self.address)
        try:
            await asyncio.wait_for(self.client.start_notify(TX_UUID, self._notification), 5.0)
        except TimeoutError:
            raise RobotProtocolError("GATT đã mở nhưng bật Notify TX quá 5 giây. Kiểm tra firmware NUS.") from None
        # Windows can complete CCCD registration before the peer sees it.
        await asyncio.sleep(0.25)
        LOGGER.info("TX notifications ready: %s", self.address)

    def _fail(self, error: Exception) -> None:
        if self._error is None:
            self._error = error
            if not self._lines.full():
                self._lines.put_nowait(error)

    def _disconnected(self, _client) -> None:
        self._fail(ConnectionError("ESP32 đã ngắt Bluetooth."))

    def _notification(self, _characteristic, data: bytearray) -> None:
        if self._error is not None:
            return
        self._buffer.extend(data)
        try:
            while b"\n" in self._buffer:
                line, _, remainder = self._buffer.partition(b"\n")
                if len(line) > 1024:
                    raise RobotProtocolError("Phản hồi ESP32 quá dài.")
                self._buffer = remainder
                decoded = line.rstrip(b"\r").decode("ascii")
                LOGGER.debug("RX %s", decoded)
                self._lines.put_nowait(decoded)
            if len(self._buffer) > 1024:
                raise RobotProtocolError("Phản hồi ESP32 quá dài.")
        except (UnicodeError, asyncio.QueueFull):
            self._fail(RobotProtocolError("Phản hồi Bluetooth không hợp lệ hoặc quá nhiều."))
        except RobotProtocolError as exc:
            self._fail(exc)

    async def request(self, command: str, timeout: float | None = None) -> None:
        if self._error is not None:
            raise self._error
        if not self.client or not self.client.is_connected:
            raise ConnectionError("ESP32 chưa kết nối Bluetooth.")
        if "\n" in command or "\r" in command:
            raise ValueError("One command per request")
        data = (command + "\n").encode("ascii")
        LOGGER.debug("TX %s", command)

        async def exchange():
            # Do not depend on a negotiated MTU; even default MTU 23 works.
            for offset in range(0, len(data), 20):
                await self.client.write_gatt_char(RX_UUID, data[offset:offset + 20], response=True)
            reply = await self._lines.get()
            if self._error is not None:
                raise self._error
            if isinstance(reply, Exception):
                raise reply
            expected = "PONG" if command == "PING" else "OK " + command
            if reply != expected:
                if reply.startswith("ERR "):
                    raise RobotCommandRejected(reply)
                raise RobotProtocolError(reply if reply.startswith("ERR ") else "Sai giao thức VietOCR BLE.")

        try:
            await asyncio.wait_for(exchange(), self.timeout if timeout is None else timeout)
        except TimeoutError:
            raise RobotProtocolError("ESP32 không phản hồi. Kiểm tra firmware và Bluetooth.") from None

    async def disconnect(self) -> None:
        if self.client is not None:
            try:
                LOGGER.info("Closing GATT: %s", self.address)
                await asyncio.wait_for(self.client.disconnect(), 1.2)
            except Exception:
                LOGGER.warning("GATT cleanup did not finish: %s", self.address, exc_info=True)
