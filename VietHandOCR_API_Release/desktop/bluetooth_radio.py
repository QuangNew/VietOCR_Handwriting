"""Turn on a Windows Bluetooth radio only after the user presses the button."""

import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


logger = logging.getLogger("vietocr_desktop.bluetooth")


@dataclass(frozen=True)
class RadioResult:
    enabled: bool
    message: str
    open_settings: bool = False


def _windows_backend():
    from winrt.windows.devices.radios import Radio, RadioAccessStatus, RadioKind, RadioState
    return Radio, RadioAccessStatus, RadioKind, RadioState


def begin_bluetooth_access() -> Awaitable[object]:
    """Start Windows consent from the UI thread; await the result on a worker.

    Do not call ``asyncio.run`` or otherwise block Tk while consent is pending.
    The UI dispatcher should return this WinRT operation to its asyncio worker.
    Windows may still deny consent for an unpackaged desktop app.
    """
    radio_type, _, _, _ = _windows_backend()
    return radio_type.request_access_async()


async def enable_bluetooth(
    request_access: Callable[[], Awaitable[object]] | None = None,
) -> RadioResult:
    """Best-effort radio control; Windows may require its own consent/settings UI.

    Run enumeration/state changes on an asyncio worker so they never block Tk.
    ``request_access`` can marshal consent initiation to the UI thread with
    :func:`begin_bluetooth_access`. Without it, access is requested directly as
    a best-effort fallback. Windows can deny consent for an unpackaged app.
    """
    if sys.platform != "win32":
        return RadioResult(False, "Hãy bật Bluetooth trong cài đặt hệ điều hành rồi bấm Quét Bluetooth.")
    try:
        radio_type, access, kind, state = _windows_backend()
        radios = [radio for radio in await asyncio.wait_for(radio_type.get_radios_async(), 8)
                  if radio.kind == kind.BLUETOOTH]
        if not radios:
            return RadioResult(False, "Windows chưa tìm thấy bộ thu Bluetooth. Kiểm tra thiết bị và driver.", True)
        if any(radio.state == state.ON for radio in radios):
            return RadioResult(True, "Bluetooth đã bật. Đang tìm trợ lý…")
        radio = next((radio for radio in radios if radio.state == state.OFF), None)
        if radio is None:
            return RadioResult(False, "Bluetooth đang bị khóa bởi phần cứng hoặc hệ thống. Kiểm tra Cài đặt Windows.", True)
        permission = await asyncio.wait_for(
            request_access() if request_access is not None else radio_type.request_access_async(), 30)
        if permission != access.ALLOWED:
            return RadioResult(False, "Windows chưa cho phép app bật Bluetooth. Bật trong Cài đặt rồi quét lại.", True)
        result = await asyncio.wait_for(radio.set_state_async(state.ON), 8)
        if result != access.ALLOWED:
            return RadioResult(False, "Windows không cho phép thay đổi Bluetooth. Bật trong Cài đặt rồi thử lại.", True)
        # SetStateAsync accepts a request; verify the radio actually turns on.
        for _ in range(30):
            if radio.state == state.ON:
                return RadioResult(True, "Đã bật Bluetooth. Đang tìm trợ lý…")
            await asyncio.sleep(0.1)
        return RadioResult(False, "Bluetooth chưa bật được. Kiểm tra chế độ máy bay hoặc công tắc phần cứng.", True)
    except TimeoutError:
        logger.warning("Windows Bluetooth radio operation timed out")
        return RadioResult(False, "Windows phản hồi Bluetooth quá lâu. Bật trong Cài đặt rồi quét lại.", True)
    except ImportError:
        logger.exception("Windows Bluetooth radio dependency is unavailable")
        return RadioResult(False, "Thiếu thư viện điều khiển Bluetooth. Cài lại requirements.txt trong .venv hoặc bật trong Cài đặt Windows.", True)
    except Exception as exc:
        logger.exception("Windows Bluetooth radio operation failed")
        return RadioResult(False, f"Không bật được Bluetooth: {exc}. Hãy bật trong Cài đặt Windows.", True)


def open_bluetooth_settings():
    if sys.platform == "win32":
        os.startfile("ms-settings:bluetooth")
