"""BLE setup and authenticated LAN JPEG transport (no cloud or new dependencies)."""
import asyncio
import ipaddress
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field, replace
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from .camera_transfer import MAX_BYTES, CameraMetadata, verify_jpeg
from .bluetooth_transport import RobotCommandRejected

LOGGER = logging.getLogger('vietocr_desktop.camera')
WIFI_FIRMWARE_REQUIRED = (
    'ESP32 đang chạy firmware chưa hỗ trợ Wi-Fi camera. '
    'Nạp profile esp32-s3-cam-ov5640 mới trong pbl4, rồi kết nối BLE lại. '
    'Có thể gửi INFO trong Serial để kiểm tra: cần bản OV5640 3.0.0 trở lên.'
)


async def wifi_request(protocol, command, **kwargs):
    try:
        return await protocol.request(command, **kwargs)
    except RobotCommandRejected as error:
        if error.code == 'INVALID_COMMAND':
            raise ValueError(WIFI_FIRMWARE_REQUIRED) from None
        if error.code == 'WIFI_BUSY':
            raise ValueError('ESP32 đang kết nối Wi-Fi. Đợi tối đa 25 giây, nhấn Kiểm tra kết nối rồi quét lại.') from None
        if error.code == 'WIFI_SCAN_FAILED':
            raise ValueError('ESP32 không hoàn tất quét Wi-Fi. Nhấn Quét mạng để thử lại; nếu vẫn lỗi, xem Serial.') from None
        raise

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class WifiEndpoint:
    ip: str
    token: str = field(repr=False)
    mirror: bool | None = field(default=None,compare=False)
    flip: bool | None = field(default=None,compare=False)

    @classmethod
    def parse(cls, response):
        fields = response.split()
        if len(fields) != 6 or fields[:3] != ['WIFI', 'STATUS', 'READY']:
            detail = ''
            if len(fields) >= 4 and fields[:3] == ['WIFI', 'STATUS', 'OFFLINE']:
                reason = fields[4] if len(fields) > 4 else ''
                if fields[3] == '1' or reason == '201': detail = ' Không tìm thấy mạng đã lưu.'
                elif fields[3] == '4' or reason in ('15', '202', '204'): detail = ' Kiểm tra mật khẩu Wi-Fi.'
            if fields[:3] == ['WIFI', 'STATUS', 'JOINING']:
                raise ValueError('ESP32 đang kết nối Wi-Fi; đợi hoặc mở Wi-Fi camera để chọn mạng khác.')
            raise ValueError('ESP32 chưa vào Wi-Fi.' + detail + ' Mở Wi-Fi camera, chọn mạng 2.4 GHz rồi kết nối.')
        ip = ipaddress.IPv4Address(fields[3])
        if not ip.is_private or ip.is_unspecified or ip.is_multicast or not re.fullmatch('[0-9a-f]{32}', fields[4]):
            raise ValueError('Địa chỉ Wi-Fi camera không hợp lệ.')
        return cls(str(ip), fields[4])


def wifi_name(value):
    if value == '-':
        return ''
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}){1,32}', value):
        raise ValueError('Tên Wi-Fi ESP32 trả về không hợp lệ.')
    return bytes.fromhex(value).decode('utf-8', errors='replace')


@dataclass(frozen=True)
class WifiState:
    """Public connection state, deliberately contains no password/session token."""
    state: str = 'unknown'
    ssid: str = ''
    ip: str = ''
    saved_ssid: str = ''
    reason: str = ''

    @property
    def summary(self):
        if self.state == 'ready':
            return f'Wi-Fi đã kết nối · {self.ssid} · IP {self.ip}'
        if self.state == 'joining':
            return f'Wi-Fi đang kết nối · {self.saved_ssid or "mạng đã cấu hình"}'
        if self.state == 'offline':
            return f'Wi-Fi chưa kết nối · {self.saved_ssid}' if self.saved_ssid else 'Wi-Fi chưa được cấu hình'
        return 'Wi-Fi · Đang đọc trạng thái từ ESP32…'

    @property
    def detail(self):
        saved = (f'Mạng đã lưu trên ESP32: {self.saved_ssid}. Tự kết nối lại khi khởi động / kết nối BLE.'
                 if self.saved_ssid else 'Chưa có mạng lưu trên ESP32. Chọn hoặc nhập Wi-Fi 2.4 GHz.')
        if self.state == 'offline' and self.saved_ssid:
            reason = (' Không tìm thấy mạng.' if self.reason == '201' else
                      ' Xác thực Wi-Fi chưa thành công; kiểm tra mật khẩu nếu lỗi lặp lại.'
                      if self.reason in ('15', '202', '204') else '')
            return saved + ' ESP32 sẽ tự thử lại.' + reason
        return saved

    @classmethod
    def parse(cls, response, saved='WIFI SAVED 0 -'):
        fields, cache = response.split(), saved.split()
        if len(cache) != 4 or cache[:2] != ['WIFI', 'SAVED'] or cache[2] not in ('0', '1'):
            raise ValueError('Phản hồi mạng đã lưu không hợp lệ.')
        name = wifi_name(cache[3]) if cache[2] == '1' else ''
        if len(fields) >= 3 and fields[:3] == ['WIFI', 'STATUS', 'READY']:
            endpoint = WifiEndpoint.parse(response)
            return cls('ready', wifi_name(fields[5]), endpoint.ip, name)
        if len(fields) in (4, 5) and fields[:2] == ['WIFI', 'STATUS'] and fields[2] in ('JOINING', 'OFFLINE'):
            return cls(fields[2].lower(), saved_ssid=name, reason=fields[4] if len(fields) == 5 else '')
        raise ValueError('Phản hồi trạng thái Wi-Fi không hợp lệ.')


async def wifi_state(protocol):
    # This is read-only. Opening settings/polling must NEVER scan or reconnect
    # a working LAN, and a sensor/HTTP failure must not hide Wi-Fi association.
    response = await wifi_status(protocol)
    try:
        saved = await protocol.request('WIFI SAVED', expected_prefix='WIFI SAVED ')
    except RobotCommandRejected as error:
        if error.code not in ('INVALID_COMMAND', 'WIFI_COMMAND'):
            raise
        saved = 'WIFI SAVED 0 -'
    return WifiState.parse(response, saved)


def wifi_commands(ssid, password):
    name, secret = ssid.encode('utf-8'), password.encode('utf-8')
    if not 1 <= len(name) <= 32 or b'\0' in name:
        raise ValueError('Tên Wi-Fi phải dài 1–32 byte.')
    if (secret and not 8 <= len(secret) <= 63) or b'\0' in secret:
        raise ValueError('Mật khẩu Wi-Fi phải dài 8–63 byte, hoặc để trống với mạng mở.')
    return [f'WIFI SSID {name.hex()}', *[f'WIFI PASS {secret[i:i+24].hex()}' for i in range(0, len(secret), 24)], 'WIFI JOIN']


async def wifi_scan(protocol):
    await wifi_request(protocol, 'WIFI SCAN')
    deadline = time.monotonic() + 20
    while True:
        response = await wifi_request(protocol, 'WIFI COUNT', expected_prefix='WIFI COUNT ')
        if response != 'WIFI COUNT BUSY':
            count = int(response.split()[-1])
            if not 0 <= count <= 30:
                raise ValueError('Số mạng Wi-Fi không hợp lệ.')
            break
        if time.monotonic() > deadline:
            raise ValueError('ESP32 quét Wi-Fi quá hạn. Hãy thử lại.')
        await asyncio.sleep(.3)
    networks = []
    for index in range(count):
        line = await wifi_request(protocol, f'WIFI NET {index}', expected_prefix=f'WIFI NET {index} ')
        fields = line.split()
        if len(fields) != 6:
            raise ValueError('Sai thông tin mạng Wi-Fi.')
        name = bytes.fromhex(fields[5]).decode('utf-8', errors='replace') if fields[5] != '-' else ''
        if name and name not in [row[0] for row in networks]:
            networks.append((name, int(fields[3]), fields[4] == '1'))
    return networks


async def wifi_configure(protocol, ssid, password):
    for line in wifi_commands(ssid, password):
        prefix = 'OK WIFI SSID' if line.startswith('WIFI SSID ') else 'OK WIFI PASS' if line.startswith('WIFI PASS ') else None
        await wifi_request(protocol, line, expected_prefix=prefix)
    return 'Đã gửi cấu hình. Trạng thái kết nối sẽ tự cập nhật.'


async def wifi_status(protocol):
    return await wifi_request(protocol, 'WIFI STATUS', expected_prefix='WIFI STATUS ')


def http_error(endpoint, error):
    reason = getattr(error, 'reason', error)
    code = getattr(reason, 'winerror', None) or getattr(reason, 'errno', None)
    target = f'{endpoint.ip}:80'
    if isinstance(error, HTTPError):
        code = f'HTTP {error.code}'
        if error.code == 401:
            detail = 'Phiên camera hết hiệu lực; kết nối BLE lại.'
        elif error.code == 503:
            detail = 'Camera chưa có JPEG; đợi khởi động rồi mở lại camera.'
        elif error.code == 404:
            detail = 'Firmware chưa có endpoint này; nạp firmware camera 2.1.0-wifi.'
        else:
            detail = 'ESP32 trả lỗi HTTP; xem Serial.'
    elif code in (10061, 111):
        detail = 'Thiết bị từ chối kết nối: cổng HTTP camera chưa mở. Nạp firmware 2.1.0-wifi rồi kiểm tra Wi-Fi.'
    elif isinstance(reason, TimeoutError) or code in (10060, 110):
        detail = 'Kết nối HTTP quá hạn. Kiểm tra IP ESP32, VPN/route và cách ly thiết bị của router.'
    elif code in (10051, 10065, 101, 113):
        detail = 'Máy chưa có đường mạng tới IP ESP32. Kiểm tra subnet/gateway và VPN.'
    else:
        detail = f'{type(reason).__name__}: {str(reason)[:180]}'
    LOGGER.warning('Camera HTTP failed: target=%s code=%s reason=%s', target, code, reason)
    return ValueError(f'Camera {target} · {code or type(reason).__name__}: {detail}')


def check_http(endpoint, *, timeout=3):
    request = Request(f'http://{endpoint.ip}/health', headers={'Authorization': f'Bearer {endpoint.token}'})
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            data = json.loads(response.read(1024))
            if data.get('http') is not True or data.get('ip') != endpoint.ip:
                raise ValueError('Phản hồi kiểm tra camera không khớp IP ESP32.')
            return data
    except (URLError, OSError, TimeoutError) as error:
        raise http_error(endpoint, error) from None


async def wifi_check(protocol):
    response = await wifi_status(protocol)
    endpoint = WifiEndpoint.parse(response)
    await asyncio.to_thread(check_http, endpoint)
    protocol._camera_endpoint = endpoint
    protocol._camera_endpoint_time = time.monotonic()
    return response


def fetch_jpeg(endpoint, path, on_progress=None):
    request = Request(f'http://{endpoint.ip}{path}', headers={'Authorization': f'Bearer {endpoint.token}', 'Cache-Control': 'no-cache'})
    try:
        # Ignore system HTTP proxies for a direct camera LAN connection.
        started = time.monotonic()
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=3 if path == '/preview' else 5) as response:
            total = int(response.headers.get('Content-Length', 0))
            if not 4 <= total <= MAX_BYTES or response.headers.get_content_type() != 'image/jpeg':
                raise ValueError('Camera trả JPEG quá lớn hoặc sai định dạng.')
            result = bytearray()
            deadline = time.monotonic() + 20
            while len(result) < total:
                if time.monotonic() > deadline: raise TimeoutError()
                chunk = response.read1(min(65536, total - len(result)))
                if not chunk:
                    raise ValueError('Ảnh Wi-Fi bị ngắt giữa chừng; hãy chụp lại.')
                result.extend(chunk)
                if on_progress:
                    on_progress(len(result), total)
            if not result.startswith(b'\xff\xd8') or not result.endswith(b'\xff\xd9'):
                raise ValueError('Camera trả JPEG chưa hoàn chỉnh.')
            LOGGER.debug('Camera HTTP JPEG target=%s path=%s bytes=%s seconds=%.3f', endpoint.ip, path, total, time.monotonic()-started)
            return bytes(result)
    except (URLError, OSError, TimeoutError) as error:
        raise http_error(endpoint, error) from None


async def preview(protocol):
    endpoint = getattr(protocol, '_camera_endpoint', None)
    if endpoint is None or time.monotonic() - getattr(protocol, '_camera_endpoint_time', 0) > 4:
        endpoint = WifiEndpoint.parse(await wifi_status(protocol))
        protocol._camera_endpoint = endpoint
        protocol._camera_endpoint_time = time.monotonic()
    try:
        return await asyncio.to_thread(fetch_jpeg, endpoint, '/preview')
    except ValueError:
        protocol._camera_endpoint = None
        raise


async def stream_info(protocol):
    # Only session discovery uses BLE. MJPEG bytes bypass the BLE worker/IPC.
    return WifiEndpoint.parse(await wifi_status(protocol))


async def open_preview(protocol, *, mirror=None, flip=None):
    # An unavailable LAN must not start the sensor or allocate its frame buffers.
    endpoint = await stream_info(protocol)
    health = await asyncio.to_thread(check_http, endpoint)
    if mirror is not None and flip is not None:
        try:
            await protocol.request(f'CAM ORIENT {int(bool(mirror))} {int(bool(flip))}', timeout=5)
        except RobotCommandRejected as error:
            if error.code in ('CAMERA_REQUEST', 'INVALID_COMMAND'):
                raise ValueError('Nạp firmware camera 2.5.0 trở lên để lật preview và ảnh chụp.') from None
            raise
    elif isinstance(health,dict):
        mirror=health.get('mirror'); flip=health.get('flip')
    await protocol.request('CAM OPEN', timeout=5)
    return replace(endpoint,mirror=mirror if type(mirror) is bool else None,
                   flip=flip if type(flip) is bool else None)


async def capture_fast(protocol, on_progress=None):
    # Choose the route BEFORE taking a photo. Never take a second shot silently
    # if a Wi-Fi transfer fails after capture.
    response = await wifi_status(protocol)
    endpoint = WifiEndpoint.parse(response)
    # Check LAN reachability before taking a shot, so a broken HTTP route cannot
    # leave the user waiting for a full-resolution BLE transfer.
    await asyncio.to_thread(check_http, endpoint)
    started = time.monotonic()
    frame_id = secrets.randbelow(0xffffffff) + 1
    await protocol.request(f'CAM SHOT {frame_id}', timeout=5)
    try:
        deadline = time.monotonic() + 35
        while True:
            try:
                metadata = CameraMetadata.parse(await protocol.request(f'CAM META {frame_id}', expected_prefix=f'CAM {frame_id} '), frame_id)
                break
            except RobotCommandRejected as error:
                if error.code != 'CAMERA_BUSY' or time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(.15)
        data = await asyncio.to_thread(fetch_jpeg, endpoint, f'/image?id={frame_id}', on_progress)
        verify_jpeg(data, metadata)
        LOGGER.info('Wi-Fi JPEG received: %s bytes %sx%s CRC32 verified total=%.3fs', len(data), metadata.width, metadata.height, time.monotonic()-started)
        return metadata, data
    finally:
        try:
            await protocol.request(f'CAM RELEASE {frame_id}')
        except Exception:
            LOGGER.warning('Cannot release Wi-Fi camera frame; disconnect/TTL will release it')
