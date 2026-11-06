import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/ocr/decoder.dart';
import 'package:vietocr_mobile/ocr/remote_engine.dart';
import 'package:vietocr_mobile/services/vietocr_remote.dart';

void main() {
  test(
    'daily quota is shown once and never retried as an upload failure',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final dir = await Directory.systemTemp.createTemp('vietocr-quota');
      final file = File('${dir.path}/image.jpg');
      await file.writeAsBytes(List.filled(30, 1));
      var attempts = 0;
      final listener = server.listen((r) async {
        attempts++;
        await r.drain<void>();
        r.response.statusCode = 429;
        r.response.headers.contentType = ContentType.json;
        r.response.headers.set('Retry-After', '3600');
        r.response.write(
          jsonEncode({
            'error': 'daily_quota',
            'message': 'Đã hết hạn mức OCR hôm nay.',
          }),
        );
        await r.response.close();
      });
      final engine = RemoteEngine(
        'http://127.0.0.1:${server.port}',
        '',
        tokenProvider: () async => 'fresh-session',
      );
      try {
        await expectLater(
          engine.recognize(
            file.path,
            split: false,
            rotation: 0,
            cancel: CancellationToken(),
            progress: (_, _) {},
          ),
          throwsA(
            isA<RemoteOcrException>().having(
              (e) => e.code,
              'quota',
              'daily_quota',
            ),
          ),
        );
        expect(attempts, 1);
      } finally {
        await engine.close();
        await listener.cancel();
        await server.close(force: true);
        await dir.delete(recursive: true);
      }
    },
  );
  test('missing Google session cannot send an unauthenticated image', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final dir = await Directory.systemTemp.createTemp('vietocr-auth');
    final file = File('${dir.path}/image.jpg');
    await file.writeAsBytes(List.filled(30, 1));
    var requests = 0;
    final listener = server.listen((r) async {
      requests++;
      await r.response.close();
    });
    final client = VietOcrRemote(
      'http://127.0.0.1:${server.port}',
      '',
      tokenProvider: () async {
        throw const RemoteOcrException('Đăng nhập Google', status: 401);
      },
    );
    try {
      await expectLater(
        client.submit(file),
        throwsA(
          isA<RemoteOcrException>().having((e) => e.status, 'status', 401),
        ),
      );
      expect(requests, 0);
    } finally {
      client.close();
      await listener.cancel();
      await server.close(force: true);
      await dir.delete(recursive: true);
    }
  });
  test('server transport refuses untrusted HTTP origins', () {
    expect(
      () => VietOcrRemote('http://example.com', 'voc_key'),
      throwsArgumentError,
    );
    final client = VietOcrRemote('https://example.com', 'voc_key');
    client.close();
  });
  test(
    'remote engine uploads once, polls result and forwards layout',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final dir = await Directory.systemTemp.createTemp('vietocr-remote');
      final file = File('${dir.path}/image.jpg');
      await file.writeAsBytes(List.filled(30, 1));
      final seen = <String>[];
      var uploads = 0;
      final listener = server.listen((r) async {
        seen.add('${r.method} ${r.uri.path}');
        expect(r.headers.value('authorization'), 'Bearer voc_private');
        r.response.headers.contentType = ContentType.json;
        if (r.method == 'POST') {
          uploads++;
          final body = await utf8.decoder.bind(r).join();
          expect(body, contains('line'));
          expect(r.headers.value('idempotency-key'), isNotEmpty);
          r.response.statusCode = 202;
          r.response.write(jsonEncode({'id': 'a' * 32, 'state': 'queued'}));
        } else {
          r.response.write(
            jsonEncode({
              'id': 'a' * 32,
              'state': 'succeeded',
              'text': 'Chúc giáng sinh vui vẻ',
            }),
          );
        }
        await r.response.close();
      });
      final engine = RemoteEngine(
        'http://127.0.0.1:${server.port}',
        'voc_private',
      );
      try {
        final text = await engine.recognize(
          file.path,
          split: false,
          rotation: 0,
          cancel: CancellationToken(),
          progress: (_, _) {},
        );
        expect(text, 'Chúc giáng sinh vui vẻ');
        expect(uploads, 1);
        expect(seen.length, 2);
      } finally {
        await engine.close();
        await listener.cancel();
        await server.close(force: true);
        await dir.delete(recursive: true);
      }
    },
  );
  test(
    'already cancelled request does not open a file or load model',
    () async {
      final engine = RemoteEngine('http://127.0.0.1:5080', 'voc_key');
      final cancel = CancellationToken()..cancel();
      try {
        await expectLater(
          engine.recognize(
            'missing',
            split: true,
            rotation: 0,
            cancel: cancel,
            progress: (_, _) {},
          ),
          throwsA(isA<OcrCancelled>()),
        );
      } finally {
        await engine.close();
      }
    },
  );
}
