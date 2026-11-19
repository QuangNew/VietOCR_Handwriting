import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vietocr_mobile/ocr/transfer_file.dart';

void main() {
  test(
    'automatic Send derivative is cached without replacing the original',
    () async {
      final dir = await Directory.systemTemp.createTemp('vietocr-transfer-');
      try {
        final source = File('${dir.path}/source.png');
        final bytes = img.encodePng(
          img.Image(width: 512, height: 256),
          level: 0,
        );
        await source.writeAsBytes(bytes);
        final wire = await automaticTransfer(source);
        expect(wire.path, isNot(source.path));
        expect(await wire.length(), lessThan(bytes.length));
        expect(await source.readAsBytes(), bytes);
        final decoded = img.decodeImage(await wire.readAsBytes())!;
        expect((decoded.width, decoded.height), (512, 256));
        expect((await automaticTransfer(source)).path, wire.path);
        expect(
          (await automaticTransfer(source, create: false)).path,
          wire.path,
        );
        expect(await dir.list().length, 2);
      } finally {
        await dir.delete(recursive: true);
      }
    },
  );
  test(
    'a pre-existing request resumes the old bytes without recompression',
    () async {
      final dir = await Directory.systemTemp.createTemp('vietocr-transfer-');
      try {
        final source = File('${dir.path}/source.jpg');
        await source.writeAsBytes([1, 2, 3]);
        await File(
          '${source.path}.ocr-v2.json',
        ).writeAsString('{"jobId":"existing"}');
        expect((await automaticTransfer(source)).path, source.path);
        expect(await dir.list().length, 2);
      } finally {
        await dir.delete(recursive: true);
      }
    },
  );
}
