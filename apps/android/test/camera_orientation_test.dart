import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vietocr_mobile/ui/pi_camera_page.dart';

void main() {
  test('camera mirror keeps full dimensions and reverses pixels only once', () {
    final source = img.Image(width: 12, height: 8);
    for (var y = 0; y < 8; y++) {
      for (var x = 0; x < 12; x++) {
        source.setPixelRgb(x, y, x * 20, y * 30, 60);
      }
    }
    final bytes = img.encodePng(source),
        mirrored = img.decodePng(mirrorCameraPhoto(bytes))!;
    expect((mirrored.width, mirrored.height), (12, 8));
    for (var x = 0; x < 12; x++) {
      expect(mirrored.getPixel(x, 3).r, source.getPixel(11 - x, 3).r);
    }
    expect(
      img
          .decodePng(mirrorCameraPhoto(mirrorCameraPhoto(bytes)))!
          .getPixel(2, 4)
          .r,
      source.getPixel(2, 4).r,
    );
    expect(img.decodePng(bytes)!.getPixel(0, 0).r, 0);
  });
}
