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
  test('blank paper does not produce fabricated lines', () {
    final image = img.Image(width: 100, height: 80)
      ..clear(img.ColorRgb8(255, 255, 255));
    expect(
      splitLines(
        GrayImage(100, 80, Uint8List.fromList(List.filled(8000, 255))),
      ),
      isEmpty,
    );
    expect(
      () => prepareLines((img.encodePng(image), true, 0)),
      throwsFormatException,
    );
  });
  test(
    'line crops retain detached Vietnamese accents without merging adjacent lines',
    () {
      final pixels = Uint8List.fromList(List.filled(200 * 100, 255));
      void rectangle(int left, int top, int width, int height) {
        for (var y = top; y < top + height; y++) {
          for (var x = left; x < left + width; x++) {
            pixels[y * 200 + x] = 0;
          }
        }
      }

      for (final top in [20, 65]) {
        for (var x = 20; x < 170; x += 15) {
          rectangle(x, top, 8, 15);
          rectangle(x + 1, top - 5, 4, 3);
        }
      }
      final lines = splitLines(GrayImage(200, 100, pixels));
      expect(lines, hasLength(2));
      for (final line in lines) {
        expect(line.height, greaterThanOrEqualTo(20));
        expect(line.pixels.where((value) => value == 0).length, 1320);
      }
    },
  );
  test(
    'tensor dimensions follow the original model and repeat RGB channels',
    () {
      for (final (width, height, expected) in [
        (1, 100, 32),
        (100, 32, 200),
        (101, 32, 210),
        (4000, 32, 2048),
      ]) {
        final tensor = makeTensor(
          GrayImage(
            width,
            height,
            Uint8List.fromList(List.filled(width * height, 127)),
          ),
        );
        expect(tensor.width, expected);
        expect(tensor.values.length, 3 * 64 * expected);
        expect(tensor.values.first, closeTo(127 / 255, 1e-7));
        expect(
          tensor.values.sublist(0, 64 * expected),
          tensor.values.sublist(64 * expected, 128 * expected),
        );
      }
    },
  );
  test(
    'transparent pixels are composited on white and rotation changes tensor aspect',
    () {
      final image = img.Image(width: 100, height: 20, numChannels: 4)
        ..clear(img.ColorRgba8(0, 0, 0, 0));
      final lines = prepareLines((img.encodePng(image), false, 1));
      expect(lines.single.width, 20);
      expect(lines.single.height, 100);
      expect(
        lines.single.pixels.reduce((a, b) => a < b ? a : b),
        greaterThan(240),
      );
    },
  );
}
