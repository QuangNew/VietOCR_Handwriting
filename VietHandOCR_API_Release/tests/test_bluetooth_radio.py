import asyncio
import unittest
from enum import IntEnum
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from desktop.bluetooth_radio import begin_bluetooth_access, enable_bluetooth, open_bluetooth_settings


class State(IntEnum):
    ON = 1
    OFF = 2
    DISABLED = 3


class Kind(IntEnum):
    WI_FI = 1
    BLUETOOTH = 3


class Access(IntEnum):
    ALLOWED = 1
    DENIED = 2


class BluetoothRadioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.radio = SimpleNamespace(kind=Kind.BLUETOOTH, state=State.OFF, set_state_async=AsyncMock())
        self.backend = SimpleNamespace(get_radios_async=AsyncMock(return_value=[self.radio]),
                                       request_access_async=AsyncMock(return_value=Access.ALLOWED))
        self.platform = patch("desktop.bluetooth_radio.sys.platform", "win32")
        self.provider = patch("desktop.bluetooth_radio._windows_backend", return_value=(self.backend, Access, Kind, State))
        self.platform.start()
        self.provider.start()
        self.addCleanup(self.platform.stop)
        self.addCleanup(self.provider.stop)

    async def test_enables_only_bluetooth_and_confirms_effective_state(self):
        wifi = SimpleNamespace(kind=Kind.WI_FI, state=State.OFF, set_state_async=AsyncMock())
        self.backend.get_radios_async.return_value.append(wifi)

        async def turn_on(state):
            self.radio.state = state
            return Access.ALLOWED

        self.radio.set_state_async.side_effect = turn_on
        result = await enable_bluetooth()
        self.assertTrue(result.enabled)
        self.radio.set_state_async.assert_awaited_once_with(State.ON)
        wifi.set_state_async.assert_not_awaited()

    async def test_already_on_does_not_request_permission_or_toggle(self):
        self.radio.state = State.ON
        self.assertTrue((await enable_bluetooth()).enabled)
        self.backend.request_access_async.assert_not_awaited()
        self.radio.set_state_async.assert_not_awaited()

    async def test_ui_consent_callback_is_used_when_bluetooth_needs_enabling(self):
        request = AsyncMock(return_value=Access.ALLOWED)

        async def turn_on(state):
            self.radio.state = state
            return Access.ALLOWED

        self.radio.set_state_async.side_effect = turn_on
        self.assertTrue((await enable_bluetooth(request_access=request)).enabled)
        request.assert_awaited_once_with()
        self.backend.request_access_async.assert_not_called()

    async def test_ui_consent_callback_is_not_used_for_on_or_locked_radios(self):
        request = AsyncMock(return_value=Access.ALLOWED)
        self.radio.state = State.ON
        self.assertTrue((await enable_bluetooth(request_access=request)).enabled)
        self.radio.state = State.DISABLED
        self.assertFalse((await enable_bluetooth(request_access=request)).enabled)
        request.assert_not_called()

    async def test_begin_access_calls_winrt_now_and_returns_operation_without_blocking(self):
        operation = begin_bluetooth_access()
        self.backend.request_access_async.assert_called_once_with()
        self.backend.request_access_async.assert_not_awaited()
        self.assertEqual(await operation, Access.ALLOWED)

    async def test_permission_denied_offers_settings_without_changing_radio(self):
        self.backend.request_access_async.return_value = Access.DENIED
        result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertTrue(result.open_settings)
        self.radio.set_state_async.assert_not_awaited()

    async def test_missing_adapter_or_hardware_lock_does_not_claim_success(self):
        self.backend.get_radios_async.return_value = []
        self.assertFalse((await enable_bluetooth()).enabled)
        self.backend.get_radios_async.return_value = [self.radio]
        self.radio.state = State.DISABLED
        result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertTrue(result.open_settings)
        self.backend.request_access_async.assert_not_awaited()
        self.radio.set_state_async.assert_not_awaited()

    async def test_wifi_only_is_not_mistaken_for_bluetooth(self):
        wifi = SimpleNamespace(kind=Kind.WI_FI, state=State.ON, set_state_async=AsyncMock())
        self.backend.get_radios_async.return_value = [wifi]
        result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertTrue(result.open_settings)
        self.backend.request_access_async.assert_not_awaited()
        wifi.set_state_async.assert_not_awaited()

    async def test_state_change_denied_does_not_claim_success(self):
        self.radio.set_state_async.return_value = Access.DENIED
        result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertTrue(result.open_settings)

    async def test_disabled_adapter_does_not_hide_an_available_adapter(self):
        disabled = SimpleNamespace(kind=Kind.BLUETOOTH, state=State.DISABLED, set_state_async=AsyncMock())
        self.backend.get_radios_async.return_value.insert(0, disabled)

        async def turn_on(state):
            self.radio.state = state
            return Access.ALLOWED

        self.radio.set_state_async.side_effect = turn_on
        self.assertTrue((await enable_bluetooth()).enabled)
        disabled.set_state_async.assert_not_awaited()

    async def test_delayed_hardware_state_is_confirmed_before_success(self):
        self.radio.set_state_async.return_value = Access.ALLOWED

        async def settle(_):
            self.radio.state = State.ON

        with patch("desktop.bluetooth_radio.asyncio.sleep", side_effect=settle) as sleep:
            self.assertTrue((await enable_bluetooth()).enabled)
        sleep.assert_awaited_once()

    async def test_accepted_request_without_state_change_is_not_reported_as_on(self):
        self.radio.set_state_async.return_value = Access.ALLOWED
        with patch("desktop.bluetooth_radio.asyncio.sleep", new_callable=AsyncMock):
            result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertTrue(result.open_settings)

    async def test_os_error_falls_back_to_settings(self):
        self.backend.get_radios_async.side_effect = OSError("radio access failed")
        with self.assertLogs("vietocr_desktop.bluetooth", level="ERROR"):
            result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertTrue(result.open_settings)
        self.assertIn("radio access failed", result.message)

    async def test_timeout_offers_a_readable_settings_fallback(self):
        self.backend.get_radios_async.side_effect = TimeoutError()
        with self.assertLogs("vietocr_desktop.bluetooth", level="WARNING"):
            result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertTrue(result.open_settings)
        self.assertIn("quá lâu", result.message)
        self.radio.set_state_async.assert_not_awaited()

    async def test_missing_optional_windows_dependency_does_not_crash(self):
        with patch("desktop.bluetooth_radio._windows_backend", side_effect=ImportError("missing winrt")):
            with self.assertLogs("vietocr_desktop.bluetooth", level="ERROR"):
                result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertTrue(result.open_settings)
        self.assertIn("requirements.txt", result.message)

    async def test_cancellation_is_not_converted_to_a_settings_launch(self):
        self.backend.get_radios_async.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await enable_bluetooth()

    async def test_non_windows_does_not_import_windows_api(self):
        with patch("desktop.bluetooth_radio.sys.platform", "linux"):
            with patch("desktop.bluetooth_radio._windows_backend") as provider:
                result = await enable_bluetooth()
        self.assertFalse(result.enabled)
        self.assertFalse(result.open_settings)
        provider.assert_not_called()

    async def test_settings_fallback_opens_only_the_bluetooth_settings_page(self):
        with patch("desktop.bluetooth_radio.os.startfile", create=True) as start:
            open_bluetooth_settings()
        start.assert_called_once_with("ms-settings:bluetooth")


if __name__ == "__main__":
    unittest.main()
