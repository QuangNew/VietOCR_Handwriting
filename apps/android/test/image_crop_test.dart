import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vietocr_mobile/ui/image_detail_page.dart';

void main() {
  test(
    'crop coordinates use original pixels, retain colour and respect rotation',
    () {
      final source = img.Image(width: 10, height: 8);
      for (final pixel in source) {
        pixel.setRgb(pixel.x * 20, pixel.y * 20, 30);
      }
      final bytes = Uint8List.fromList(img.encodePng(source));
      final cropped = img.decodePng(cropOriginal((bytes, 0, 2, 3, 6, 4)))!;
      expect((cropped.width, cropped.height), (6, 4));
      expect(cropped.getPixel(0, 0).r, source.getPixel(2, 3).r);
      expect(cropped.getPixel(0, 0).g, source.getPixel(2, 3).g);
      final rotated = img.decodePng(cropOriginal((bytes, 1, 0, 0, 8, 10)))!;
      expect((rotated.width, rotated.height), (8, 10));
      expect(rotated.getPixel(0, 0).g, source.getPixel(0, 7).g);
      expect(() => cropOriginal((bytes, 0, 9, 7, 5, 5)), throwsFormatException);
      expect(img.decodePng(bytes)!.width, 10);
    },
  );
}
