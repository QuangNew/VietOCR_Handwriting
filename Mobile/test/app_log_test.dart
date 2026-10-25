import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/app_log.dart';
import 'package:vietocr_mobile/ui/log_page.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const native = MethodChannel('vietocr/ocr');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() => messenger.setMockMethodCallHandler(native, null));

  test(
    'log is bounded, stores error stack, persists and recovers after restart',
    () async {
      final folder = await Directory.systemTemp.createTemp('vietocr_log_');
      try {
        final log = AppLog(directory: folder);
        await log.initialize();
        for (var i = 0; i < 305; i++) {
          log.add('test', 'event $i');
        }
        log.add(
          'OCR',
          'Failed',
          level: 'ERROR',
          error: StateError('root cause'),
          stack: StackTrace.current,
        );
        expect(log.entries.length, 300);
        expect(log.text, contains('root cause'));
        await log.flush();
        // A torn line after a crash must not hide valid earlier records.
        await File(
          '${folder.path}/app-log.jsonl',
        ).writeAsString('{broken', mode: FileMode.append);
        final recovered = AppLog(directory: folder);
        await recovered.initialize();
        expect(recovered.entries.length, 300);
        expect(recovered.entries.last.level, 'ERROR');
        expect(recovered.entries.last.detail, contains('app_log_test.dart'));
        await recovered.clear();
        expect(recovered.entries, isEmpty);
        expect(
          await File('${folder.path}/app-log.jsonl').readAsString(),
          isEmpty,
        );
        log.dispose();
        recovered.dispose();
      } finally {
        await folder.delete(
          recursive: true,
        ); // Only this test's newly created folder.
      }
    },
  );
  test(
    'native error details are captured once and clear resets native log',
    () async {
      var clears = 0;
      messenger.setMockMethodCallHandler(native, (call) async {
        if (call.method == 'clearNativeLogs') {
          clears++;
          return null;
        }
        return jsonEncode({
          'time': 123,
          'pid': 42,
          'stage': 'error',
          'level': 'ERROR',
          'detail': 'OrtException: bad tensor',
        });
      });
      final log = AppLog(persist: false);
      await log.captureNative();
      await log.captureNative();
      expect(log.entries.length, 1);
      expect(log.entries.single.detail, contains('OrtException'));
      await log.clear();
      expect(clears, 1);
      expect(log.entries, isEmpty);
      log.dispose();
    },
  );
  test('a long native history is not duplicated on every poll', () async {
    messenger.setMockMethodCallHandler(
      native,
      (_) async => List.generate(
        400,
        (i) =>
            jsonEncode({'time': i, 'pid': 42, 'stage': 'ready', 'detail': ''}),
      ).join('\n'),
    );
    final log = AppLog(persist: false);
    await log.captureNative();
    expect(log.entries.length, 250);
    await log.captureNative();
    expect(log.entries.length, 250);
    log.dispose();
  });
  testWidgets(
    'log tab shows error details and filters events on small screens',
    (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final log = AppLog(persist: false)
        ..add('BLE', 'Connected')
        ..add('OCR', 'Failed', level: 'ERROR', error: 'native root cause');
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: LogPage(log: log)),
        ),
      );
      await tester.pump();
      expect(find.textContaining('BLE · Connected'), findsOneWidget);
      await tester.tap(find.text('Chỉ lỗi'));
      await tester.pumpAndSettle();
      expect(find.textContaining('BLE · Connected'), findsNothing);
      await tester.tap(find.textContaining('OCR · Failed'));
      await tester.pumpAndSettle();
      expect(find.textContaining('native root cause'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      log.dispose();
    },
  );
}
