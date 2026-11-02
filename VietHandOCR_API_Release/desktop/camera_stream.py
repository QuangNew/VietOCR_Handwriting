"""Bounded MJPEG reader. No Tk or BLE objects are used by its network thread."""
import http.client
import io
import logging
import queue
import re
import select
import socket
import threading
import time

LOGGER = logging.getLogger('vietocr_desktop.camera')
MAX_FRAME = 2 * 1024 * 1024
MAX_HEADER = 2048
READ_TIMEOUT = 25


class _CancelableReader(io.RawIOBase):
    def __init__(self, sock, stopped):
        self.sock, self.stopped = sock, stopped
        # Keep the socket alive if HTTPConnection detaches a Connection: close
        # response. WinSock shutdown alone may leave an ongoing recv blocked.
        self.raw = sock.makefile('rb', buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        deadline = time.monotonic() + READ_TIMEOUT
        while not self.stopped.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Camera stream idle')
            if select.select([self.sock], [], [], min(.1, remaining))[0]:
                return self.raw.readinto(buffer)
        return 0

    def close(self):
        self.raw.close()
        super().close()


class _ResponseSocket:
    def __init__(self, sock, stopped):
        self.sock, self.stopped = sock, stopped

    def makefile(self, *_args):
        return io.BufferedReader(_CancelableReader(self.sock, self.stopped))


class MjpegParser:
    def __init__(self, content_type):
        match = re.search(r'boundary=(?:"([^"\r\n]+)"|([^;\s]+))', content_type, re.I)
        if not content_type.lower().startswith('multipart/x-mixed-replace') or not match:
            raise ValueError('Camera chưa hỗ trợ MJPEG. Nạp firmware 2.4.1-native trong pbl4.')
        boundary = (match[1] or match[2]).encode('ascii')
        if not 1 <= len(boundary) <= 70:
            raise ValueError('MJPEG boundary không hợp lệ.')
        self.boundary = b'--' + boundary
        self.buffer = bytearray()
        self.wanted = None

    def feed(self, data):
        for start in range(0, len(data), 8192):
            self.buffer.extend(data[start:start + 8192])
            yield from self._drain()

    def _drain(self):
        while True:
            if self.wanted is None:
                # A flushed HTTP preamble and the following MIME part may each
                # contribute CRLF. These are separators, not empty headers.
                while self.buffer.startswith(b'\r\n'):
                    del self.buffer[:2]
                end = self.buffer.find(b'\r\n\r\n')
                if end < 0:
                    if len(self.buffer) > MAX_HEADER:
                        raise ValueError('MJPEG header quá dài.')
                    return
                if end > MAX_HEADER:
                    raise ValueError('MJPEG header quá dài.')
                lines = bytes(self.buffer[:end]).lstrip(b'\r\n').split(b'\r\n')
                del self.buffer[:end + 4]
                if not lines or lines[0] != self.boundary:
                    raise ValueError('MJPEG boundary bị lỗi.')
                headers = {}
                for line in lines[1:]:
                    name, separator, value = line.partition(b':')
                    name = name.strip().lower()
                    if not separator or name in headers:
                        raise ValueError('MJPEG header bị lỗi.')
                    headers[name] = value.strip().lower()
                size = headers.get(b'content-length', b'')
                if not size.isdigit() or len(size) > 9 or headers.get(b'content-type') != b'image/jpeg':
                    raise ValueError('MJPEG thiếu kích thước JPEG hợp lệ.')
                self.wanted = int(size)
                if not 4 <= self.wanted <= MAX_FRAME:
                    raise ValueError('Khung hình xem trước quá lớn.')
            if len(self.buffer) < self.wanted:
                return
            frame = bytes(self.buffer[:self.wanted])
            del self.buffer[:self.wanted]
            self.wanted = None
            if not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9'):
                raise ValueError('Khung hình xem trước sai JPEG.')
            yield frame


class CameraStream:
    """One persistent HTTP connection; keep just the latest frame for the UI."""
    def __init__(self, endpoint, *, port=81):
        self.endpoint = endpoint
        self.port = port
        self.frames = queue.Queue(maxsize=1)
        self.errors = queue.Queue(maxsize=1)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name='VietOCR-MJPEG', daemon=True)
        self._socket = None
        self.stage = 'kết nối TCP'

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stopped.set()
        # shutdown unblocks read1(). HTTPResponse.close() here could wait for
        # its buffered-reader lock and freeze Tk; only the reader owns close().
        sock = self._socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def latest(self):
        try:
            return self.frames.get_nowait()
        except queue.Empty:
            return None

    def error(self):
        try:
            return self.errors.get_nowait()
        except queue.Empty:
            return None

    def _run(self):
        connection = http.client.HTTPConnection(self.endpoint.ip, self.port, timeout=3)
        connection.response_class = lambda sock, **kwargs: http.client.HTTPResponse(
            _ResponseSocket(sock, self.stopped), **kwargs)
        response = None
        count = 0
        start = time.monotonic()
        try:
            connection.connect()
            self._socket = connection.sock
            self._socket.settimeout(READ_TIMEOUT)
            if self.stopped.is_set():
                return
            connection.request('GET', '/stream', headers={
                'Authorization': f'Bearer {self.endpoint.token}', 'Connection': 'close',
            })
            self.stage = 'đợi HTTP header'
            response = connection.getresponse()
            if response.status != 200:
                if response.status == 404:
                    raise ValueError('Nạp firmware 2.4.1-native để xem camera liên tục.')
                raise ValueError(f'Camera stream HTTP {response.status}. Mở lại camera hoặc kết nối lại BLE.')
            parser = MjpegParser(response.getheader('Content-Type', ''))
            self.stage = 'đợi JPEG đầu tiên'
            LOGGER.info('Camera MJPEG HTTP ready: target=%s:%s; waiting for native JPEG', self.endpoint.ip, self.port)
            while not self.stopped.is_set():
                data = response.read1(32768)
                if not data:
                    raise ValueError('Camera đã dừng stream. Nhấn Xem lại camera.')
                for frame in parser.feed(data):
                    if self.stopped.is_set():
                        return
                    try:
                        self.frames.get_nowait()
                    except queue.Empty:
                        pass
                    self.frames.put_nowait(frame)
                    count += 1
                    self.stage = f'nhận JPEG sau {count} khung'
                    if count == 1:
                        LOGGER.info('Camera MJPEG first frame target=%s bytes=%d seconds=%.3f',
                                    self.endpoint.ip, len(frame), time.monotonic() - start)
        except (OSError, http.client.HTTPException, ValueError) as error:
            if not self.stopped.is_set():
                if isinstance(error, (OSError, http.client.HTTPException)):
                    detail = f'Stream :{self.port} · {self.stage}: {type(error).__name__}.'
                    if self.stage == 'kết nối TCP':
                        detail += f' Không mở được cổng {self.port} trên ESP32.'
                    else:
                        # :80 is independent of the streaming socket. Query the
                        # sensor failure, not a blanket "check LAN" diagnosis.
                        from .wifi_camera import check_http
                        try:
                            status = check_http(self.endpoint, timeout=.75)
                            camera = status.get('camera_status', 'không có chẩn đoán')
                            firmware = status.get('firmware', 'cũ')
                            detail += f' ESP32 {firmware} · Camera: {camera}.'
                            if str(camera).startswith('ERROR'):
                                detail = ('Wi-Fi đã kết nối; cảm biến chưa gửi được ảnh JPEG. '
                                          f'ESP32 {firmware} · {camera}. Xem Serial dòng CAMERA DVP TIMEOUT.')
                            else:
                                version = re.match(r'^(\d+)\.(\d+)\.(\d+)', str(firmware))
                                if version is None or tuple(map(int, version.groups())) < (2, 4, 2):
                                    detail += ' Cập nhật firmware 2.4.2-status để kiểm tra driver camera.'
                        except (OSError, ValueError):
                            detail += ' Không đọc được trạng thái camera trên HTTP :80.'
                else:
                    detail = str(error)
                self.errors.put_nowait(detail)
                LOGGER.warning('Camera MJPEG stopped: %s', detail)
        finally:
            if response is not None:
                response.close()
            connection.close()
            self._socket = None
            LOGGER.info('Camera MJPEG closed frames=%d seconds=%.3f', count, time.monotonic() - start)
