import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vietocr_mobile/ocr/shape_crop.dart';
import 'package:vietocr_mobile/ocr/image_processing.dart';

void main() {
  test('black white bakes transparent background to opaque white', () {
    final image = img.Image(width: 20, height: 20, numChannels: 4)
      ..clear(img.ColorRgba8(0, 0, 0, 0));
    final output = img.decodePng(
      blackWhitePhoto(Uint8List.fromList(img.encodePng(image))),
    )!;
    expect(output.getPixel(0, 0).a, 255);
    expect(output.getPixel(0, 0).r, 255);
  });
  late Uint8List bytes;
  setUp(() {
    final image = img.Image(width: 100, height: 80);
    for (final p in image) {
      p.setRgb(p.x * 2, p.y * 3, 30);
    }
    bytes = Uint8List.fromList(img.encodePng(image));
  });
  test('native rectangle and rotated region map back to source pixels', () {
    Uint8List crop(double angle) => cropSelection((
      bytes: bytes,
      rotation: 0,
      shape: 'rectangle',
      points: [(20.0, 20.0), (60.0, 40.0)],
      angle: angle,
    ));
    final normal = img.decodePng(crop(0))!, rotated = img.decodePng(crop(90))!;
    expect((normal.width, normal.height), (40, 20));
    expect(normal.getPixel(10, 10).r, 60);
    expect(normal.getPixel(10, 10).g, 90);
    expect(rotated.getPixel(1, 1).r, closeTo(98, 1));
    expect(rotated.getPixel(1, 1).g, closeTo(33, 1));
    expect(rotateOutline([(20.0, 20.0), (60.0, 40.0)], 90).first, (50.0, 10.0));
  });
  test(
    'ellipse and concave freehand mask outside to white and preserve original',
    () {
      final original = Uint8List.fromList(bytes);
      final ellipse = img.decodePng(
        cropSelection((
          bytes: bytes,
          rotation: 0,
          shape: 'ellipse',
          points: [(10.0, 10.0), (90.0, 70.0)],
          angle: 0,
        )),
      )!;
      expect(ellipse.getPixel(0, 0).r, 255);
      expect(ellipse.getPixel(40, 30).r, 100);
      final free = img.decodePng(
        cropSelection((
          bytes: bytes,
          rotation: 0,
          shape: 'freehand',
          points: [
            (10.0, 10.0),
            (80.0, 10.0),
            (80.0, 30.0),
            (30.0, 30.0),
            (30.0, 70.0),
            (10.0, 70.0),
          ],
          angle: 0,
        )),
      )!;
      expect(free.getPixel(50, 40).r, 255);
      expect(free.getPixel(10, 40).r, 40);
      expect(bytes, original);
    },
  );
  test('invalid/empty regions are rejected before creating output', () {
    expect(
      () => cropSelection((
        bytes: bytes,
        rotation: 0,
        shape: 'freehand',
        points: [(0.0, 0.0), (10.0, 10.0), (20.0, 20.0)],
        angle: 0,
      )),
      throwsFormatException,
    );
    expect(
      () => cropSelection((
        bytes: bytes,
        rotation: 0,
        shape: 'rectangle',
        points: [(0.0, 0.0), (20.0, 20.0)],
        angle: double.nan,
      )),
      throwsFormatException,
    );
  });
  test(
    'black white preserves native dimensions and red ink under uneven light',
    () {
      final image = img.Image(width: 180, height: 80)
        ..clear(img.ColorRgb8(170, 170, 170));
      img.drawLine(
        image,
        x1: 20,
        y1: 40,
        x2: 160,
        y2: 40,
        thickness: 3,
        color: img.ColorRgb8(128, 16, 16),
      );
      final source = Uint8List.fromList(img.encodePng(image));
      final bw = img.decodePng(blackWhitePhoto(source))!;
      expect((bw.width, bw.height), (180, 80));
      expect(bw.getPixel(60, 40).r, 0);
      expect(bw.getPixel(60, 10).r, 255);
      final rotated = img.decodePng(blackWhitePhoto(source, rotation: 1))!;
      expect((rotated.width, rotated.height), (80, 180));
    },
  );
}
