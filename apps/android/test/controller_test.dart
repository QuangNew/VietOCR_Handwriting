import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vietocr_mobile/domain/app_controller.dart';
import 'package:vietocr_mobile/domain/document.dart';
import 'package:vietocr_mobile/main.dart';
import 'package:vietocr_mobile/ocr/cancellation.dart';
import 'package:vietocr_mobile/ocr/engine.dart';
import 'package:vietocr_mobile/services/session_store.dart';
import 'package:vietocr_mobile/services/vietocr_remote.dart';

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
      throw const RemoteOcrException('Server chưa sẵn sàng', status: 503);
    }
    if (failFirst && calls == 1) throw StateError('Thử lại ảnh');
    return result ?? 'Tiếng Việt $calls';
  }

  @override
  Future<void> close() async {}
}

class ParallelFakeEngine extends FakeEngine implements ConcurrentOcrEngine {
  @override
  int get parallelRequests => 2;
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
      await app.remove(app.documents.last.id);
      expect((await store.load()), hasLength(10));
    },
  );
  test(
    'new capture during Send stays draft until the next explicit Send',
    () async {
      await app.importImages([(bytes, 'first.png')]);
      engine.gate = Completer<void>();
      final running = app.recognize();
      await Future<void>.delayed(Duration.zero);
      expect(engine.calls, 1);
      await app.importImages([(bytes, 'camera.jpg')]);
      expect(engine.calls, 1);
      expect(app.documents, hasLength(2));
      engine.gate!.complete();
      await running;
      expect(engine.calls, 1);
      expect(app.documents.last.status, DocumentStatus.ready);
      await app.recognize();
      expect(engine.calls, 2);
    },
  );
  test(
    'remote batch uses two slots without auto-sending photos captured later',
    () async {
      final parallel = ParallelFakeEngine()..gate = Completer<void>();
      app.engine = parallel;
      await app.importImages([
        (bytes, 'one.png'),
        (bytes, 'two.png'),
        (bytes, 'three.png'),
      ]);
      final operation = app.recognize();
      await Future<void>.delayed(Duration.zero);
      expect(parallel.calls, 2);
      await app.importImages([(bytes, 'later.png')]);
      expect(parallel.calls, 2);
      parallel.gate!.complete();
      await operation;
      expect(parallel.calls, 3);
      expect(app.documents.last.status, DocumentStatus.ready);
    },
  );
  test(
    'an unchecked source stays on disk and only the chosen derivative is submitted',
    () async {
      await app.importImages([(bytes, 'source.png'), (bytes, 'crop.png')]);
      final source = app.documents.first;
      app.setIncluded(source.id, false);
      await app.flush();
      expect(app.sendCount, 1);
      expect((await store.load()).first.included, false);
      await app.recognize();
      expect(engine.calls, 1);
      expect(app.documents.first.status, DocumentStatus.ready);
      expect(await File(source.path).exists(), true);
      expect(app.documents.last.status, DocumentStatus.done);
    },
  );

  test('Send from document details submits that image alone', () async {
    await app.importImages([(bytes, 'one.png'), (bytes, 'two.png')]);
    final first = app.documents.first;
    app.setIncluded(first.id, false);
    await app.recognize(only: first.id, split: false);
    expect(engine.calls, 1);
    expect(first.text, 'Tiếng Việt 1');
    expect(app.documents.last.status, DocumentStatus.ready);
  });

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
    'unavailable server stops the batch, preserves text and can be retried',
    () async {
      await app.importImages([(bytes, 'one.png'), (bytes, 'two.png')]);
      app.edit(app.documents.first.id, 'Văn bản đã sửa');
      engine.workerDies = true;
      await app.recognize();
      expect(engine.calls, 1);
      expect(app.busy, isFalse);
      expect(app.documents.first.text, 'Văn bản đã sửa');
      expect(app.documents.last.status, DocumentStatus.ready);
      expect(app.message, contains('Hàng đợi đã tạm dừng'));
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
    'small phone supports stable theme and Raspberry camera without Bluetooth',
    (tester) async {
      tester.view.physicalSize = const Size(360, 780);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(VietOcrApp(controller: app));
      await tester.pumpAndSettle();
      expect(find.text('Chụp tài liệu'), findsOneWidget);
      final rect = tester.getRect(find.text('Tài liệu của bạn'));
      await tester.tap(find.byTooltip('Cài đặt'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Giao diện tối'));
      await tester.pumpAndSettle();
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(app.dark, isFalse);
      expect(tester.getRect(find.text('Tài liệu của bạn')), rect);
      expect(find.text('Bật Bluetooth'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
