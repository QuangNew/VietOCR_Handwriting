import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vietocr_mobile/domain/app_controller.dart';
import 'package:vietocr_mobile/services/session_store.dart';
import 'package:vietocr_mobile/ui/image_detail_page.dart';
import 'controller_test.dart' show FakeEngine;

void main() {
  testWidgets(
    'touch freehand and rotated ellipse crop work on a narrow phone screen',
    (tester) async {
      tester.view.physicalSize = const Size(360, 780);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      late Directory folder;
      late AppController app;
      await tester.runAsync(() async {
        final font = File(
          '${Platform.environment['FLUTTER_ROOT'] ?? 'C:/Services/Flutter/flutter'}/bin/cache/artifacts/material_fonts/roboto-regular.ttf',
        );
        if (await font.exists()) {
          final loader = FontLoader('ReviewFont')
            ..addFont(
              font.readAsBytes().then((bytes) => ByteData.sublistView(bytes)),
            );
          await loader.load();
        }
        SharedPreferences.setMockInitialValues({});
        folder = await Directory.systemTemp.createTemp('vietocr_crop_ui_');
        app = AppController(
          store: SessionStore(directory: folder),
          engine: FakeEngine(),
        );
        await app.initialize(recoverLost: false);
        final image = img.Image(width: 400, height: 200)
          ..clear(img.ColorRgb8(245, 245, 245));
        for (var x = 30; x < 370; x += 30) {
          img.fillRect(
            image,
            x1: x,
            y1: 70,
            x2: x + 10,
            y2: 130,
            color: img.ColorRgb8(60, 60, 60),
          );
        }
        await app.importImages([(img.encodePng(image), 'source.png')]);
      });
      try {
        const key = ValueKey('screen');
        await tester.runAsync(() async {
          await tester.pumpWidget(
            MaterialApp(
              theme: ThemeData(
                useMaterial3: true,
                fontFamily: 'ReviewFont',
                colorScheme: ColorScheme.fromSeed(
                  seedColor: const Color(0xff0087bb),
                ),
              ),
              home: RepaintBoundary(
                key: key,
                child: ImageDetailPage(app: app, item: app.documents.first),
              ),
            ),
          );
          await Future<void>.delayed(const Duration(milliseconds: 200));
          await tester
              .pump(); // Resolve FileImage I/O in the real async zone too.
          await Future<void>.delayed(const Duration(milliseconds: 100));
        });
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await tester.tap(find.text('Chọn vùng crop'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Tự vẽ'));
        await tester.pumpAndSettle();
        final viewer = find.byType(InteractiveViewer);
        final bounds = tester.getRect(viewer), middle = bounds.center;
        final gesture = await tester.startGesture(
          middle + const Offset(-110, -38),
        );
        await gesture.moveBy(const Offset(220, 0));
        await gesture.moveBy(const Offset(0, 75));
        await gesture.moveBy(const Offset(-220, 0));
        await gesture.moveBy(const Offset(0, -75));
        await gesture.up();
        await tester.pumpAndSettle();
        final apply = find.widgetWithText(FilledButton, 'Lưu vùng cắt');
        expect(tester.widget<FilledButton>(apply).onPressed, isNotNull);
        expect(tester.widget<Slider>(find.byType(Slider)).onChanged, isNotNull);
        await tester.drag(find.byType(Slider), const Offset(15, 0));
        await tester.pumpAndSettle();
        // Store an actual rendered mobile screen alongside build evidence.
        await tester.runAsync(() async {
          final boundary = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(key),
          );
          final image = await boundary.toImage(pixelRatio: 2);
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          image.dispose();
          final output = File('build/verification/mobile-crop.png');
          await output.parent.create(recursive: true);
          await output.writeAsBytes(bytes!.buffer.asUint8List());
        });
        await tester.runAsync(() async {
          await tester.tap(apply);
          final until = DateTime.now().add(const Duration(seconds: 3));
          while ((app.documents.length < 2 || app.importing || app.busy) &&
              DateTime.now().isBefore(until)) {
            await Future<void>.delayed(const Duration(milliseconds: 20));
          }
          await app.flush();
          await Future<void>.delayed(const Duration(milliseconds: 50));
        });
        await tester.pumpAndSettle();
        expect(app.documents, hasLength(2));
        expect(File(app.documents.first.path).existsSync(), true);
        expect(app.documents.last.name, startsWith('Crop_'));
        await tester.tap(find.text('Elip'));
        await tester.pumpAndSettle();
        final nextCenter = tester.getRect(viewer).center;
        await tester.dragFrom(
          nextCenter + const Offset(-100, -35),
          const Offset(200, 70),
        );
        await tester.pumpAndSettle();
        expect(tester.widget<FilledButton>(apply).onPressed, isNotNull);
        await tester.drag(find.byType(Slider), const Offset(-10, 0));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      } finally {
        await tester.pumpWidget(const SizedBox.shrink());
        app.dispose();
        await tester.runAsync(() async {
          await app.flush();
          await Future<void>.delayed(const Duration(milliseconds: 150));
          try {
            await folder.delete(recursive: true);
          } on PathNotFoundException {
            // Windows may observe an already-removed temp entry while walking
            // the directory. Do not fail a successful crop on idempotent cleanup.
            if (await folder.exists()) rethrow;
          }
        });
      }
    },
  );
}
