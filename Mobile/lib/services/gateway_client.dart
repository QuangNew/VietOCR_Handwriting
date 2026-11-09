/// Authenticated Pi camera and resumable OCR v2. Images always pass through Pi.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'mjpeg_stream.dart';

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
    validateOrigin(this.origin, allowInsecureLan: allowInsecureLan);
    _http.connectionTimeout = const Duration(seconds: 10);
    _http.findProxy = (_) => 'DIRECT';
  }
  static void validateOrigin(Uri u, {bool allowInsecureLan = false}) {
    if (!{'https', 'http'}.contains(u.scheme) ||
        u.host.isEmpty ||
        u.userInfo.isNotEmpty ||
        u.hasQuery ||
        u.hasFragment ||
        !{'', '/'}.contains(u.path) ||
        u.scheme == 'http' &&
            !{'localhost', '127.0.0.1', '::1'}.contains(u.host) &&
            !allowInsecureLan)
      throw ArgumentError(
        'Cần địa chỉ HTTPS của Raspberry. HTTP chỉ dành cho phát triển trong LAN.',
      );
  }

  final Uri origin;
  final String _key;
  final Future<String> Function()? tokenProvider;
  final _http = HttpClient();
  bool _closed = false;
  Uri? _resultsOrigin;
  Future<String> _token() async {
    if (_closed) throw StateError('Client đã đóng.');
    final token = tokenProvider == null ? _key : await tokenProvider!();
    if (token.isEmpty)
      throw const RemoteOcrException('Đăng nhập Google trước.', status: 401);
    return token;
  }

  static String newIdempotencyKey() {
    final r = Random.secure();
    final b = List.generate(16, (_) => r.nextInt(256));
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    final s = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
    return '${s.substring(0, 8)}-${s.substring(8, 12)}-${s.substring(12, 16)}-${s.substring(16, 20)}-${s.substring(20)}';
  }

  Future<HttpClientRequest> request(String method, String path) async {
    final r = await _http
        .openUrl(method, origin.resolve(path))
        .timeout(const Duration(seconds: 10));
    r.followRedirects = false;
    r.headers.set('Authorization', 'Bearer ${await _token()}');
    return r;
  }

  Future<dynamic> _read(HttpClientRequest r) async {
    final response = await r.close().timeout(const Duration(seconds: 30));
    final bytes = BytesBuilder(copy: false);
    var count = 0;
    await for (final chunk in response.timeout(const Duration(seconds: 30))) {
      count += chunk.length;
      if (count > 2 * 1024 * 1024)
        throw const FormatException('Phản hồi quá lớn.');
      bytes.add(chunk);
    }
    final text = utf8.decode(bytes.takeBytes());
    dynamic value;
    try {
      value = text.isEmpty ? <String, dynamic>{} : jsonDecode(text);
    } catch (_) {
      throw RemoteOcrException(
        'Gateway trả dữ liệu không hợp lệ.',
        status: response.statusCode,
      );
    }
    if (response.statusCode >= 300) {
      final code = value is Map ? value['error']?.toString() : null;
      throw RemoteOcrException(
        switch (code) {
          'daily_quota' => 'Đã hết hạn mức ảnh hôm nay.',
          'minute_quota' => 'Đã đạt 30 ảnh trong 60 giây. Hãy chờ.',
          'google_session_required' ||
          'account_or_session_disabled' ||
          'account_disabled' => 'Phiên Google hết hạn hoặc tài khoản bị khoá.',
          'compute_not_configured' =>
            'Raspberry chưa được ghép nối với máy chạy model.',
          _ => '${code ?? 'Kết nối thất bại'} (HTTP ${response.statusCode}).',
        },
        status: response.statusCode,
        code: code,
        retryAfter: Duration(
          seconds:
              (int.tryParse(response.headers.value('retry-after') ?? '') ?? 3)
                  .clamp(1, 60),
        ),
      );
    }
    return value;
  }

  Future<Map<String, dynamic>> json(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    final r = await request(method, path);
    if (body != null) {
      r.headers.contentType = ContentType.json;
      r.write(jsonEncode(body));
    }
    return Map<String, dynamic>.from(await _read(r) as Map);
  }

  Future<Map<String, dynamic>> session() async {
    final value = await json('GET', '/api/v2/session');
    if (value['resultsOrigin'] is String) {
      final u = Uri.parse(value['resultsOrigin'] as String);
      validateOrigin(u);
      _resultsOrigin = u;
    }
    return value;
  }

  Future<Map<String, dynamic>> account() async =>
      Map<String, dynamic>.from((await session())['account'] as Map);
  Future<List<Map<String, dynamic>>> history() async =>
      ((await _read(await request('GET', '/api/v2/intents'))) as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
  Future<List<Map<String, dynamic>>> cameras() async =>
      ((await _read(await request('GET', '/api/v2/cameras'))) as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
  Future<Uint8List> snapshot(String camera) async {
    final r = await request(
      'POST',
      '/api/v2/cameras/${Uri.encodeComponent(camera)}/snapshots',
    );
    final response = await r.close().timeout(const Duration(seconds: 15));
    if (response.statusCode != 200)
      throw RemoteOcrException(
        'Chụp camera thất bại.',
        status: response.statusCode,
      );
    final output = BytesBuilder(copy: false);
    var length = 0;
    await for (final p in response.timeout(const Duration(seconds: 15))) {
      length += p.length;
      if (length > 8 * 1024 * 1024)
        throw const FormatException('Ảnh camera quá lớn.');
      output.add(p);
    }
    final bytes = output.takeBytes();
    final expected = response.headers.value('x-image-sha256');
    if (expected != null && sha256.convert(bytes).toString() != expected)
      throw const FormatException('Ảnh camera bị lỗi đường truyền.');
    return bytes;
  }

  Stream<Uint8List> frames(String camera) async* {
    while (!_closed) {
      final r = await request(
        'GET',
        '/api/v2/cameras/${Uri.encodeComponent(camera)}/stream',
      );
      final response = await r.close().timeout(const Duration(seconds: 15));
      if (response.statusCode != 200)
        throw RemoteOcrException(
          'Không mở được camera.',
          status: response.statusCode,
        );
      final parser = MjpegParser(response.headers.value('content-type') ?? '');
      await for (final chunk in response.timeout(const Duration(seconds: 15))) {
        if (_closed) return;
        for (final frame in parser.add(chunk)) {
          yield frame;
        }
      }
      if (!_closed) await Future<void>.delayed(const Duration(seconds: 1));
    }
  }

  Future<Map<String, dynamic>> get(String id) async {
    if (_resultsOrigin == null) await session();
    final ticket = await json('POST', '/api/v2/intents/$id/result-ticket', {});
    final u = Uri.parse(ticket['resultUrl'] as String);
    if (_resultsOrigin == null ||
        u.origin != _resultsOrigin!.origin ||
        u.path != '/api/v2/results/$id' ||
        u.userInfo.isNotEmpty ||
        u.hasFragment ||
        u.hasQuery)
      throw const FormatException('Địa chỉ trả kết quả không hợp lệ.');
    final r = await _http.getUrl(u.replace(queryParameters: {'wait': '8'}));
    r.followRedirects = false;
    r.headers.set('Authorization', 'Bearer ${ticket['ticket']}');
    return Map<String, dynamic>.from(await _read(r) as Map);
  }

  Future<String> recognize(
    File image, {
    String layout = 'auto',
    bool Function()? cancelled,
    void Function(String)? onState,
    Duration timeout = const Duration(minutes: 20),
  }) async {
    final deadline = DateTime.now().add(timeout);
    void check() {
      if (_closed || (cancelled?.call() ?? false))
        throw const RemoteOcrException(
          'Đã tạm dừng. Ảnh đã nhận ở server vẫn được xử lý.',
        );
      if (DateTime.now().isAfter(deadline))
        throw const RemoteOcrException(
          'Hết thời gian chờ; mở lại để nhận kết quả.',
        );
    }

    check();
    await session();
    final length = await image.length();
    if (length > 16 * 1048576)
      throw const FormatException(
        'Ảnh gửi vượt 16 MiB. Hãy crop vùng cần đọc.',
      );
    final hash = (await sha256.bind(image.openRead()).first).toString();
    final sidecar = File('${image.path}.ocr-v2.json');
    Map<String, dynamic> cache = {};
    if (await sidecar.exists()) {
      try {
        cache = Map<String, dynamic>.from(
          jsonDecode(await sidecar.readAsString()) as Map,
        );
      } catch (_) {}
    }
    if (cache['sha256'] != hash ||
        cache['layout'] != layout ||
        cache['gateway'] != origin.toString())
      cache = {
        'requestId': newIdempotencyKey(),
        'sha256': hash,
        'layout': layout,
        'gateway': origin.toString(),
      };
    Future<void> save() async {
      final temp = File('${sidecar.path}.tmp');
      await temp.writeAsString(jsonEncode(cache), flush: true);
      await temp.rename(sidecar.path);
    }

    await save();
    final input = await image.open();
    final head = await input.read(12);
    await input.close();
    final media = head.length > 3 && head[0] == 255 && head[1] == 216
        ? 'image/jpeg'
        : head.length > 3 && head[0] == 137
        ? 'image/png'
        : 'image/webp';
    final intent = await json('POST', '/api/v2/intents', {
      'requestId': cache['requestId'],
      'sha256': hash,
      'imageBytes': length,
      'mediaType': media,
      'layout': layout,
      'imageVersion': 1,
    });
    final id = intent['id'] as String;
    cache['jobId'] = id;
    await save();
    var state = intent['state'];
    if (!['queued', 'running', 'succeeded', 'failed'].contains(state)) {
      Map<String, dynamic> grant;
      while (true) {
        check();
        onState?.call('awaiting_upload');
        try {
          grant = await json('POST', '/api/v2/intents/$id/grant', {});
          break;
        } on RemoteOcrException catch (e) {
          if (![429, 503].contains(e.status) ||
              ['minute_quota', 'daily_quota'].contains(e.code))
            rethrow;
          await Future<void>.delayed(
            e.retryAfter ?? const Duration(seconds: 3),
          );
        }
      }
      if (grant['accepted'] != true) {
        final generation = grant['generation'] as int;
        var offset = grant['offset'] as int;
        while (offset < length) {
          check();
          final end = min(offset + 1048576, length);
          onState?.call('uploading ${(offset * 100 / length).round()}%');
          final r = await request('PUT', '/api/v2/intents/$id/content');
          r.headers.set('Upload-Offset', offset);
          r.headers.set('X-OCR-Generation', generation);
          r.contentLength = end - offset;
          await r.addStream(image.openRead(offset, end));
          final value = Map<String, dynamic>.from(await _read(r) as Map);
          offset = value['offset'] as int;
        }
        check();
        await json('POST', '/api/v2/intents/$id/complete', {
          'generation': generation,
        });
      }
    }
    while (true) {
      check();
      final result = await get(id);
      state = result['state'];
      onState?.call(state?.toString() ?? 'queued');
      if (state == 'succeeded') return result['text'] as String? ?? '';
      if (state == 'failed' || state == 'cancelled')
        throw RemoteOcrException(
          result['error'] as String? ?? 'Không nhận diện được ảnh.',
        );
      await Future<void>.delayed(const Duration(milliseconds: 400));
    }
  }

  void close() {
    _closed = true;
    _http.close(force: true);
  }
}
