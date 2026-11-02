import http.client
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from desktop.camera_stream import CameraStream, MjpegParser, MAX_FRAME, MAX_HEADER
from desktop.wifi_camera import WifiEndpoint

TYPE = 'multipart/x-mixed-replace; boundary="vietocr-frame"'
JPEG = b'\xff\xd8sample--vietocr-frame\r\n\r\npayload\xff\xd9'


def part(jpeg=JPEG):
    return (b'--vietocr-frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
            str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')


class MultipartTests(unittest.TestCase):
    def test_native_high_quality_frame_larger_than_old_preview_limit(self):
        jpeg = b'\xff\xd8' + b'x'*(900*1024) + b'\xff\xd9'
        parser = MjpegParser(TYPE)
        wire = part(jpeg)
        frames = [frame for at in range(0, len(wire), 16384) for frame in parser.feed(wire[at:at+16384])]
        self.assertEqual(frames, [jpeg])
        self.assertLess(len(parser.buffer), MAX_HEADER)

    def test_split_at_every_byte_and_boundary_inside_jpeg(self):
        wire = b'\r\n' + part() + part(b'\xff\xd8second\xff\xd9')
        for split in range(1, len(wire)):
            parser = MjpegParser(TYPE)
            frames = list(parser.feed(wire[:split])) + list(parser.feed(wire[split:]))
            self.assertEqual(frames, [JPEG, b'\xff\xd8second\xff\xd9'])
        parser = MjpegParser(TYPE)
        self.assertEqual([frame for byte in wire for frame in parser.feed(bytes([byte]))],
                         [JPEG, b'\xff\xd8second\xff\xd9'])

    def test_many_frames_in_single_read_do_not_accumulate(self):
        parser = MjpegParser(TYPE)
        self.assertEqual(len(list(parser.feed(part() * 2000))), 2000)
        self.assertLess(len(parser.buffer), MAX_HEADER)

    def test_invalid_or_unbounded_streams_fail(self):
        for content in ('image/jpeg', 'multipart/x-mixed-replace', 'multipart/x-mixed-replace; boundary=' + 'a' * 71):
            with self.subTest(content=content), self.assertRaises(ValueError):
                MjpegParser(content)
        for data in (b'x' * (MAX_HEADER + 1), part(b'not a jpeg'),
                     part().replace(str(len(JPEG)).encode(), str(MAX_FRAME + 1).encode(), 1),
                     part().replace(b'Content-Length:', b'Unknown:'),
                     part().replace(b'Content-Type: image/jpeg', b'Content-Type: text/html'),
                     part().replace(b'Content-Type: image/jpeg', b'Content-Type: image/jpeg\r\nContent-Length: 4')):
            with self.subTest(data=data[:90]), self.assertRaises(ValueError):
                list(MjpegParser(TYPE).feed(data))


class HttpStreamTests(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        self.started = threading.Event()
        self.streams = []
        self.requests = []
        self.status = 200
        self.startup_delay = 0
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                fixture.requests.append((self.path, self.headers.get('Authorization')))
                if self.path == '/health':
                    self.send_response(200)
                    self.send_header('Content-Length', '2')
                    self.end_headers()
                    self.wfile.write(b'OK')
                    return
                self.send_response(fixture.status)
                self.send_header('Content-Type', TYPE)
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                try:
                    if fixture.startup_delay:
                        self.wfile.write(b'2\r\n\r\n\r\n')
                        self.wfile.flush()
                        fixture.release.wait(fixture.startup_delay)
                    # Real chunked HTTP, fragmented across both headers and body.
                    wire = b'\r\n' + part() + part(b'\xff\xd8latest\xff\xd9')
                    for at in range(0, len(wire), 7):
                        chunk = wire[at:at + 7]
                        self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                        self.wfile.flush()
                    fixture.started.set()
                    fixture.release.wait(10)
                    self.wfile.write(b'0\r\n\r\n')
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        for stream in self.streams:
            stream.stop()
            stream.thread.join(2)
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def connect(self):
        stream = CameraStream(WifiEndpoint('127.0.0.1', 'a' * 32), port=self.server.server_port).start()
        self.streams.append(stream)
        return stream

    def test_live_frames_arrive_before_response_ends_and_stop_unblocks_read(self):
        stream = self.connect()
        self.assertTrue(self.started.wait(2))
        deadline = time.monotonic() + 2
        while not stream.frames.qsize() and time.monotonic() < deadline:
            time.sleep(.01)
        # Reader must publish without waiting for the endless HTTP body to end.
        time.sleep(.03)
        self.assertEqual(stream.frames.qsize(), 1)
        self.assertEqual(stream.latest(), b'\xff\xd8latest\xff\xd9')
        self.assertIsNone(stream.latest())
        self.assertFalse(self.release.is_set())
        start = time.monotonic()
        stream.stop()
        self.assertLess(time.monotonic() - start, .2)
        stream.thread.join(1)
        self.assertFalse(stream.thread.is_alive())
        self.assertIsNone(stream.error())
        self.assertEqual(self.requests, [('/stream', 'Bearer ' + 'a' * 32)])

    def test_stream_does_not_block_control_http(self):
        stream = self.connect()
        self.assertTrue(self.started.wait(2))
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=1)
        try:
            connection.request('GET', '/health')
            self.assertEqual(connection.getresponse().read(), b'OK')
            self.assertTrue(stream.thread.is_alive())
        finally:
            connection.close()

    def test_idle_connection_times_out_instead_of_leaving_a_permanent_worker(self):
        with patch('desktop.camera_stream.READ_TIMEOUT', .15):
            stream = self.connect()
            self.assertTrue(self.started.wait(2))
            self.assertIn('TimeoutError', stream.errors.get(timeout=2))
            stream.thread.join(1)
            self.assertFalse(stream.thread.is_alive())

    def test_native_first_frame_can_arrive_after_old_eight_second_cutoff(self):
        self.startup_delay = 8.5
        stream = self.connect()
        self.assertTrue(stream.frames.get(timeout=12).startswith(b'\xff\xd8'))
        self.assertIsNone(stream.error())
        stream.stop()

    def test_sensor_error_is_reported_from_health_after_stream_timeout(self):
        with patch('desktop.camera_stream.READ_TIMEOUT', .15), patch('desktop.wifi_camera.check_http',
                return_value={'firmware': '2.4.1-native', 'camera_status': 'ERROR CAMERA_PREVIEW: FB-OVF'}):
            stream = self.connect()
            error = stream.errors.get(timeout=2)
            self.assertIn('FB-OVF', error)
            self.assertIn('2.4.1-native', error)
            self.assertNotIn('kiểm tra mạng LAN', error)

    def test_unsupported_firmware_explains_upgrade_without_retry_loop(self):
        self.status = 404
        stream = self.connect()
        self.assertIn('2.4.1-native', stream.errors.get(timeout=2))
        stream.thread.join(1)
        self.assertFalse(stream.thread.is_alive())
        self.assertEqual(len(self.requests), 1)

    def test_remote_close_is_reported_and_client_can_reopen(self):
        stream = self.connect()
        self.assertTrue(self.started.wait(2))
        self.release.set()
        self.assertIn('dừng stream', stream.errors.get(timeout=2))
        stream.thread.join(1)
        self.assertFalse(stream.thread.is_alive())
        reopened = self.connect()
        self.assertIn('dừng stream', reopened.errors.get(timeout=2))
        self.assertEqual(len(self.requests), 2)
