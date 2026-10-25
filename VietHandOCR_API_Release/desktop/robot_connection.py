"""Persistent BLE connection to the ESP32. No Bluetooth I/O runs on Tk's thread."""

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

from .bluetooth_transport import BLEProtocol, RobotCommandRejected, validate_address
from .bluetooth_coordinator import radio_access
from .domain import AssistantState
LOGGER = logging.getLogger("vietocr_desktop.ble")


@dataclass(frozen=True)
class RobotSnapshot:
    state: AssistantState = AssistantState.AWAKE
    images: int = 0
    progress: int | None = None


def state_commands(current: RobotSnapshot, previous: RobotSnapshot) -> list[str]:
    """Send actual events; coalesce progress and restore the latest state on reconnect."""
    if current == previous:
        return []
    if current.state == AssistantState.SLEEP:
        return ["SLEEP"]
    if current.state == AssistantState.AWAKE:
        return ["WAKE"]
    commands = []
    changed = current.state != previous.state or current.images != previous.images
    if current.images and (current.state == AssistantState.RECEIVED or current.images != previous.images):
        if changed:
            commands.append(f"RECEIVED {current.images}")
    if current.state == AssistantState.PROCESSING:
        if changed:
            commands.append("PROCESS")
        if current.progress is not None and (changed or current.progress != previous.progress):
            commands.append(f"PROGRESS {current.progress}")
    elif current.state in (AssistantState.DONE, AssistantState.ERROR) and changed:
        commands.append("DONE" if current.state == AssistantState.DONE else "ERROR")
    return commands


class _StopRequested(Exception):
    pass


class RobotClient:
    def __init__(self, address: str, on_status, *, name: str = "VietOCR-Assistant",
                 timeout: float = 2.0, heartbeat: float = 4.0, retry_delay: float = 3.0,
                 protocol_factory=BLEProtocol, radio_lock=None):
        self.address = validate_address(address)
        self.name = name
        self._on_status = on_status
        self._timeout, self._heartbeat, self._retry_delay = timeout, heartbeat, retry_delay
        self._protocol_factory = protocol_factory
        self._radio_lock = radio_lock
        self._snapshot = RobotSnapshot()
        self._theme = None
        self._pending_states: deque[RobotSnapshot] = deque(maxlen=32)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._beep = threading.Event()
        self._retry_requested = threading.Event()
        self._failures = 0
        self.closed = threading.Event()
        self.connected = threading.Event()
        self._thread = None
        self._notification = None
        self._loop = None
        self._async_changed = None
        self._async_stop = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="VietOCR-BLE", daemon=True)
            self._thread.start()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    @property
    def status(self) -> str:
        return self._notification[0] if self._notification else "connecting"

    def retry_now(self) -> None:
        if not self.stopping and self.status == "offline":
            self._retry_requested.set()
            self._wake_worker()

    def _wake_worker(self) -> None:
        def signal():
            self._async_changed.set()
            if self._stop.is_set():
                self._async_stop.set()
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(signal)
            except RuntimeError:
                pass  # The event loop already closed.

    def set_state(self, state: AssistantState, images: int = 0) -> None:
        images = max(0, min(10, images)) if state not in (AssistantState.AWAKE, AssistantState.SLEEP) else 0
        with self._lock:
            progress = self._snapshot.progress if state == self._snapshot.state == AssistantState.PROCESSING else None
            snapshot = RobotSnapshot(state, images, progress)
            if snapshot != self._snapshot and self.connected.is_set():
                self._pending_states.append(snapshot)
            self._snapshot = snapshot
        self._wake_worker()

    def set_progress(self, value: int) -> None:
        with self._lock:
            if self._snapshot.state != AssistantState.PROCESSING:
                return
            self._snapshot = RobotSnapshot(self._snapshot.state, self._snapshot.images, max(0, min(100, int(value))))
            if self._pending_states and self._pending_states[-1].state == AssistantState.PROCESSING:
                self._pending_states[-1] = self._snapshot
        self._wake_worker()

    def beep(self) -> None:
        if self.connected.is_set():
            self._beep.set()
            self._wake_worker()

    def set_theme(self, theme: str) -> None:
        if theme not in ("light", "dark"):
            raise ValueError("Unknown assistant theme")
        with self._lock:
            self._theme = theme
        self._wake_worker()

    def stop(self) -> None:
        if not self._stop.is_set():
            LOGGER.info("Stop requested: address=%s phase=%s", self.address, self.status)
        self._stop.set()
        self._wake_worker()
        if self._thread is None:
            self.closed.set()

    def _emit(self, status: str, detail: str) -> None:
        if (status, detail) != self._notification:
            LOGGER.info("%s: %s", status, detail)
            self._notification = (status, detail)
            self._on_status(status, detail)

    async def _interruptible(self, coroutine):
        if self._stop.is_set():
            coroutine.close()
            raise _StopRequested
        operation = asyncio.create_task(coroutine)
        stopped = asyncio.create_task(self._async_stop.wait())
        try:
            await asyncio.wait([operation, stopped], return_when=asyncio.FIRST_COMPLETED)
            if self._stop.is_set():
                raise _StopRequested
            return await operation
        finally:
            operation.cancel()
            stopped.cancel()
            await asyncio.gather(operation, stopped, return_exceptions=True)

    async def _wait_for_change(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._async_changed.wait(), timeout)
        except TimeoutError:
            pass

    def _run(self) -> None:
        try:
            asyncio.run(self._run_async())
        finally:
            self.closed.set()

    async def _run_async(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._async_changed, self._async_stop = asyncio.Event(), asyncio.Event()
        if self._stop.is_set():
            self._async_stop.set()
        while not self._stop.is_set():
            self._retry_requested.clear()
            try:
                if self._radio_lock is not None and self._radio_lock.locked():
                    self._emit("waiting", "Đang chờ lượt quét/kết nối Bluetooth trước đóng xong…")
                async with radio_access(self._radio_lock, self._stop):
                    self._emit("connecting", f"Đang kết nối Bluetooth · {self.name} · {self.address}")
                    await self._connect_once()
            except _StopRequested:
                pass
            except asyncio.CancelledError:
                if not self._stop.is_set():
                    raise
            except Exception as exc:
                if not self._stop.is_set():
                    self._failures += 1
                    LOGGER.warning("Connection failed", exc_info=True)
                    reason = str(exc).strip() or "Bật Bluetooth và kiểm tra firmware ESP32."
                    self._emit("offline", f"Chưa kết nối BLE · {reason} Thử lại sau {self.retry_seconds:g} giây.")
            deadline = time.monotonic() + self.retry_seconds
            while not self._stop.is_set() and time.monotonic() < deadline:
                if self._retry_requested.is_set():
                    break
                await self._wait_for_change(min(0.25, max(0.01, deadline - time.monotonic())))
                self._async_changed.clear()

    @property
    def retry_seconds(self) -> float:
        return min(30.0, self._retry_delay * 2 ** min(4, max(0, self._failures - 1)))

    async def _connect_once(self) -> None:
        protocol = self._protocol_factory(self.address, self._timeout)
        try:
            await self._interruptible(protocol.connect())
            # Do not report connected until the correct NUS peer acknowledges.
            await self._interruptible(protocol.request("PING"))
            await self._interruptible(protocol.request("WAKE"))
            self._failures = 0
            previous = RobotSnapshot()
            previous_theme = None
            theme_supported = True
            with self._lock:
                self.connected.set()
            self._emit("connected", f"Đã kết nối BLE · {self.name}")
            next_ping = time.monotonic() + self._heartbeat
            while not self._stop.is_set():
                self._async_changed.clear()
                with self._lock:
                    snapshot = self._pending_states.popleft() if self._pending_states else self._snapshot
                    theme = self._theme
                if theme_supported and theme is not None and theme != previous_theme:
                    try:
                        await self._interruptible(protocol.request(f"THEME {theme.upper()}"))
                    except RobotCommandRejected as exc:
                        if exc.code != "INVALID_COMMAND":
                            raise
                        theme_supported = False
                        self._emit("connected", "Đã kết nối BLE · Nạp firmware mới để đồng bộ giao diện.")
                    previous_theme = theme
                for command in state_commands(snapshot, previous):
                    await self._interruptible(protocol.request(command))
                previous = snapshot
                if self._beep.is_set():
                    self._beep.clear()
                    await self._interruptible(protocol.request("BEEP"))
                if time.monotonic() >= next_ping:
                    await self._interruptible(protocol.request("PING"))
                    next_ping = time.monotonic() + self._heartbeat
                with self._lock:
                    pending = bool(self._pending_states)
                if not pending:
                    await self._interruptible(self._wait_for_change(
                        max(0.01, min(0.25, next_ping - time.monotonic()))))
        finally:
            with self._lock:
                self.connected.clear()
                self._pending_states.clear()
            self._beep.clear()
            if self._stop.is_set() and protocol.client is not None and protocol.client.is_connected:
                try:
                    await protocol.request("SLEEP", timeout=0.5)
                except Exception:
                    pass
            await protocol.disconnect()
