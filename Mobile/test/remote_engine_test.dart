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
      await file.writeAsBytes(
        await File('assets/samples/test.jpg').readAsBytes(),
      );
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
  test(
    'missing Google session cannot send an unauthenticated request',
    () async {
      final remote = VietOcrRemote('http://127.0.0.1:5082', '');
      try {
        await expectLater(remote.account(), throwsA(isA<RemoteOcrException>()));
      } finally {
        remote.close();
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
