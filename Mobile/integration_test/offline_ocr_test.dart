import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:vietocr_mobile/ocr/decoder.dart';
import 'package:vietocr_mobile/ocr/image_processing.dart';
import 'package:vietocr_mobile/ocr/offline_engine.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'bundled model runs on Android and agrees with the original PyTorch output',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: Text('Offline OCR verification')),
        ),
      );
      final engine = OfflineEngine();
      try {
        await engine.load((_, _) {});
        final reference =
            jsonDecode(
                  await rootBundle.loadString('assets/samples/reference.json'),
                )
                as Map<String, dynamic>;
        final tensor = await rootBundle.load('assets/samples/reference.f32');
        final values = Float32List(tensor.lengthInBytes ~/ 4);
        for (var i = 0; i < values.length; i++) {
          values[i] = tensor.getFloat32(i * 4, Endian.little);
        }
        final result = await engine.recognizeTensor(
          LineTensor(reference['width'] as int, values),
          CancellationToken(),
        );
        expect(result, reference['text']);
        // Exercise decoding, Dart preprocessing, native sessions and repeated runs.
        final directory = await getTemporaryDirectory();
        for (final name in ['test.jpg', 'test2.jpg']) {
          final bytes = await rootBundle.load('assets/samples/$name');
          final file = File('${directory.path}/integration_$name');
          await file.writeAsBytes(
            bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes),
          );
          final text = await engine.recognize(
            file.path,
            split: true,
            rotation: 0,
            cancel: CancellationToken(),
            progress: (_, _) {},
          );
          expect(text.trim(), isNotEmpty);
          await file.delete();
        }
      } finally {
        await engine.close();
      }
    },
    timeout: const Timeout(Duration(minutes: 8)),
  );
}
