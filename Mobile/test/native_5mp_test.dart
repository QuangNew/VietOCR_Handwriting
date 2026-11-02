import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vietocr_mobile/services/session_store.dart';

void main() {
  test(
    '5 MP mirrored camera JPEG keeps resolution, pixels and original bytes through session restore',
    () async {
      final directory = await Directory.systemTemp.createTemp('vietocr_5mp_');
      try {
        final image = img.Image(width: 2592, height: 1944)
          ..clear(img.ColorRgb8(230, 230, 230));
        img.fillRect(
          image,
          x1: 0,
          y1: 0,
          x2: 150,
          y2: 150,
          color: img.ColorRgb8(255, 0, 0),
        );
        img.fillRect(
          image,
          x1: 2440,
          y1: 0,
          x2: 2591,
          y2: 150,
          color: img.ColorRgb8(0, 0, 255),
        );
        final mirrored = img.flipHorizontal(image);
        final jpeg = Uint8List.fromList(img.encodeJpg(mirrored, quality: 90));
        final store = SessionStore(directory: directory);
        final item = await store.import(jpeg, 'OV5640_42.jpg', 'photo');
        expect(item.path, endsWith('.jpg'));
        expect(await File(item.path).readAsBytes(), jpeg);
        await store.save([item]);
        final restored = await store.load();
        final original = await File(restored.single.path).readAsBytes();
        expect(original, jpeg);
        final decoded = img.decodeJpg(original)!;
        expect((decoded.width, decoded.height), (2592, 1944));
        final left = decoded.getPixel(50, 50);
        expect(left.b, greaterThan(left.r)); // no second software mirror
      } finally {
        await directory.delete(recursive: true);
      }
    },
  );
}
