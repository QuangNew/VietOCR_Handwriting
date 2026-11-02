import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'camera_transfer.dart';

typedef WifiRequest = Future<String> Function(String command, String? prefix);

List<String> wifiCommands(String ssid, String password) {
  final name = utf8.encode(ssid), secret = utf8.encode(password);
  if (name.isEmpty || name.length > 32 || name.contains(0)) {
    throw ArgumentError('Tên Wi-Fi phải dài 1–32 byte.');
  }
  if ((secret.isNotEmpty && (secret.length < 8 || secret.length > 63)) ||
      secret.contains(0)) {
    throw ArgumentError(
      'Mật khẩu phải dài 8–63 byte, hoặc để trống với mạng mở.',
    );
  }
  return [
    'WIFI SSID ${hexBytes(name)}',
    for (var i = 0; i < secret.length; i += 24)
      'WIFI PASS ${hexBytes(secret.sublist(i, (i + 24).clamp(0, secret.length)))}',
    'WIFI JOIN',
  ];
}

String hexBytes(List<int> bytes) =>
    bytes.map((v) => v.toRadixString(16).padLeft(2, '0')).join();
String wifiName(String hex) {
  if (hex == '-') return '';
  if (hex.length.isOdd || hex.length > 64) {
    throw const FormatException('Tên Wi-Fi không hợp lệ.');
  }
  return utf8.decode([
    for (var i = 0; i < hex.length; i += 2)
      int.parse(hex.substring(i, i + 2), radix: 16),
  ], allowMalformed: true);
}

class WifiState {
  const WifiState({
    this.state = 'unknown',
    this.ssid = '',
    this.ip = '',
    this.savedSsid = '',
    this.reason = '',
  });
  final String state, ssid, ip, savedSsid, reason;
  bool get ready => state == 'ready';
  String get summary => switch (state) {
    'ready' => 'Wi-Fi đã kết nối · $ssid · IP $ip',
    'joining' =>
      'Wi-Fi đang kết nối · ${savedSsid.isEmpty ? 'mạng đã cấu hình' : savedSsid}',
    'offline' =>
      savedSsid.isEmpty
          ? 'Wi-Fi chưa được cấu hình'
          : 'Wi-Fi chưa kết nối · $savedSsid',
    _ => 'Wi-Fi · Đang đọc trạng thái từ ESP32…',
  };
  String get detail {
    if (savedSsid.isEmpty) {
      return 'Chưa có mạng lưu trên ESP32. Chọn hoặc nhập Wi-Fi 2.4 GHz.';
    }
    final saved =
        'Mạng đã lưu trên ESP32: $savedSsid. Tự kết nối khi khởi động / kết nối BLE.';
    if (state != 'offline') return saved;
    final error = reason == '201'
        ? ' Không tìm thấy mạng.'
        : ['15', '202', '204'].contains(reason)
        ? ' Xác thực chưa thành công; kiểm tra mật khẩu nếu lỗi lặp lại.'
        : '';
    return '$saved ESP32 sẽ tự thử lại.$error';
  }

  factory WifiState.parse(String response, String saved) {
    final fields = response.split(' '), cache = saved.split(' ');
    if (cache.length != 4 ||
        cache[0] != 'WIFI' ||
        cache[1] != 'SAVED' ||
        !['0', '1'].contains(cache[2])) {
      throw const FormatException('Phản hồi mạng đã lưu không hợp lệ.');
    }
    final name = cache[2] == '1' ? wifiName(cache[3]) : '';
    if (response.startsWith('WIFI STATUS READY ')) {
      final endpoint = WifiEndpoint.parse(response);
      return WifiState(
        state: 'ready',
        ssid: wifiName(fields[5]),
        ip: endpoint.ip,
        savedSsid: name,
      );
    }
    if ((fields.length == 4 || fields.length == 5) &&
        fields[0] == 'WIFI' &&
        fields[1] == 'STATUS' &&
        ['JOINING', 'OFFLINE'].contains(fields[2])) {
      return WifiState(
        state: fields[2].toLowerCase(),
        savedSsid: name,
        reason: fields.length == 5 ? fields[4] : '',
      );
    }
    throw const FormatException('Phản hồi trạng thái Wi-Fi không hợp lệ.');
  }
}

class WifiEndpoint {
  const WifiEndpoint(this.ip, this.token);
  final String ip, token;
  factory WifiEndpoint.parse(String line) {
    final parts = line.split(' ');
    if (parts.length != 6 || !line.startsWith('WIFI STATUS READY ')) {
      throw StateError(wifiUnavailableMessage(line));
    }
    final address = InternetAddress.tryParse(parts[3]);
    final bytes = address?.rawAddress;
    if (bytes == null ||
        bytes.length != 4 ||
        !(bytes[0] == 10 ||
            (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
            (bytes[0] == 192 && bytes[1] == 168) ||
            bytes[0] == 127) ||
        !RegExp(r'^[0-9a-f]{32}$').hasMatch(parts[4])) {
      throw const FormatException('Địa chỉ Wi-Fi camera không hợp lệ.');
    }
    return WifiEndpoint(parts[3], parts[4]);
  }
}

String wifiUnavailableMessage(String line) {
  if (line.startsWith('WIFI STATUS JOINING ')) {
    return 'ESP32 đang kết nối Wi-Fi. Đợi hoặc quét để chọn mạng khác.';
  }
  final fields = line.split(' ');
  final status = fields.length > 3 ? fields[3] : '';
  final reason = fields.length > 4 ? fields[4] : '';
  final detail = status == '1' || reason == '201'
      ? ' Không tìm thấy mạng đã lưu.'
      : status == '4' || ['15', '202', '204'].contains(reason)
      ? ' Kiểm tra mật khẩu Wi-Fi.'
      : '';
  return 'ESP32 chưa vào Wi-Fi.$detail Mở Wi-Fi camera và chọn mạng 2.4 GHz.';
}

Future<void> checkCameraHttp(WifiEndpoint endpoint) async {
  final client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 3)
    ..findProxy = (_) => 'DIRECT';
  try {
    final request = await client
        .getUrl(Uri.parse('http://${endpoint.ip}/health'))
        .timeout(const Duration(seconds: 4));
    request.followRedirects = false;
    request.headers.set(
      HttpHeaders.authorizationHeader,
      'Bearer ${endpoint.token}',
    );
    final response = await request.close().timeout(const Duration(seconds: 4));
    if (response.statusCode != 200) {
      throw StateError(
        'Camera HTTP ${response.statusCode} tại ${endpoint.ip}. Kiểm tra firmware/kết nối BLE.',
      );
    }
    final data = BytesBuilder(copy: false);
    await for (final chunk in response.timeout(const Duration(seconds: 3))) {
      if (data.length + chunk.length > 4096) {
        throw const FormatException('Phản hồi camera quá lớn.');
      }
      data.add(chunk);
    }
    final value = jsonDecode(utf8.decode(data.takeBytes()));
    if (value is! Map || value['http'] != true || value['ip'] != endpoint.ip) {
      throw const FormatException(
        'Sai phản hồi HTTP của ESP32. Nạp firmware camera mới.',
      );
    }
  } on SocketException catch (error) {
    throw StateError(
      'Không tới được camera ${endpoint.ip}:80 (socket ${error.osError?.errorCode ?? 'unknown'}). Kiểm tra cùng mạng LAN.',
    );
  } on TimeoutException {
    throw StateError('Camera ${endpoint.ip}:80 quá hạn. Kiểm tra Wi-Fi.');
  } finally {
    client.close(force: true);
  }
}

Future<Uint8List> fetchCameraJpeg(
  WifiEndpoint endpoint,
  String path, {
  void Function(double)? progress,
}) async {
  final client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 4)
    ..findProxy = (_) => 'DIRECT';
  final deadline = Stopwatch()..start();
  try {
    final request = await client
        .getUrl(Uri.parse('http://${endpoint.ip}$path'))
        .timeout(const Duration(seconds: 5));
    request.followRedirects = false;
    request.headers.set(
      HttpHeaders.authorizationHeader,
      'Bearer ${endpoint.token}',
    );
    final response = await request.close().timeout(const Duration(seconds: 8));
    if (response.statusCode != 200) {
      throw StateError(
        'Camera HTTP ${response.statusCode}. Kiểm tra Wi-Fi, mở lại camera hoặc kết nối lại BLE.',
      );
    }
    final size = response.contentLength;
    if (size < 4 ||
        size > 2 * 1024 * 1024 ||
        response.headers.contentType?.mimeType != 'image/jpeg') {
      throw const FormatException('Camera trả ảnh quá lớn hoặc sai JPEG.');
    }
    final data = BytesBuilder(copy: false);
    await for (final chunk in response.timeout(const Duration(seconds: 5))) {
      if (deadline.elapsed > const Duration(seconds: 20) ||
          data.length + chunk.length > size) {
        throw const FormatException(
          'Ảnh Wi-Fi quá hạn hoặc vượt kích thước khai báo.',
        );
      }
      data.add(chunk);
      progress?.call(data.length / size);
    }
    final bytes = data.takeBytes();
    if (bytes.length != size ||
        bytes[0] != 255 ||
        bytes[1] != 216 ||
        bytes[size - 2] != 255 ||
        bytes[size - 1] != 217) {
      throw const FormatException('Ảnh Wi-Fi bị thiếu dữ liệu. Hãy chụp lại.');
    }
    return bytes;
  } on SocketException {
    throw StateError(
      'Không tới được camera. Điện thoại và ESP32 cần cùng mạng LAN; tắt cách ly thiết bị trên router.',
    );
  } on TimeoutException {
    throw StateError('Nhận ảnh Wi-Fi quá hạn. Kiểm tra tín hiệu rồi thử lại.');
  } finally {
    client.close(force: true);
  }
}

Future<CameraPhoto> captureWifiPhoto({
  required int id,
  required WifiEndpoint endpoint,
  required WifiRequest request,
  required void Function() checkConnected,
  required Future<int> Function(Uint8List) checksum,
  void Function(double)? progress,
}) async {
  checkConnected();
  await checkCameraHttp(endpoint);
  checkConnected();
  await request('CAM SHOT $id', null);
  try {
    final deadline = DateTime.now().add(const Duration(seconds: 35));
    late CameraMetadata metadata;
    while (true) {
      checkConnected();
      try {
        metadata = CameraMetadata.parse(
          await request('CAM META $id', 'CAM $id '),
          id,
        );
        break;
      } catch (error) {
        if (!error.toString().contains('CAMERA_BUSY') ||
            DateTime.now().isAfter(deadline)) {
          rethrow;
        }
        await Future<void>.delayed(const Duration(milliseconds: 160));
      }
    }
    final bytes = await fetchCameraJpeg(
      endpoint,
      '/image?id=$id',
      progress: progress,
    );
    checkConnected();
    if (bytes.length != metadata.size ||
        await checksum(bytes) != metadata.crc) {
      throw const FormatException(
        'Ảnh Wi-Fi sai CRC32; ảnh chưa được đưa vào OCR.',
      );
    }
    return CameraPhoto(metadata, bytes);
  } finally {
    try {
      await request('CAM RELEASE $id', null);
    } catch (_) {}
  }
}
