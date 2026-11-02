import asyncio
import io
import unittest
import zlib
from urllib.error import HTTPError, URLError
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch
from desktop.bluetooth_transport import RobotCommandRejected
from desktop.wifi_camera import WifiEndpoint, WifiState, wifi_state, wifi_commands, fetch_jpeg, capture_fast, wifi_scan, wifi_status, wifi_configure, check_http, open_preview

TOKEN = 'a' * 32

class Response(io.BytesIO):
    def __init__(self, data, declared=None, content_type='image/jpeg'):
        super().__init__(data)
        self.headers = Message()
        self.headers['Content-Length'] = str(len(data) if declared is None else declared)
        self.headers['Content-Type'] = content_type


class WifiTransportTests(unittest.TestCase):
    def test_public_status_displays_current_and_saved_network_without_token(self):
        name = 'Nhà Việt'.encode().hex()
        state = WifiState.parse(f'WIFI STATUS READY 192.168.100.173 {TOKEN} {name}', f'WIFI SAVED 1 {name}')
        self.assertIn('Nhà Việt', state.summary)
        self.assertIn('192.168.100.173', state.summary)
        self.assertIn('Tự kết nối', state.detail)
        self.assertNotIn(TOKEN, repr(state))
        self.assertEqual(state.state, 'ready')

    def test_offline_joining_and_unconfigured_are_distinct(self):
        offline = WifiState.parse('WIFI STATUS OFFLINE 4 202', 'WIFI SAVED 1 61')
        self.assertIn('tự thử lại', offline.detail)
        self.assertIn('Xác thực', offline.detail)
        joining = WifiState.parse('WIFI STATUS JOINING 6 202', 'WIFI SAVED 1 61')
        self.assertIn('đang kết nối', joining.summary)
        self.assertNotIn('Xác thực', joining.detail)
        self.assertIn('chưa được cấu hình', WifiState.parse('WIFI STATUS OFFLINE 6 0').summary)

    def test_connection_reason_is_not_hidden_by_generic_urlerror(self):
        failure = ConnectionRefusedError(10061, 'Connection refused')
        with patch('desktop.wifi_camera.build_opener', return_value=SimpleNamespace(open=lambda *a, **k: (_ for _ in ()).throw(URLError(failure)))):
            with self.assertRaisesRegex(ValueError, '192.168.1.2:80.*10061'):
                fetch_jpeg(WifiEndpoint('192.168.1.2', TOKEN), '/preview')

    def test_health_checks_http_and_does_not_log_token(self):
        data = b'{"http":true,"ip":"192.168.1.2","firmware":"2.1.0-wifi"}'
        with patch('desktop.wifi_camera.build_opener', return_value=SimpleNamespace(open=lambda *a, **k: Response(data))):
            self.assertEqual(check_http(WifiEndpoint('192.168.1.2', TOKEN))['firmware'], '2.1.0-wifi')

    def test_credentials_utf8_boundaries_fit_original_firmware_receiver(self):
        commands = wifi_commands('Việt OCR', 'mật khẩu wifi 123')
        self.assertTrue(all(len(command.encode()) + 1 <= 80 for command in commands))
        self.assertEqual(bytes.fromhex(commands[0].split()[-1]).decode(), 'Việt OCR')
        for invalid in [('', ''), ('x' * 33, ''), ('abc', '123'), ('abc', 'x' * 64)]:
            with self.assertRaises(ValueError): wifi_commands(*invalid)
        self.assertEqual(wifi_commands('open', '')[-1], 'WIFI JOIN')
        self.assertEqual(len(wifi_commands('x' * 32, 'x' * 63)), 5)

    def test_endpoint_rejects_public_hosts_and_token_not_in_repr(self):
        endpoint = WifiEndpoint.parse(f'WIFI STATUS READY 192.168.1.2 {TOKEN} 616263')
        self.assertNotIn(TOKEN, repr(endpoint))
        for invalid in [f'WIFI STATUS READY example.com {TOKEN} 61', f'WIFI STATUS READY 8.8.8.8 {TOKEN} 61', 'WIFI STATUS OFFLINE 6']:
            with self.assertRaises(ValueError): WifiEndpoint.parse(invalid)

    def test_authenticated_jpeg_progress_and_response_limits(self):
        jpeg = b'\xff\xd8' + b'x' * 1024 + b'\xff\xd9'
        progress, requests = [], []
        def open_request(request, timeout):
            requests.append(request)
            return Response(jpeg)
        with patch('desktop.wifi_camera.build_opener', return_value=SimpleNamespace(open=open_request)):
            self.assertEqual(fetch_jpeg(WifiEndpoint('192.168.1.2', TOKEN), '/preview', lambda *row: progress.append(row)), jpeg)
        self.assertEqual(requests[0].get_header('Authorization'), f'Bearer {TOKEN}')
        self.assertNotIn(TOKEN, requests[0].full_url)
        self.assertEqual(progress[-1], (len(jpeg), len(jpeg)))
        for response in [Response(jpeg, len(jpeg) + 1), Response(jpeg, 3*1024*1024), Response(jpeg, content_type='text/html')]:
            with patch('desktop.wifi_camera.build_opener', return_value=SimpleNamespace(open=lambda *a, **k: response)):
                with self.assertRaises(ValueError): fetch_jpeg(WifiEndpoint('192.168.1.2', TOKEN), '/preview')


class WifiWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_orientation_is_applied_before_open_and_rejected_without_starting_stream(self):
        commands = []
        async def request(command, **kwargs):
            commands.append(command)
            if command == 'WIFI STATUS': return f'WIFI STATUS READY 127.0.0.1 {TOKEN} 61'
            return f'OK {command}'
        protocol = SimpleNamespace(request=request)
        with patch('desktop.wifi_camera.check_http'):
            await open_preview(protocol, mirror=True, flip=False)
        self.assertEqual(commands, ['WIFI STATUS', 'CAM ORIENT 1 0', 'CAM OPEN'])
        commands.clear()
        async def older(command, **kwargs):
            if command.startswith('CAM ORIENT'):
                commands.append(command)
                raise RobotCommandRejected('ERR CAMERA_REQUEST: old firmware')
            return await request(command, **kwargs)
        with patch('desktop.wifi_camera.check_http'):
            with self.assertRaisesRegex(ValueError, '2.5.0'):
                await open_preview(SimpleNamespace(request=older), mirror=True, flip=True)
        self.assertNotIn('CAM OPEN', commands)

    async def test_background_status_never_scans_connects_or_requires_camera_http(self):
        commands = []
        async def request(command, **kwargs):
            commands.append(command)
            return {'WIFI STATUS': f'WIFI STATUS READY 192.168.1.2 {TOKEN} 61',
                    'WIFI SAVED': 'WIFI SAVED 1 61'}[command]
        with patch('desktop.wifi_camera.check_http', side_effect=ValueError('sensor failed')) as health:
            result = await wifi_state(SimpleNamespace(request=request))
        self.assertEqual(result.state, 'ready')
        self.assertEqual(commands, ['WIFI STATUS', 'WIFI SAVED'])
        health.assert_not_called()

    async def test_preview_checks_lan_before_starting_sensor(self):
        commands = []
        async def request(command, **kwargs):
            commands.append(command)
            return f'WIFI STATUS READY 127.0.0.1 {TOKEN} 61'
        protocol = SimpleNamespace(request=request)
        with patch('desktop.wifi_camera.check_http', side_effect=ValueError('HTTP refused')):
            with self.assertRaisesRegex(ValueError, 'HTTP refused'):
                await open_preview(protocol)
        self.assertEqual(commands, ['WIFI STATUS'])
        commands.clear()
        with patch('desktop.wifi_camera.check_http'):
            self.assertEqual((await open_preview(protocol)).ip, '127.0.0.1')
        self.assertEqual(commands, ['WIFI STATUS', 'CAM OPEN'])

    async def test_scan_error_keeps_robot_link_and_subsequent_theme_working(self):
        from desktop.bluetooth_transport import BLEProtocol
        from desktop.robot_connection import RobotClient
        from test_robot_connection import FakeBLE
        class OlderFirmware(BLEProtocol):
            async def request(self, command, *args, **kwargs):
                if command.startswith('WIFI '): raise RobotCommandRejected('ERR INVALID_COMMAND: send HELP')
                return await super().request(command, *args, **kwargs)
        events = []
        with FakeBLE() as radio:
            link = RobotClient(radio.address, lambda *args: None, protocol_factory=OlderFirmware,
                on_camera=lambda *args: events.append(args))
            link.start()
            try:
                self.assertTrue(await asyncio.to_thread(link.connected.wait, 3))
                self.assertTrue(link.wifi('wifi_scan'))
                for _ in range(100):
                    if events: break
                    await asyncio.sleep(.02)
                self.assertTrue(events)
                self.assertIn('esp32-s3-cam-ov5640', events[0][2])
                self.assertTrue(link.connected.is_set())
                link.set_theme('light')
                for _ in range(100):
                    if any(line == 'THEME LIGHT' for _, line in radio.commands): break
                    await asyncio.sleep(.02)
                self.assertTrue(any(line == 'THEME LIGHT' for _, line in radio.commands))
                self.assertEqual(radio.sessions, 1)
            finally:
                link.stop()
                self.assertTrue(await asyncio.to_thread(link.closed.wait, 3))

    async def test_unsupported_firmware_names_update_and_leaves_transport_usable(self):
        commands = []
        async def request(command, **kwargs):
            commands.append(command)
            if command == 'PING': return 'PONG'
            raise RobotCommandRejected('ERR INVALID_COMMAND: send HELP')
        protocol = SimpleNamespace(request=request)
        for operation in (wifi_scan(protocol), wifi_status(protocol), wifi_configure(protocol, 'Test', '12345678')):
            with self.assertRaisesRegex(ValueError, 'esp32-s3-cam-ov5640'):
                await operation
        self.assertFalse(any(command.startswith('WIFI PASS ') for command in commands))
        self.assertEqual(await protocol.request('PING'), 'PONG')

    async def test_scan_failure_and_busy_are_distinguished_from_empty_scan(self):
        for error in ('ERR WIFI_SCAN_FAILED: scan failed', 'ERR WIFI_BUSY: connecting'):
            async def request(command, **kwargs):
                if command == 'WIFI SCAN' and 'WIFI_SCAN_FAILED' in error: return 'OK WIFI SCAN'
                raise RobotCommandRejected(error)
            with self.assertRaises(ValueError): await wifi_scan(SimpleNamespace(request=request))

    async def test_wifi_failure_does_not_take_second_photo_or_drop_ble(self):
        commands = []
        jpeg = b'\xff\xd8test\xff\xd9'
        async def request(command, **options):
            commands.append(command)
            if command == 'WIFI STATUS': return f'WIFI STATUS READY 192.168.1.2 {TOKEN} 61'
            if command.startswith('CAM META '):
                frame_id = command.split()[-1]
                return f'CAM {frame_id} {len(jpeg)} {zlib.crc32(jpeg):08x} 2048 1536'
            return f'OK {command}'
        protocol = SimpleNamespace(request=request)
        for data in [jpeg, jpeg[:-1] + b'Z']:
            with patch('desktop.wifi_camera.fetch_jpeg', return_value=data), patch('desktop.wifi_camera.check_http'):
                if data == jpeg:
                    metadata, result = await capture_fast(protocol)
                    self.assertEqual((metadata.width, metadata.height, result), (2048, 1536, jpeg))
                else:
                    with self.assertRaises(ValueError): await capture_fast(protocol)
        self.assertEqual(sum(command.startswith('CAM SHOT ') for command in commands), 2)
        self.assertEqual(sum(command.startswith('CAM RELEASE ') for command in commands), 2)

    async def test_offline_or_older_firmware_does_not_start_a_slow_ble_photo(self):
        async def request(*args, **kwargs): raise RobotCommandRejected('ERR INVALID_COMMAND')
        with patch('desktop.camera_transfer.capture_image') as capture:
            with self.assertRaisesRegex(ValueError, 'esp32-s3-cam-ov5640'):
                await capture_fast(SimpleNamespace(request=request))
            capture.assert_not_called()
        commands = []
        async def offline(command, **kwargs): commands.append(command); return 'WIFI STATUS OFFLINE 6'
        with self.assertRaises(ValueError): await capture_fast(SimpleNamespace(request=offline))
        self.assertEqual(commands, ['WIFI STATUS'])

    async def test_http_health_failure_happens_before_shutter(self):
        commands = []
        async def request(command, **kwargs): commands.append(command); return f'WIFI STATUS READY 192.168.1.2 {TOKEN} 61'
        with patch('desktop.wifi_camera.check_http', side_effect=ValueError('HTTP 10061')):
            with self.assertRaisesRegex(ValueError, '10061'): await capture_fast(SimpleNamespace(request=request))
        self.assertEqual(commands, ['WIFI STATUS'])

    async def test_scan_is_async_and_preserves_unicode_names(self):
        commands = []
        async def request(command, **kwargs):
            commands.append(command)
            if command == 'WIFI COUNT': return 'WIFI COUNT 1'
            if command == 'WIFI NET 0': return 'WIFI NET 0 -50 1 ' + 'Wi-Fi Việt'.encode().hex()
            return 'OK WIFI SCAN'
        rows = await wifi_scan(SimpleNamespace(request=request))
        self.assertEqual(rows, [('Wi-Fi Việt', -50, True)])


if __name__ == '__main__': unittest.main()
