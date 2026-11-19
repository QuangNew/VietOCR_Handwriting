/// Transport-only client: model is hosted on the C# server. No shared baked-in key.
/// Uses dart:io for Android/desktop; store keys with the platform's secure storage.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

class RemoteOcrException implements Exception {
  const RemoteOcrException(
    this.message, {
    this.status,
    this.retryAfter,
    this.code,
  });
  final String message;
  final int? status;
  final Duration? retryAfter;
  final String? code;
  @override
  String toString() => message;
}

class VietOcrRemote {
  VietOcrRemote(
    String origin,
    this._key, {
    bool allowInsecureLan = false,
    this.tokenProvider,
  }) : origin = Uri.parse(origin) {
    if (!{'https', 'http'}.contains(this.origin.scheme) ||
        this.origin.host.isEmpty ||
        this.origin.userInfo.isNotEmpty) {
      throw ArgumentError('Invalid server origin');
    }
    if (this.origin.scheme == 'http' &&
        !{'localhost', '127.0.0.1', '::1'}.contains(this.origin.host) &&
        !allowInsecureLan) {
      throw ArgumentError('HTTPS is required outside loopback.');
    }
    _http.connectionTimeout = const Duration(seconds: 15);
    _http.findProxy = (_) => 'DIRECT';
  }
  final Uri origin;
  final String _key;
  final Future<String> Function()? tokenProvider;
  Future<String> _token() async {
    final token = tokenProvider == null ? _key : await tokenProvider!();
    if (token.isEmpty) {
      throw const RemoteOcrException(
        'Đăng nhập Google trước khi nhận diện.',
        status: 401,
      );
    }
    return token;
  }

  final _http = HttpClient();
  static String newIdempotencyKey() {
    final random = Random.secure();
    return List.generate(
      16,
      (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0'),
    ).join();
  }

  Uri _url(String path) => origin.resolve(path);
  Future<Map<String, dynamic>> account() async {
    final accessToken = await _token();
    final r = await _http.getUrl(_url('/api/v1/me'));
    r.followRedirects = false;
    r.headers.set('Authorization', 'Bearer $accessToken');
    return _response(r);
  }

  Future<List<Map<String, dynamic>>> history() async {
    final accessToken = await _token();
    final r = await _http.getUrl(_url('/api/v1/jobs'));
    r.followRedirects = false;
    r.headers.set('Authorization', 'Bearer $accessToken');
    final response = await r.close().timeout(const Duration(seconds: 25));
    if (response.statusCode != 200) {
      throw RemoteOcrException(
        'Không tải được lịch sử OCR.',
        status: response.statusCode,
      );
    }
    final bytes = <int>[];
    await for (final chunk in response.timeout(const Duration(seconds: 25))) {
      bytes.addAll(chunk);
      if (bytes.length > 2000000) {
        throw const RemoteOcrException('Lịch sử quá lớn.');
      }
    }
    return (jsonDecode(utf8.decode(bytes)) as List)
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  Future<Map<String, dynamic>> _response(HttpClientRequest request) async {
    final response = await request.close().timeout(const Duration(seconds: 25));
    final bytes = <int>[];
    await for (final chunk in response.timeout(const Duration(seconds: 25))) {
      bytes.addAll(chunk);
      if (bytes.length > 2000000) {
        throw const RemoteOcrException('Server response too large.');
      }
    }
    if (response.statusCode >= 300) {
      final detail = bytes.isEmpty
          ? <String, dynamic>{}
          : (jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>);
      throw RemoteOcrException(
        response.statusCode == 401
            ? 'Phiên đăng nhập hết hạn. Hãy đăng nhập Google lại.'
            : (detail['message'] as String? ??
                  'Server trả lỗi ${response.statusCode}.'),
        status: response.statusCode,
        code: detail['error'] as String?,
        retryAfter: Duration(
          seconds:
              (int.tryParse(response.headers.value('retry-after') ?? '') ?? 3)
                  .clamp(1, 30),
        ),
      );
    }
    return bytes.isEmpty
        ? {}
        : jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> submit(
    File image, {
    String layout = 'auto',
    String? idempotencyKey,
  }) async {
    if (await image.length() > 16 * 1048576) {
      throw const RemoteOcrException('Ảnh vượt 16 MiB.');
    }
    if (!{'auto', 'line'}.contains(layout)) {
      throw ArgumentError('Invalid layout');
    }
    final boundary = 'vietocr-${newIdempotencyKey()}';
    final accessToken = await _token();
    final request = await _http.postUrl(_url('/api/v1/jobs'));
    request.followRedirects = false;
    request.headers.set('Authorization', 'Bearer $accessToken');
    request.headers.set(
      'Idempotency-Key',
      idempotencyKey ?? newIdempotencyKey(),
    );
    request.headers.set(
      'Content-Type',
      'multipart/form-data; boundary=$boundary',
    );
    request.write(
      '--$boundary\r\nContent-Disposition: form-data; name="layout"\r\n\r\n$layout\r\n',
    );
    request.write(
      '--$boundary\r\nContent-Disposition: form-data; name="image"; filename="image.jpg"\r\nContent-Type: application/octet-stream\r\n\r\n',
    );
    await request.addStream(image.openRead());
    request.write('\r\n--$boundary--\r\n');
    return _response(request);
  }

  static void _checkId(String id) {
    if (!RegExp(r'^[a-f0-9]{32}$').hasMatch(id)) {
      throw ArgumentError('Invalid job ID');
    }
  }

  Future<Map<String, dynamic>> get(String id) async {
    _checkId(id);
    final accessToken = await _token();
    final r = await _http.getUrl(_url('/api/v1/jobs/$id'));
    r.followRedirects = false;
    r.headers.set('Authorization', 'Bearer $accessToken');
    return _response(r);
  }

  Future<void> cancel(String id) async {
    _checkId(id);
    final accessToken = await _token();
    final r = await _http.deleteUrl(_url('/api/v1/jobs/$id'));
    r.followRedirects = false;
    r.headers.set('Authorization', 'Bearer $accessToken');
    await _response(r);
  }

  Future<String> recognize(
    File image, {
    String layout = 'auto',
    bool Function()? cancelled,
    void Function(String)? onState,
    Duration timeout = const Duration(minutes: 3),
  }) async {
    final deadline = DateTime.now().add(timeout), idem = newIdempotencyKey();
    Map<String, dynamic>? job;
    for (var attempt = 0; attempt < 3; attempt++) {
      if (cancelled?.call() ?? false) {
        throw const RemoteOcrException('Đã huỷ nhận diện.');
      }
      try {
        job = await submit(image, layout: layout, idempotencyKey: idem);
        break;
      } catch (e) {
        if (attempt == 2 ||
            e is RemoteOcrException &&
                ([401, 403].contains(e.status) ||
                    ['daily_quota', 'minute_quota'].contains(e.code))) {
          rethrow;
        }
        await Future<void>.delayed(
          e is RemoteOcrException
              ? e.retryAfter ?? const Duration(seconds: 2)
              : const Duration(seconds: 2),
        );
      }
    }
    if (job == null) {
      throw const RemoteOcrException('Không tạo được công việc.');
    }
    try {
      while (true) {
        if (cancelled?.call() ?? false) {
          throw const RemoteOcrException('Đã huỷ nhận diện.');
        }
        final state = job!['state'] as String;
        onState?.call(state);
        if (state == 'succeeded') return job['text'] as String;
        if (state == 'failed' || state == 'cancelled') {
          throw RemoteOcrException(
            job['error'] as String? ?? 'Nhận diện thất bại.',
          );
        }
        if (DateTime.now().isAfter(deadline)) {
          throw TimeoutException('Hết thời gian chờ OCR.');
        }
        await Future<void>.delayed(const Duration(seconds: 1));
        try {
          job = await get(job['id'] as String);
        } on RemoteOcrException catch (e) {
          if (e.status == 401) rethrow;
          await Future<void>.delayed(
            e.retryAfter ?? const Duration(seconds: 2),
          );
        }
      }
    } catch (_) {
      if ((cancelled?.call() ?? false) || DateTime.now().isAfter(deadline)) {
        try {
          await cancel(job!['id'] as String);
        } catch (_) {}
      }
      rethrow;
    }
  }

  void close() => _http.close(force: true);
}
