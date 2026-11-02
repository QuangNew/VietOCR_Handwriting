import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'wifi_camera.dart';

class CameraField {
  const CameraField(
    this.label,
    this.group,
    this.min,
    this.max,
    this.initial, [
    this.choices,
  ]);
  final String label, group;
  final int min, max, initial;
  final Map<int, String>? choices;
}

const cameraFields = <String, CameraField>{
  'preview_width':
      CameraField('Độ phân giải preview', 'Luồng ảnh', 320, 2592, 640, {
        320: '320 × 240',
        640: '640 × 480 · Mượt',
        800: '800 × 600',
        1024: '1024 × 768',
        1600: '1600 × 1200',
        2048: '2048 × 1536',
        2592: '2592 × 1944 · Nặng',
      }),
  'preview_quality': CameraField(
    'JPEG preview · QS thấp = nét hơn',
    'Luồng ảnh',
    4,
    63,
    18,
  ),
  'still_quality': CameraField(
    'JPEG ảnh chụp 5 MP · QS thấp = nét hơn',
    'Luồng ảnh',
    4,
    63,
    8,
  ),
  'max_fps': CameraField(
    'Giới hạn FPS · 0 = không giới hạn',
    'Luồng ảnh',
    0,
    30,
    30,
  ),
  'brightness': CameraField('Độ sáng', 'Màu sắc', -3, 3, 0),
  'contrast': CameraField('Tương phản', 'Màu sắc', -3, 3, 0),
  'saturation': CameraField('Bão hòa màu', 'Màu sắc', -4, 4, 0),
  'sharpness': CameraField('Độ sắc nét', 'Màu sắc', -3, 3, 0),
  'denoise': CameraField('Giảm nhiễu', 'Màu sắc', 0, 8, 0),
  'wb_mode': CameraField('Cân bằng trắng', 'Màu sắc', 0, 4, 0, {
    0: 'Tự động',
    1: 'Nắng',
    2: 'Nhiều mây',
    3: 'Đèn văn phòng',
    4: 'Đèn trong nhà',
  }),
  'special_effect': CameraField('Hiệu ứng', 'Màu sắc', 0, 6, 0, {
    0: 'Tự nhiên',
    1: 'Âm bản',
    2: 'Thang xám',
    3: 'Đỏ',
    4: 'Xanh lá',
    5: 'Xanh dương',
    6: 'Sepia',
  }),
  'aec': CameraField('Phơi sáng tự động', 'Ánh sáng', 0, 1, 1, {
    0: 'Tắt · chỉnh tay',
    1: 'Bật',
  }),
  'ae_level': CameraField('Bù phơi sáng tự động', 'Ánh sáng', -5, 5, 0),
  'aec_value': CameraField('Phơi sáng thủ công', 'Ánh sáng', 0, 1944, 500),
  'agc': CameraField('Gain tự động', 'Ánh sáng', 0, 1, 1, {
    0: 'Tắt · chỉnh tay',
    1: 'Bật',
  }),
  'agc_gain': CameraField('Gain thủ công', 'Ánh sáng', 0, 64, 0),
  'hmirror': CameraField('Lật ngang', 'Hướng ảnh', 0, 1, 0, {
    0: 'Tắt',
    1: 'Bật',
  }),
  'vflip': CameraField('Lật dọc', 'Hướng ảnh', 0, 1, 0, {0: 'Tắt', 1: 'Bật'}),
  'lenc': CameraField('Hiệu chỉnh ống kính', 'Hướng ảnh', 0, 1, 1, {
    0: 'Tắt',
    1: 'Bật',
  }),
  'autofocus': CameraField('Lấy nét tự động', 'Ánh sáng', 0, 1, 1, {
    0: 'Tắt',
    1: 'Bật',
  }),
};
final cameraDefaults = {
  for (final entry in cameraFields.entries) entry.key: entry.value.initial,
};
const cameraPresets = {
  'Mượt': {'preview_width': 640, 'preview_quality': 24, 'max_fps': 30},
  'Cân bằng': {'preview_width': 640, 'preview_quality': 18, 'max_fps': 30},
  'Chi tiết': {'preview_width': 1024, 'preview_quality': 10, 'max_fps': 15},
};

Map<String, int> validateCameraSettings(Object? value) {
  if (value is! Map ||
      value.length != cameraFields.length ||
      !cameraFields.keys.every(value.containsKey)) {
    throw const FormatException(
      'Cấu hình camera thiếu thông số hoặc khác phiên bản.',
    );
  }
  final output = <String, int>{};
  for (final entry in cameraFields.entries) {
    final v = value[entry.key], field = entry.value;
    if (v is! int ||
        v < field.min ||
        v > field.max ||
        (field.choices != null && !field.choices!.containsKey(v))) {
      throw FormatException('${field.label}: giá trị không hợp lệ.');
    }
    output[entry.key] = v;
  }
  return output;
}

class CameraConfig {
  CameraConfig(
    this.settings,
    this.defaults,
    this.revision,
    this.appliedRevision,
    this.saved,
    this.error,
  );
  final Map<String, int> settings, defaults;
  final int revision, appliedRevision;
  final bool saved;
  final String error;
  factory CameraConfig.parse(Object? value) {
    if (value is! Map || value['schema'] != 2 || value['sensor'] != 'OV5640') {
      throw const FormatException(
        'Cần firmware OV5640 3.0.0 để chỉnh cấu hình.',
      );
    }
    if (value['revision'] is! int ||
        value['applied_revision'] is! int ||
        (value['revision'] as int) < 0 ||
        (value['applied_revision'] as int) < 0 ||
        value['saved'] is! bool ||
        value['error'] is! String) {
      throw const FormatException('Trạng thái cấu hình camera không hợp lệ.');
    }
    return CameraConfig(
      validateCameraSettings(value['settings']),
      validateCameraSettings(value['defaults']),
      value['revision'] as int,
      value['applied_revision'] as int,
      value['saved'] as bool,
      value['error'] as String,
    );
  }
}

Future<CameraConfig> requestCameraConfig(
  WifiEndpoint endpoint, {
  Map<String, int>? settings,
  bool persist = false,
}) async {
  final client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 4)
    ..findProxy = (_) => 'DIRECT';
  try {
    final uri = Uri.parse('http://${endpoint.ip}/camera/config');
    final request = await client
        .openUrl(settings == null ? 'GET' : 'POST', uri)
        .timeout(const Duration(seconds: 5));
    request.followRedirects = false;
    request.headers.set(
      HttpHeaders.authorizationHeader,
      'Bearer ${endpoint.token}',
    );
    if (settings != null) {
      final bytes = utf8.encode(
        jsonEncode({
          'settings': validateCameraSettings(settings),
          'persist': persist,
        }),
      );
      request.headers.contentType = ContentType.json;
      request.contentLength = bytes.length;
      request.add(bytes);
    }
    final response = await request.close().timeout(const Duration(seconds: 5));
    final data = <int>[];
    await for (final chunk in response.timeout(const Duration(seconds: 5))) {
      if (data.length + chunk.length > 4096) {
        throw const FormatException('Phản hồi cấu hình quá lớn.');
      }
      data.addAll(chunk);
    }
    if (response.statusCode == 404) {
      throw StateError('Nạp firmware OV5640 3.0.0 để dùng cấu hình.');
    }
    if (response.statusCode != 200 && response.statusCode != 202) {
      Object? detail;
      try {
        detail = (jsonDecode(utf8.decode(data)) as Map)['error'];
      } catch (_) {}
      throw StateError(
        detail?.toString() ??
            'Camera HTTP ${response.statusCode}. Kết nối lại BLE/Wi-Fi.',
      );
    }
    return CameraConfig.parse(jsonDecode(utf8.decode(data)));
  } on SocketException {
    throw StateError('Không tới được camera. Kiểm tra cùng mạng LAN.');
  } on TimeoutException {
    throw StateError('Cấu hình camera quá hạn. Tải lại trước khi thử tiếp.');
  } finally {
    client.close(force: true);
  }
}
