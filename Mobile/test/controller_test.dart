import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vietocr_mobile/domain/app_controller.dart';
import 'package:vietocr_mobile/domain/document.dart';
import 'package:vietocr_mobile/main.dart';
import 'package:vietocr_mobile/ocr/decoder.dart';
import 'package:vietocr_mobile/ocr/offline_engine.dart';
import 'package:vietocr_mobile/services/session_store.dart';

class FakeEngine implements OcrEngine {
  int calls = 0;
  bool failFirst = false;
  String? result;
  bool workerDies = false;
  Completer<void>? gate;
  @override
  bool get loaded => true;
  @override
  Future<String> recognize(
    String path, {
    required bool split,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  }) async {
    calls++;
    progress('Đang đọc', .5);
    await gate?.future;
    cancel.check();
    if (workerDies) {
      throw PlatformException(code: 'OCR_PROCESS_DIED', message: 'AI đã dừng');
    }
    if (failFirst && calls == 1) throw StateError('Thử lại ảnh');
    return result ?? 'Tiếng Việt $calls';
  }

  @override
  Future<void> close() async {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory folder;
  late SessionStore store;
  late FakeEngine engine;
  late AppController app;
  final bytes = img.encodePng(
    img.Image(width: 8, height: 8)..clear(img.ColorRgb8(255, 255, 255)),
  );
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    folder = await Directory.systemTemp.createTemp('vietocr_test_');
    store = SessionStore(directory: folder);
    engine = FakeEngine();
    app = AppController(store: store, engine: engine);
    await app.initialize(recoverLost: false);
  });
  tearDown(() async {
    app.dispose();
    // Only delete the freshly created test directory under the OS temp root.
    if (folder.parent.absolute.path == Directory.systemTemp.absolute.path &&
        folder.path
            .split(Platform.pathSeparator)
            .last
            .startsWith('vietocr_test_')) {
      await folder.delete(recursive: true);
    }
  });
  test(
    'more than ten images accepted and restored from disk without truncation',
    () async {
      await app.importImages(
        List.generate(10, (index) => (bytes, '$index.png')),
      );
      await app.importImages([(bytes, 'eleventh.png')]);
      expect(app.documents, hasLength(11));
      expect(await store.load(), hasLength(11));
      await app.removeSelected();
      expect((await store.load()), hasLength(10));
    },
  );
  test(
    'OV3660 arrival during OCR is processed serially without repeating completed images',
    () async {
      await app.importImages([(bytes, 'first.png')]);
      engine.gate = Completer<void>();
      final running = app.recognize();
      await Future<void>.delayed(Duration.zero);
      expect(engine.calls, 1);
      await app.importImages([(bytes, 'OV3660.jpg')], enqueue: true);
      expect(engine.calls, 1);
      expect(app.documents, hasLength(2));
      engine.gate!.complete();
      await running;
      expect(engine.calls, 2);
      expect(
        app.documents.every((row) => row.status == DocumentStatus.done),
        isTrue,
      );
      await app.recognize();
      expect(engine.calls, 2);
    },
  );

  test(
    'native OV3660 JPEG stays full resolution and byte-for-byte on disk',
    () async {
      final jpeg = img.encodeJpg(
        img.Image(width: 2048, height: 1536)
          ..clear(img.ColorRgb8(80, 120, 180)),
        quality: 100,
      );
      await app.importImages([(jpeg, 'OV3660_native.jpg')]);
      final document = app.documents.single;
      expect(document.path.endsWith('.jpg'), isTrue);
      expect(await File(document.path).readAsBytes(), jpeg);
      final decoded = img.decodeJpg(await File(document.path).readAsBytes())!;
      expect((decoded.width, decoded.height), (2048, 1536));
    },
  );
  test(
    'an invalid image is reported and a following import still succeeds',
    () async {
      await app.importImages([(bytes.sublist(0, 2), 'bad.png')]);
      expect(app.documents, isEmpty);
      expect(app.importing, isFalse);
      await app.importImages([(bytes, 'valid.png')]);
      expect(app.documents, hasLength(1));
    },
  );
  test(
    'AI health check exercises the engine without adding a sample to the queue',
    () async {
      engine.result = 'KHÁI QUÁT VỀ BIỂN ĐẢO VIỆT NAM';
      await app.checkModel();
      expect(engine.calls, 1);
      expect(app.documents, isEmpty);
      expect(app.busy, isFalse);
      expect(app.message, contains('Kiểm tra AI đạt'));
    },
  );
  test(
    'AI check rejects numeric gibberish even if inference returns nonempty text',
    () async {
      engine.result = '1234567890';
      await app.checkModel();
      expect(app.message, contains('Kiểm tra AI chưa đạt'));
      expect(app.assistant, AssistantState.error);
      expect(app.documents, isEmpty);
    },
  );
  test(
    'failure on one image does not discard another result, and retry works',
    () async {
      engine.failFirst = true;
      await app.importImages([(bytes, 'one.png'), (bytes, 'two.png')]);
      await app.recognize();
      expect(app.documents.first.status, DocumentStatus.error);
      expect(app.documents.last.text, 'Tiếng Việt 2');
      expect(app.busy, isFalse);
      await app.recognize();
      expect(
        app.documents.every(
          (document) => document.status == DocumentStatus.done,
        ),
        isTrue,
      );
      app.edit(app.documents.first.id, 'Đã sửa dấu');
      await app.flush();
      expect((await store.load()).first.text, 'Đã sửa dấu');
    },
  );
  test(
    'cancellation prevents subsequent images, preserves existing text and permits retry',
    () async {
      await app.importImages([(bytes, 'one.png'), (bytes, 'two.png')]);
      app.edit(app.documents.first.id, 'Kết quả cũ');
      engine.gate = Completer<void>();
      final running = app.recognize();
      await Future<void>.delayed(Duration.zero);
      app.cancel();
      engine.gate!.complete();
      await running;
      expect(engine.calls, 1);
      expect(app.documents.first.text, 'Kết quả cũ');
      expect(app.documents.first.status, DocumentStatus.cancelled);
      expect(app.busy, isFalse);
      engine.gate = null;
      await app.recognize();
      expect(engine.calls, 3);
    },
  );
  test(
    'a dead AI process stops the batch, preserves text and can be retried',
    () async {
      await app.importImages([(bytes, 'one.png'), (bytes, 'two.png')]);
      app.edit(app.documents.first.id, 'Văn bản đã sửa');
      engine.workerDies = true;
      await app.recognize();
      expect(engine.calls, 1);
      expect(app.busy, isFalse);
      expect(app.documents.first.text, 'Văn bản đã sửa');
      expect(app.documents.last.status, DocumentStatus.ready);
      expect(app.message, contains('AI gặp lỗi'));
      engine.workerDies = false;
      await app.recognize();
      expect(
        app.documents.every(
          (document) => document.status == DocumentStatus.done,
        ),
        isTrue,
      );
    },
  );
  test('session restores interrupted processing as cancelled', () async {
    await app.importImages([(bytes, 'one.png')]);
    app.documents.first.status = DocumentStatus.processing;
    await app.flush();
    expect((await store.load()).single.status, DocumentStatus.cancelled);
  });
  testWidgets(
    'small phone supports dark theme, theme toggle and the Bluetooth button',
    (tester) async {
      tester.view.physicalSize = const Size(360, 780);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        VietOcrApp(controller: app, enableBluetooth: false),
      );
      await tester.pump();
      expect(
        Theme.of(tester.element(find.text('VietOCR'))).brightness,
        Brightness.dark,
      );
      final headings = [
        'Đọc chữ từ ảnh',
        'Hoạt động ngoại tuyến',
        'Chụp điện thoại',
      ];
      final geometry = [
        for (final text in headings) tester.getRect(find.text(text)),
      ];
      await tester.tap(find.byTooltip('Giao diện sáng'));
      await tester.pump(const Duration(milliseconds: 16));
      expect([
        for (final text in headings) tester.getRect(find.text(text)),
      ], geometry);
      await tester.pump(const Duration(milliseconds: 300));
      expect([
        for (final text in headings) tester.getRect(find.text(text)),
      ], geometry);
      expect(app.dark, isFalse);
      await tester.tap(find.text('Trợ lý'));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Bật Bluetooth'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
