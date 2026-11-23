import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vietocr_mobile/domain/app_controller.dart';
import 'package:vietocr_mobile/domain/document.dart';
import 'package:vietocr_mobile/ocr/cancellation.dart';
import 'package:vietocr_mobile/ocr/engine.dart';
import 'package:vietocr_mobile/ocr/paper_detector.dart';
import 'package:vietocr_mobile/services/session_store.dart';
import 'package:vietocr_mobile/ui/document_page.dart';

class _RichFakeEngine implements OcrEngine, RichOcrEngine {
  int calls = 0;

  @override
  bool get loaded => true;

  @override
  Future<void> close() async {}

  @override
  Future<String> recognize(
    String path, {
    required bool split,
    bool correct = false,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  }) async => (await recognizeRich(
    path,
    split: split,
    correct: correct,
    rotation: rotation,
    cancel: cancel,
    progress: progress,
  )).text;

  @override
  Future<OcrArtifactResult> recognizeRich(
    String path, {
    required bool split,
    bool correct = false,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  }) async {
    calls++;
    return const OcrArtifactResult(
      text: 'Ngày mồng một đầu năm\nCô bé bán diêm',
      jobId: 'job-rich-001',
      hasPipeline: true,
      lens: {
        'sourceWidth': 800,
        'sourceHeight': 600,
        'paperDetected': true,
        'paperQuad': [
          [120.0, 60.0],
          [680.0, 60.0],
          [680.0, 540.0],
          [120.0, 540.0],
        ],
        'lines': [
          {
            'id': 1,
            'text': 'Ngày mồng một đầu năm',
            'polygon': [
              [160.0, 140.0],
              [620.0, 140.0],
              [620.0, 210.0],
              [160.0, 210.0],
            ],
          },
          {
            'id': 2,
            'text': 'Cô bé bán diêm',
            'polygon': [
              [160.0, 260.0],
              [520.0, 260.0],
              [520.0, 330.0],
              [160.0, 330.0],
            ],
          },
        ],
      },
    );
  }

  @override
  Future<Map<String, dynamic>?> fetchPipeline(String jobId) async => {
    'route': 'scanner',
    'paperDetected': true,
    'sourceWidth': 800,
    'sourceHeight': 600,
    'corrected': true,
    'timings': {
      'preprocessMs': 120,
      'segmentMs': 90,
      'recognitionMs': 410,
      'correctionMs': 140,
      'totalMs': 760,
    },
    'lines': [
      {
        'id': 1,
        'rawText': 'Ngay mồng một đầu năm',
        'text': 'Ngày mồng một đầu năm',
        'changed': true,
        'ms': 190,
      },
    ],
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('detectPaperQuadFromRgba isolates cool paper and ignores wood glare', () {
    const w = 160, h = 100;
    final rgba = Uint8List(w * h * 4);
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        final i = (y * w + x) * 4;
        var r = 145, g = 118, b = 90;
        if (x >= 115 && y >= 65) {
          r = 186;
          g = 174;
          b = 150;
        }
        if (x >= 40 && x <= 112 && y >= 16 && y <= 84) {
          r = 196;
          g = 208;
          b = 216;
          if (y % 12 == 0 && x >= 48 && x <= 104) {
            r = 45;
            g = 60;
            b = 110;
          }
        }
        rgba[i] = r;
        rgba[i + 1] = g;
        rgba[i + 2] = b;
        rgba[i + 3] = 255;
      }
    }
    final det = detectPaperQuadFromRgba(rgba, w, h, natW: 1600, natH: 1000);
    expect(det, isNotNull);
    final pb = polygonBounds(det!.paperQuad);
    expect(pb.minX, inInclusiveRange(340, 430));
    expect(pb.maxX, inInclusiveRange(1090, 1185));
    expect(pb.minY, inInclusiveRange(120, 190));
    expect(pb.maxY, inInclusiveRange(810, 890));
  });

  test('linesInsideQuad filters lines inside user-adjusted Lens quad', () {
    final quad = <Point2D>[
      [100, 100],
      [500, 100],
      [500, 300],
      [100, 300],
    ];
    final lines = [
      {
        'id': 1,
        'text': 'Trong khung',
        'polygon': [
          [120, 140],
          [420, 140],
          [420, 180],
          [120, 180],
        ],
      },
      {
        'id': 2,
        'text': 'Ngoài khung',
        'polygon': [
          [120, 360],
          [420, 360],
          [420, 400],
          [120, 400],
        ],
      },
    ];
    final inside = linesInsideQuad(lines, quad);
    expect(inside.map((l) => l['id']), [1]);
  });

  test(
    'cameraAutoSend toggle persists and enqueueAutoSend populates lens & pipeline metadata',
    () async {
      SharedPreferences.setMockInitialValues({});
      final dir = await Directory.systemTemp.createTemp('vietocr_auto_send_');
      final store = SessionStore(directory: dir);
      final engine = _RichFakeEngine();
      final app = AppController(store: store, engine: engine);
      try {
        await app.initialize(recoverLost: false);
        expect(app.cameraAutoSend, isTrue);
        await app.setCameraAutoSend(false);
        expect(app.cameraAutoSend, isFalse);
        await app.setCameraAutoSend(true);

        final png = img.encodePng(
          img.Image(width: 40, height: 30)
            ..clear(img.ColorRgb8(230, 236, 240)),
        );
        await app.importImages([(png, 'cam_01.png')]);
        final doc = app.documents.single;
        app.enqueueAutoSend(doc.id);
        await Future<void>.delayed(const Duration(milliseconds: 50));

        expect(engine.calls, 1);
        expect(doc.status, DocumentStatus.done);
        expect(doc.jobId, 'job-rich-001');
        expect(doc.hasPipeline, isTrue);
        expect(doc.lens?['lines'], hasLength(2));
      } finally {
        app.dispose();
        await dir.delete(recursive: true);
      }
    },
  );

  testWidgets(
    'DocumentPage fits 360x780 phone screen cleanly across Ảnh gốc, Ảnh văn bản, and Đối chiếu',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      late Directory dir;
      late AppController app;
      late Document doc;
      tester.view.physicalSize = const Size(360, 780);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.runAsync(() async {
        dir = await Directory.systemTemp.createTemp('vietocr_doc_ui_');
        final store = SessionStore(directory: dir);
        final engine = _RichFakeEngine();
        app = AppController(store: store, engine: engine);
        await app.initialize(recoverLost: false);
        final png = img.encodePng(
          img.Image(width: 200, height: 150)
            ..clear(img.ColorRgb8(210, 220, 228)),
        );
        await app.importImages([(png, 'demo_page.png')]);
        await app.recognize();
        doc = app.documents.single;
      });

      try {
        await tester.pumpWidget(
          MaterialApp(
            home: DocumentPage(app: app, id: doc.id),
          ),
        );
        await tester.pump(const Duration(milliseconds: 50));
        await tester.pump(const Duration(milliseconds: 100));

        expect(find.text('Ảnh gốc'), findsOneWidget);
        expect(find.text('Ảnh văn bản'), findsOneWidget);
        expect(find.text('Đối chiếu'), findsOneWidget);
        expect(find.text('Pipeline'), findsOneWidget);

        // Switch to Ảnh văn bản
        await tester.tap(find.text('Ảnh văn bản'));
        await tester.pump(const Duration(milliseconds: 200));
        expect(tester.takeException(), isNull);

        // Switch to Đối chiếu
        await tester.tap(find.text('Đối chiếu'));
        await tester.pump(const Duration(milliseconds: 200));
        expect(find.byIcon(Icons.compare_arrows_rounded), findsOneWidget);
        expect(tester.takeException(), isNull);

        await tester.pumpWidget(const SizedBox());
      } finally {
        await tester.runAsync(() async {
          app.dispose();
          if (await dir.exists()) await dir.delete(recursive: true);
        });
      }
    },
  );

  test('tightenLinePolygons prevents tall boxes from bleeding into neighbor lines', () {
    final raw = <Map<String, dynamic>>[
      {
        'id': 1,
        'polygon': [
          [594.5, 510.5],
          [1500.5, 510.5],
          [1500.5, 619.5],
          [594.5, 619.5],
        ],
      },
      {
        'id': 2,
        'polygon': [
          [587.5, 578.5],
          [1472.5, 578.5],
          [1472.5, 682.5],
          [587.5, 682.5],
        ],
      },
      {
        'id': 3,
        'polygon': [
          [583.5, 630.5],
          [1481.5, 630.5],
          [1481.5, 748.5],
          [583.5, 748.5],
        ],
      },
    ];
    final tight = tightenLinePolygons(raw);
    for (var i = 1; i <= 2; i++) {
      final a = polygonBounds(tight[i]!);
      final b = polygonBounds(tight[i + 1]!);
      expect(a.maxY, lessThan(b.minY));
    }
  });
}
