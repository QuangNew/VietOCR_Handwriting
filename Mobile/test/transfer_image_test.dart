import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vietocr_mobile/ocr/transfer_image.dart';

void main() {
  test(
    'automatic transfer optimisation never resizes or overwrites the source',
    () {
      final photo = img.Image(width: 512, height: 256);
      for (var y = 0; y < photo.height; y++) {
        for (var x = 0; x < photo.width; x++) {
          photo.setPixelRgb(
            x,
            y,
            (x * 13 + y * 3) % 256,
            y % 30 < 3 ? 20 : 230,
            (x + y) % 256,
          );
        }
      }
      final bytes = img.encodePng(photo, level: 0), copy = List<int>.of(bytes);
      final result = optimizeTransfer((bytes, 0));
      expect(result, isNotNull);
      expect(result!.bytes.length, lessThan(bytes.length));
      final decoded = img.decodeImage(result.bytes)!;
      expect((decoded.width, decoded.height), (512, 256));
      expect(bytes, copy);
    },
  );
}
