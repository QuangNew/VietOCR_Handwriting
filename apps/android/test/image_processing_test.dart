import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vietocr_mobile/ocr/image_processing.dart';

void main() {
  test('camera EXIF orientation is baked into the image dimensions', () {
    final image = img.Image(width: 40, height: 20)
      ..clear(img.ColorRgb8(255, 255, 255));
    image.exif.imageIfd.orientation = 6;
    final decoded = decodePhoto(img.encodeJpg(image));
    expect(decoded.width, 20);
    expect(decoded.height, 40);
  });
  test(
    'invalid image and oversized header are rejected before allocating pixels',
    () {
      expect(
        () => decodePhoto(Uint8List.fromList([1, 2, 3])),
        throwsFormatException,
      );
      final small = img.encodeBmp(img.Image(width: 2, height: 2));
      final header = ByteData.sublistView(small);
      header.setInt32(18, 50000, Endian.little);
      header.setInt32(22, 50000, Endian.little);
      expect(() => decodePhoto(small), throwsFormatException);
    },
  );
}
