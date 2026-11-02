"""OV5640 settings contract and authenticated LAN control (no Tk/BLE I/O here)."""
import asyncio
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

# key: label, group, minimum, maximum, default, optional discrete choices.
FIELDS = {
    'preview_width': ('Độ phân giải preview', 'Luồng ảnh', 320, 2592, 640, {320:'320 × 240',640:'640 × 480 · Mượt',800:'800 × 600',1024:'1024 × 768',1600:'1600 × 1200',2048:'2048 × 1536',2592:'2592 × 1944 · Nặng'}),
    'preview_quality': ('JPEG preview · QS thấp = nét hơn', 'Luồng ảnh', 4, 63, 18, None),
    'still_quality': ('JPEG ảnh chụp 5 MP · QS thấp = nét hơn', 'Luồng ảnh', 4, 63, 8, None),
    'max_fps': ('Giới hạn FPS · 0 = không giới hạn', 'Luồng ảnh', 0, 30, 30, None),
    'brightness': ('Độ sáng', 'Màu sắc', -3, 3, 0, None),
    'contrast': ('Tương phản', 'Màu sắc', -3, 3, 0, None),
    'saturation': ('Bão hòa màu', 'Màu sắc', -4, 4, 0, None),
    'sharpness': ('Độ sắc nét', 'Màu sắc', -3, 3, 0, None),
    'denoise': ('Giảm nhiễu', 'Màu sắc', 0, 8, 0, None),
    'wb_mode': ('Cân bằng trắng', 'Màu sắc', 0, 4, 0, {0:'Tự động',1:'Nắng',2:'Nhiều mây',3:'Đèn văn phòng',4:'Đèn trong nhà'}),
    'special_effect': ('Hiệu ứng', 'Màu sắc', 0, 6, 0, {0:'Tự nhiên',1:'Âm bản',2:'Thang xám',3:'Đỏ',4:'Xanh lá',5:'Xanh dương',6:'Sepia'}),
    'aec': ('Phơi sáng tự động', 'Ánh sáng', 0, 1, 1, {0:'Tắt · chỉnh tay',1:'Bật'}),
    'ae_level': ('Bù phơi sáng tự động', 'Ánh sáng', -5, 5, 0, None),
    'aec_value': ('Phơi sáng thủ công', 'Ánh sáng', 0, 1944, 500, None),
    'agc': ('Gain tự động', 'Ánh sáng', 0, 1, 1, {0:'Tắt · chỉnh tay',1:'Bật'}),
    'agc_gain': ('Gain thủ công', 'Ánh sáng', 0, 64, 0, None),
    'hmirror': ('Lật ngang', 'Hướng ảnh', 0, 1, 0, {0:'Tắt',1:'Bật'}),
    'vflip': ('Lật dọc', 'Hướng ảnh', 0, 1, 0, {0:'Tắt',1:'Bật'}),
    'lenc': ('Hiệu chỉnh ống kính', 'Hướng ảnh', 0, 1, 1, {0:'Tắt',1:'Bật'}),
    'autofocus': ('Lấy nét tự động', 'Ánh sáng', 0, 1, 1, {0:'Tắt',1:'Bật'}),
}
DEFAULTS = {key: field[4] for key,field in FIELDS.items()}
PRESETS = {'Mượt': {'preview_width':640,'preview_quality':24,'max_fps':30},
           'Cân bằng': {'preview_width':640,'preview_quality':18,'max_fps':30},
           'Chi tiết': {'preview_width':1024,'preview_quality':10,'max_fps':15}}

def validate_settings(values, *, partial=False):
    if not isinstance(values, dict) or (not partial and set(values) != set(FIELDS)):
        raise ValueError('Cấu hình camera thiếu thông số hoặc khác phiên bản.')
    result = dict(values)
    for key,value in result.items():
        if key not in FIELDS:
            raise ValueError(f'Thông số camera không hỗ trợ: {key}')
        label,_,low,high,_,choices = FIELDS[key]
        if type(value) is not int or not low <= value <= high or (choices is not None and value not in choices):
            raise ValueError(f'{label}: giá trị không hợp lệ.')
    return result

def parse_config(data):
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data.get('schema') != 2 or data.get('sensor') != 'OV5640':
        raise ValueError('Cần firmware OV5640 3.0.0 trở lên để chỉnh cấu hình.')
    validate_settings(data.get('settings'))
    validate_settings(data.get('defaults'))
    for key in ('revision','applied_revision'):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ValueError('Camera trả phiên bản cấu hình không hợp lệ.')
    if type(data.get('saved')) is not bool or not isinstance(data.get('error'),str):
        raise ValueError('Camera trả trạng thái cấu hình không hợp lệ.')
    return data

def request_config(endpoint, settings=None, *, persist=False):
    from .wifi_camera import _NoRedirect, http_error
    body = None if settings is None else json.dumps({'settings':validate_settings(settings),'persist':bool(persist)}, separators=(',',':')).encode()
    request = Request(f'http://{endpoint.ip}/camera/config', data=body,
                      headers={'Authorization':f'Bearer {endpoint.token}','Content-Type':'application/json','Cache-Control':'no-cache'})
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=5) as response:
            raw = response.read(4097)
            if len(raw) > 4096: raise ValueError('Phản hồi cấu hình camera quá lớn.')
            return parse_config(json.loads(raw))
    except HTTPError as error:
        if error.code == 404: raise ValueError('Nạp firmware OV5640 3.0.0 để dùng bảng cấu hình.') from None
        if error.code in (400,409):
            try: detail=json.loads(error.read(1024)).get('error','Camera từ chối cấu hình.')
            except (ValueError,UnicodeError): detail='Camera từ chối cấu hình.'
            raise ValueError(str(detail)) from None
        raise http_error(endpoint,error) from None
    except (URLError,OSError,TimeoutError) as error:
        raise http_error(endpoint,error) from None

async def get_config(protocol):
    from .wifi_camera import WifiEndpoint, wifi_status
    endpoint = WifiEndpoint.parse(await wifi_status(protocol))
    return await asyncio.to_thread(request_config,endpoint)

async def apply_config(protocol, settings, persist=True):
    from .wifi_camera import WifiEndpoint, wifi_status
    settings=validate_settings(settings)
    endpoint = WifiEndpoint.parse(await wifi_status(protocol))
    await protocol.request('CAM CLOSE',timeout=5)
    result=await asyncio.to_thread(request_config,endpoint,settings,persist=persist)
    revision=result['revision']; deadline=time.monotonic()+20; ping=time.monotonic()
    while True:
        if result['error']: raise ValueError(result['error'])
        if result['revision'] != revision: raise ValueError('Cấu hình camera đã bị thay đổi bởi yêu cầu khác. Hãy tải lại.')
        if result['applied_revision'] == revision and (not persist or result['saved']): return result
        if time.monotonic() >= deadline: raise ValueError('Camera chưa xác nhận áp dụng cấu hình. Tải lại để kiểm tra trước khi thử tiếp.')
        if time.monotonic()-ping>=3:
            await protocol.request('PING'); ping=time.monotonic()
        await asyncio.sleep(.15)
        result=await asyncio.to_thread(request_config,endpoint)
