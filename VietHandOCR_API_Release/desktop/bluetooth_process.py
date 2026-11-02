"""Keep WinRT/driver code out of the Tk process, including the first scan.

Only portable addresses, strings and scan results cross the pipe. Every native
connection and its asyncio loop stay together in one disposable process.
"""

import asyncio
import logging
import multiprocessing
import signal
import threading
import time
from types import SimpleNamespace

from .bluetooth_transport import BLEProtocol, RobotCommandRejected, RobotProtocolError, RobotLinkLost, validate_address

logger = logging.getLogger("vietocr_desktop.ble_process")


async def _serve(pipe):
    from .bluetooth_transport import scan_robots
    loop = asyncio.get_running_loop()
    requests = asyncio.Queue()
    stopping = asyncio.Event()
    protocol = None

    def deliver(message):
        if message[1] == "close":
            stopping.set()
        else:
            requests.put_nowait(message)

    def read_control():
        # A daemon reader keeps CLOSE responsive while WinRT awaits discovery or
        # GATT. Do not use to_thread(recv): its executor can block process exit.
        while True:
            try:
                message = pipe.recv()
            except (EOFError, OSError):
                message = (0, "close", {})
            try:
                loop.call_soon_threadsafe(deliver, message)
            except RuntimeError:
                return
            if message[1] == "close":
                return

    async def perform(command, data, progress):
        nonlocal protocol
        if command == "scan":
            return await scan_robots(data["timeout"])
        if command == "connect":
            protocol = BLEProtocol(data["address"], data["timeout"])
            await protocol.connect()
            return None
        if command == "request" and protocol is not None:
            return await protocol.request(data["command"], data["timeout"], expected_prefix=data.get("expected_prefix"))
        if command == "capture" and protocol is not None:
            from .wifi_camera import capture_fast
            return await capture_fast(protocol, on_progress=progress)
        if command == 'network' and protocol is not None:
            if data['action'] in ('settings_get','settings_set','settings_focus'):
                from .camera_settings import get_config, apply_config, focus_at
                if data['action']=='settings_get': return await get_config(protocol)
                operation=focus_at if data['action']=='settings_focus' else apply_config
                return await operation(protocol,data['settings'],data.get('persist',True))
            from .wifi_camera import preview, stream_info, open_preview, wifi_scan, wifi_configure, wifi_check, wifi_state, wifi_profiles
            if data['action'] == 'camera_open':
                return await open_preview(protocol, mirror=data.get('mirror'), flip=data.get('flip'))
            if data['action'] == 'preview': return await preview(protocol)
            if data['action'] == 'stream_info': return await stream_info(protocol)
            if data['action'] == 'wifi_scan': return await wifi_scan(protocol)
            if data['action'] == 'wifi_status': return await wifi_check(protocol)
            if data['action'] == 'wifi_state': return await wifi_state(protocol)
            if data['action'] == 'wifi_profiles': return await wifi_profiles(protocol)
            if data['action'] == 'wifi_join': return await wifi_configure(protocol, data['ssid'], data['password'])
        raise RobotProtocolError("Invalid Bluetooth worker operation")

    threading.Thread(target=read_control, name="BLE-control", daemon=True).start()
    stop_task = asyncio.create_task(stopping.wait())
    active = None
    incoming = None
    try:
        while True:
            incoming = asyncio.create_task(requests.get())
            await asyncio.wait([incoming, stop_task], return_when=asyncio.FIRST_COMPLETED)
            if stopping.is_set():
                break
            request_id, command, data = await incoming
            active = asyncio.create_task(perform(command, data, lambda received, total:
                pipe.send({"id": request_id, "progress": (received, total)})))
            await asyncio.wait([active, stop_task], return_when=asyncio.FIRST_COMPLETED)
            if stopping.is_set():
                break
            try:
                value = await active
                pipe.send({"id": request_id, "ok": True, "value": value})
            except Exception as error:
                if isinstance(error, (ValueError, RobotCommandRejected, RobotLinkLost, ConnectionError)):
                    logger.warning("Operation %s rejected: %s", command, error)
                else:
                    logger.exception("Bluetooth worker %s failed", command)
                pipe.send({"id": request_id, "ok": False, "error": str(error), "rejected": isinstance(error, RobotCommandRejected), "recoverable": isinstance(error, ValueError)})
    except (EOFError, OSError):
        pass
    finally:
        for task in (active, incoming, stop_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in (active, incoming, stop_task) if task is not None), return_exceptions=True)
        if protocol is not None:
            await protocol.disconnect()
        logger.info("Bluetooth worker stopped; GATT cleanup finished")


def _worker(pipe):
    # Windows broadcasts Ctrl+C to every process attached to the console.
    # The GUI owns shutdown and sends CLOSE; interrupting asyncio here can
    # otherwise cancel GATT cleanup and print an unrelated KeyboardInterrupt.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    from .diagnostics import configure_logging
    configure_logging(role="bluetooth")
    logger.info("Bluetooth worker started")
    try:
        asyncio.run(_serve(pipe))
    finally:
        pipe.close()


class _Session:
    def __init__(self, *, target=_worker):
        context = multiprocessing.get_context("spawn")
        self.pipe, child = context.Pipe()
        self.process = context.Process(target=target, args=(child,), name="VietOCR-Bluetooth", daemon=True)
        try:
            self.process.start()
        except BaseException:
            self.pipe.close()
            raise
        finally:
            child.close()
        logger.info("Started isolated Bluetooth pid=%s", self.process.pid)
        self.closed = False
        self.interrupted = False
        self.sequence = 0

    async def call(self, command, data, timeout, cancel=None, on_progress=None):
        if self.closed or self.interrupted:
            raise RobotProtocolError("Tiến trình Bluetooth đã đóng.")
        try:
            self.sequence += 1
            request_id = self.sequence
            self.pipe.send((request_id, command, data))
            deadline = time.monotonic() + timeout
            while True:
                if cancel is not None and cancel.is_set():
                    raise asyncio.CancelledError
                if self.pipe.poll():
                    response = self.pipe.recv()
                    if response.get("id") != request_id:
                        logger.debug("Ignoring stale Bluetooth response id=%s, expected=%s", response.get("id"), request_id)
                        continue
                    if "progress" in response:
                        if on_progress:
                            on_progress(*response["progress"])
                        continue
                    if not response["ok"]:
                        error_type = RobotCommandRejected if response["rejected"] else ValueError if response.get('recoverable') else RobotProtocolError
                        raise error_type(response["error"])
                    return response["value"]
                if not self.process.is_alive():
                    code = self.process.exitcode
                    raise RobotProtocolError(f"Tiến trình Bluetooth dừng (exit={code}). Xem .logs/bluetooth-crash.log; giao diện vẫn hoạt động.")
                if time.monotonic() >= deadline:
                    raise RobotProtocolError("Bluetooth không phản hồi đúng hạn. Kiểm tra driver và nguồn ESP32.")
                await asyncio.sleep(0.025)
        except asyncio.CancelledError:
            self.interrupted = True
            raise
        except (EOFError, BrokenPipeError, OSError) as error:
            await asyncio.to_thread(self.process.join, 0.1)
            code = self.process.exitcode
            raise RobotProtocolError(f"Mất tiến trình Bluetooth (exit={code}): {error}. Xem .logs/bluetooth.log.") from error

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.process.is_alive():
                try:
                    self.pipe.send((0, "close", {}))
                except (OSError, EOFError):
                    pass
                await asyncio.to_thread(self.process.join, 2.0)
                if self.process.is_alive():
                    logger.warning("Bluetooth worker shutdown timed out; terminating pid=%s", self.process.pid)
                    self.process.terminate()
            await asyncio.to_thread(self.process.join, 1.0)
            if self.process.is_alive():
                self.process.kill()
                await asyncio.to_thread(self.process.join, 1.0)
        finally:
            self.pipe.close()
            if not self.process.is_alive():
                self.process.close()


async def scan_robots_isolated(timeout=5.0, *, cancel: threading.Event | None = None):
    session = _Session()
    try:
        return await session.call("scan", {"timeout": timeout}, timeout + 10, cancel)
    finally:
        await session.close()


class ProcessBLEProtocol:
    def __init__(self, address, timeout=2.0):
        self.address = validate_address(address)
        self.timeout = timeout
        self.client = None
        self._session = None

    async def connect(self):
        self._session = _Session()
        await self._session.call("connect", {"address": self.address, "timeout": self.timeout}, 35)
        self.client = SimpleNamespace(is_connected=True)

    async def request(self, command, timeout=None, *, expected_prefix=None):
        if self._session is None:
            raise RobotProtocolError("Bluetooth chưa kết nối.")
        duration = self.timeout if timeout is None else timeout
        return await self._session.call("request", {"command": command, "timeout": duration,
                                                  "expected_prefix": expected_prefix}, duration + 5)

    async def capture(self, on_progress=None):
        return await self._session.call("capture", {}, 250, on_progress=on_progress)

    async def network(self, action, **arguments):
        return await self._session.call('network', {'action': action, **arguments}, 35)

    async def disconnect(self):
        if self.client is not None:
            self.client.is_connected = False
        if self._session is not None:
            await self._session.close()
            self._session = None
