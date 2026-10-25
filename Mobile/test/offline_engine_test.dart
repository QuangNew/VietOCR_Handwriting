import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vietocr_mobile/ocr/offline_engine.dart';
import 'package:vietocr_mobile/ocr/decoder.dart';
import 'package:vietocr_mobile/ocr/image_processing.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  test('an empty detected row does not discard text from later rows', () async {
    final folder = await Directory.systemTemp.createTemp('vietocr_rows_');
    final image = img.Image(width: 200, height: 100)
      ..clear(img.ColorRgb8(255, 255, 255));
    for (final top in [20, 65]) {
      for (var x = 20; x < 170; x += 15) {
        img.fillRect(
          image,
          x1: x,
          y1: top,
          x2: x + 7,
          y2: top + 14,
          color: img.ColorRgb8(0, 0, 0),
        );
      }
    }
    final photo = File('${folder.path}/sample.png');
    await photo.writeAsBytes(img.encodePng(image));
    var lines = 0;
    messenger.setMockMethodCallHandler(OfflineEngine.channel, (call) async {
      if (call.method == 'line') return ++lines == 1 ? '' : 'Tiếng Việt';
      return 'ready';
    });
    final engine = OfflineEngine(temporaryDirectory: () async => folder);
    try {
      expect(
        await engine.recognize(
          photo.path,
          split: true,
          rotation: 0,
          cancel: CancellationToken(),
          progress: (_, _) {},
        ),
        'Tiếng Việt',
      );
      expect(lines, 2);
    } finally {
      await engine.close();
      messenger.setMockMethodCallHandler(OfflineEngine.channel, null);
      await folder.delete(
        recursive: true,
      ); // Only this test's temporary folder.
    }
  });
  test(
    'failed model load can retry; worker death leaves the engine reusable',
    () async {
      final folder = await Directory.systemTemp.createTemp('vietocr_engine_');
      final engine = OfflineEngine(temporaryDirectory: () async => folder);
      var loads = 0, lines = 0;
      messenger.setMockMethodCallHandler(OfflineEngine.channel, (call) async {
        if (call.method == 'load' && ++loads == 1) {
          throw PlatformException(code: 'OCR_PROCESS_DIED');
        }
        if (call.method == 'line') {
          final file = File(call.arguments['path'] as String);
          expect(await file.length(), 3 * 32 * 32 * 4);
          if (++lines == 1) throw PlatformException(code: 'OCR_PROCESS_DIED');
          return 'Tiếng Việt';
        }
        return 'ready';
      });
      try {
        await expectLater(
          engine.load((_, _) {}),
          throwsA(isA<PlatformException>()),
        );
        await engine.load((_, _) {});
        final tensor = LineTensor(32, Float32List(3 * 32 * 32));
        await expectLater(
          engine.recognizeTensor(tensor, CancellationToken()),
          throwsA(isA<PlatformException>()),
        );
        expect(engine.loaded, isFalse);
        expect(
          await engine.recognizeTensor(tensor, CancellationToken()),
          'Tiếng Việt',
        );
        expect(loads, 3);
        expect(Directory('${folder.path}/ocr-input').listSync(), isEmpty);
      } finally {
        await engine.close();
        messenger.setMockMethodCallHandler(OfflineEngine.channel, null);
        await folder.delete(
          recursive: true,
        ); // Only this test's newly created temp directory.
      }
    },
  );
  test(
    'cancel interrupts pending initialization and resets the native worker once',
    () async {
      final pending = Completer<String>();
      var resets = 0;
      messenger.setMockMethodCallHandler(OfflineEngine.channel, (call) async {
        if (call.method == 'load') return pending.future;
        if (call.method == 'reset') {
          resets++;
          pending.completeError(PlatformException(code: 'OCR_CANCELLED'));
        }
        return null;
      });
      final token = CancellationToken(), engine = OfflineEngine();
      final running = engine.load((_, _) {}, cancel: token);
      token.cancel();
      await expectLater(running, throwsA(isA<OcrCancelled>()));
      expect(resets, 1);
      expect(engine.loaded, isFalse);
      messenger.setMockMethodCallHandler(
        OfflineEngine.channel,
        (_) async => null,
      );
      await engine.close();
      messenger.setMockMethodCallHandler(OfflineEngine.channel, null);
    },
  );
}
