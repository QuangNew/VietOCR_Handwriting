import 'dart:math' as math;
import 'dart:typed_data';
import 'package:image/image.dart' as img;

const maxPhotoPixels = 40000000;

img.Image decodePhoto(Uint8List bytes) {
  final decoder = img.findDecoderForData(bytes);
  final info = decoder?.startDecode(bytes);
  if (info == null) {
    throw const FormatException('Ảnh không hợp lệ hoặc định dạng chưa hỗ trợ.');
  }
  if (info.width * info.height > maxPhotoPixels) {
    throw const FormatException('Ảnh vượt 40 megapixel. Hãy chọn ảnh nhỏ hơn.');
  }
  final decoded = decoder!.decodeFrame(0);
  if (decoded == null) throw const FormatException('Không đọc được ảnh này.');
  return img.bakeOrientation(decoded);
}

Uint8List normalizeDerivative(Uint8List bytes) {
  final image = decodePhoto(bytes);
  if (image.width * image.height > 12000000) {
    throw const FormatException('Ảnh chỉnh sửa vượt 12 MP.');
  }
  return Uint8List.fromList(img.encodePng(image, level: 3));
}

// Optional local threshold, lossless PNG, original dimensions. Running column
// sums avoid a full-image integral buffer on phones with limited RAM.
Uint8List blackWhitePhoto(Uint8List bytes, {int rotation = 0}) {
  var image = decodePhoto(bytes);
  if (rotation % 4 != 0) {
    image = img.copyRotate(image, angle: (rotation % 4) * 90);
  }
  final w = image.width, h = image.height;
  if (w * h > 12000000) {
    throw const FormatException(
      'Ảnh đen trắng hỗ trợ đến 12 MP. Hãy crop vùng chữ trước.',
    );
  }
  final gray = Uint8List(w * h);
  for (final p in image) {
    gray[p.y * w + p.x] =
        ((p.r * .299 + p.g * .587 + p.b * .114) * p.aNormalized +
                255 * (1 - p.aNormalized))
            .round()
            .clamp(0, 255);
  }
  final sums = Uint32List(w);
  const radius = 15;
  for (var y = 0; y <= math.min(radius, h - 1); y++) {
    for (var x = 0; x < w; x++) {
      sums[x] += gray[y * w + x];
    }
  }
  for (var y = 0; y < h; y++) {
    var sum = 0;
    for (var x = 0; x <= math.min(radius, w - 1); x++) {
      sum += sums[x];
    }
    final rows = math.min(h - 1, y + radius) - math.max(0, y - radius) + 1;
    for (var x = 0; x < w; x++) {
      final columns = math.min(w - 1, x + radius) - math.max(0, x - radius) + 1;
      final v = gray[y * w + x] < sum / (rows * columns) - 8 ? 0 : 255;
      image.setPixelRgba(x, y, v, v, v, 255);
      if (x - radius >= 0) sum -= sums[x - radius];
      if (x + radius + 1 < w) sum += sums[x + radius + 1];
    }
    for (var x = 0; x < w; x++) {
      if (y - radius >= 0) sums[x] -= gray[(y - radius) * w + x];
      if (y + radius + 1 < h) sums[x] += gray[(y + radius + 1) * w + x];
    }
  }
  return Uint8List.fromList(img.encodePng(image, level: 3));
}
