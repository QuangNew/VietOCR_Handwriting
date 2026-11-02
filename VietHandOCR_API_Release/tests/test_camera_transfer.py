import struct
import asyncio
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch
from desktop.camera_transfer import CameraMetadata, capture_image
from desktop.bluetooth_transport import RobotCommandRejected


class CameraTransferTests(unittest.IsolatedAsyncioTestCase):
    async def receive(self, *, mtu=23, corrupt=False, wrong_first=False, long_read=False, truncated=False,
                      long_read_error=False, progress=None):
        jpeg = b'\xff\xd8' + bytes(range(256)) * 3 + b'\xff\xd9'
        commands, offsets = [], []
        selector = None
        async def write(_characteristic, data, response):
            nonlocal selector
            selector = struct.unpack('<III', data)
        async def read(_characteristic):
            nonlocal wrong_first
            frame, offset, count = selector
            self.assertLessEqual(count, 480 if long_read else max(14, mtu - 9))
            offsets.append(offset)
            if long_read_error and count > mtu - 9:
                raise RuntimeError('Driver does not assemble long reads')
            if wrong_first:
                wrong_first = False
                return struct.pack('<II', frame, offset + 1) + jpeg[offset:offset+count]
            data = jpeg[offset:offset+count]
            if truncated:
                data = data[:mtu-9]
            if corrupt and offset == 0: data = b'X' + data[1:]
            return struct.pack('<II', frame, offset) + data
        busy = True
        async def request(command, timeout=None, expected_prefix=None):
            nonlocal busy
            commands.append(command)
            if command.startswith('CAM META'):
                if busy:
                    busy = False
                    raise RobotCommandRejected('ERR CAMERA_BUSY: capturing')
                return f'CAM 42 {len(jpeg)} {zlib.crc32(jpeg):08x} 320 240'
            return f'OK {command}'
        protocol = SimpleNamespace(request=request, supports_long_reads=long_read,
                                   client=SimpleNamespace(mtu_size=mtu, write_gatt_char=write, read_gatt_char=read))
        with patch('desktop.camera_transfer.secrets.randbelow', return_value=41):
            result = await capture_image(protocol, on_progress=progress)
        return result, jpeg, commands, offsets

    async def test_minimum_mtu_and_negotiated_mtu_preserve_bytes(self):
        for mtu in (23, 247, 517):
            (metadata, actual), jpeg, commands, _ = await self.receive(mtu=mtu)
            self.assertEqual(actual, jpeg)
            self.assertEqual(metadata.id, 42)
            self.assertEqual(commands[-1], 'CAM RELEASE 42')

    async def test_windows_long_read_avoids_tiny_selector_writes(self):
        progress = []
        (_, actual), jpeg, _, offsets = await self.receive(long_read=True, progress=lambda *value: progress.append(value))
        self.assertEqual(actual, jpeg)
        self.assertEqual(offsets, [0, 480])
        self.assertEqual(progress[0], (0, len(jpeg)))
        self.assertEqual(progress[-1], (len(jpeg), len(jpeg)))

    async def test_truncated_long_read_falls_back_without_losing_image_bytes(self):
        (_, actual), jpeg, _, offsets = await self.receive(long_read=True, truncated=True)
        self.assertEqual(actual, jpeg)
        self.assertEqual(offsets[:2], [0, 0])

    async def test_long_read_driver_error_falls_back_without_restarting_capture(self):
        (_, actual), jpeg, commands, offsets = await self.receive(long_read=True, long_read_error=True)
        self.assertEqual(actual, jpeg)
        self.assertEqual(offsets[:2], [0, 0])
        self.assertEqual(sum(command.startswith('CAM SHOT') for command in commands), 1)

    async def test_timeout_reports_received_bytes_and_releases_snapshot(self):
        commands = []
        async def request(command, **kwargs):
            commands.append(command)
            if command.startswith('CAM META'):
                return 'CAM 42 100 0 320 240'
        async def write(*args, **kwargs):
            pass
        async def read(*args):
            raise TimeoutError('simulated ATT read timeout')
        protocol = SimpleNamespace(request=request, client=SimpleNamespace(mtu_size=23,
                                    write_gatt_char=write, read_gatt_char=read))
        with patch('desktop.camera_transfer.secrets.randbelow', return_value=41):
            with self.assertRaisesRegex(TimeoutError, '0/100 byte'):
                await capture_image(protocol)
        self.assertEqual(commands[-1], 'CAM RELEASE 42')

    async def test_wrong_offset_retries_same_chunk_before_advancing(self):
        _, _, _, offsets = await self.receive(wrong_first=True)
        self.assertEqual(offsets[:2], [0, 0])

    async def test_corruption_never_reaches_ocr(self):
        with self.assertRaisesRegex(ValueError, 'CRC32'):
            await self.receive(corrupt=True)

    async def test_metadata_rejects_oversize_and_wrong_frame(self):
        for line in ('CAM 42 2097153 0 320 240', 'CAM 41 100 0 320 240', 'CAM 42 100 0 99999 240'):
            with self.assertRaises(ValueError): CameraMetadata.parse(line, 42)

    async def test_cancelled_transfer_does_not_wait_for_release_ack(self):
        entered = asyncio.Event()
        commands = []
        async def request(command, timeout=None, expected_prefix=None):
            commands.append(command)
            if command.startswith('CAM META'): return 'CAM 42 100 0 320 240'
        async def write(*args, **kwargs): pass
        async def read(*args):
            entered.set()
            await asyncio.Future()
        protocol = SimpleNamespace(request=request, client=SimpleNamespace(mtu_size=23, write_gatt_char=write, read_gatt_char=read))
        with patch('desktop.camera_transfer.secrets.randbelow', return_value=41):
            task = asyncio.create_task(capture_image(protocol))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(any(command.startswith('CAM RELEASE') for command in commands))
