import 'dart:math' as math;
import 'dart:typed_data';
import 'package:image/image.dart' as img;
import 'image_processing.dart' show decodePhoto;

typedef CropPoint = (double, double);
typedef SelectionCropJob = ({
  Uint8List bytes,
  int rotation,
  String shape,
  List<CropPoint> points,
  double angle,
});

List<CropPoint> selectionOutline(List<CropPoint> points, String shape) {
  if (shape == 'freehand') return List.of(points);
  if (points.length < 2) return [];
  final l = math.min(points.first.$1, points.last.$1),
      r = math.max(points.first.$1, points.last.$1);
  final t = math.min(points.first.$2, points.last.$2),
      b = math.max(points.first.$2, points.last.$2);
  if (shape == 'ellipse') {
    return List.generate(
      96,
      (i) => (
        (l + r) / 2 + (r - l) / 2 * math.cos(i * math.pi * 2 / 96),
        (t + b) / 2 + (b - t) / 2 * math.sin(i * math.pi * 2 / 96),
      ),
    );
  }
  return [(l, t), (r, t), (r, b), (l, b)];
}

List<CropPoint> rotateOutline(List<CropPoint> points, double angle) {
  if (points.isEmpty) return [];
  final cx =
      (points.map((p) => p.$1).reduce(math.min) +
          points.map((p) => p.$1).reduce(math.max)) /
      2;
  final cy =
      (points.map((p) => p.$2).reduce(math.min) +
          points.map((p) => p.$2).reduce(math.max)) /
      2;
  final c = math.cos(angle * math.pi / 180),
      s = math.sin(angle * math.pi / 180);
  return points
      .map(
        (p) => (
          cx + c * (p.$1 - cx) - s * (p.$2 - cy),
          cy + s * (p.$1 - cx) + c * (p.$2 - cy),
        ),
      )
      .toList();
}

Uint8List cropSelection(SelectionCropJob job) {
  if (!['rectangle', 'ellipse', 'freehand'].contains(job.shape) ||
      !job.angle.isFinite ||
      job.angle.abs() > 180 ||
      job.points.length > 4096 ||
      job.points.any((p) => !p.$1.isFinite || !p.$2.isFinite)) {
    throw const FormatException('Vùng crop không hợp lệ.');
  }
  var image = decodePhoto(job.bytes);
  if (job.rotation % 4 != 0) {
    image = img.copyRotate(image, angle: (job.rotation % 4) * 90);
  }
  final points = selectionOutline(job.points, job.shape);
  if (points.length < 3) {
    throw const FormatException('Vẽ một vùng kín trước khi crop.');
  }
  final minX = points.map((p) => p.$1).reduce(math.min),
      maxX = points.map((p) => p.$1).reduce(math.max);
  final minY = points.map((p) => p.$2).reduce(math.min),
      maxY = points.map((p) => p.$2).reduce(math.max);
  final l = minX.floor(),
      t = minY.floor(),
      w = maxX.ceil() - l,
      h = maxY.ceil() - t;
  var area = 0.0;
  for (var i = 0; i < points.length; i++) {
    final a = points[i], b = points[(i + 1) % points.length];
    area += a.$1 * b.$2 - b.$1 * a.$2;
  }
  if (area.abs() < 4 ||
      w < 2 ||
      h < 2 ||
      w * h > 12000000 ||
      minX < 0 ||
      minY < 0 ||
      maxX > image.width ||
      maxY > image.height) {
    throw const FormatException('Vùng crop rỗng, ngoài ảnh hoặc vượt 12 MP.');
  }
  final mask = img.Image(width: w * 2, height: h * 2, numChannels: 1);
  img.fillPolygon(
    mask,
    vertices: points
        .map((p) => img.Point((p.$1 - l) * 2, (p.$2 - t) * 2))
        .toList(),
    color: img.ColorRgb8(255, 255, 255),
  );
  final out = img.Image(width: w, height: h)
    ..clear(img.ColorRgb8(255, 255, 255));
  final c = math.cos(job.angle * math.pi / 180),
      s = math.sin(job.angle * math.pi / 180),
      cx = (minX + maxX) / 2,
      cy = (minY + maxY) / 2;
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      final alpha =
          (mask.getPixel(x * 2, y * 2).r +
              mask.getPixel(x * 2 + 1, y * 2).r +
              mask.getPixel(x * 2, y * 2 + 1).r +
              mask.getPixel(x * 2 + 1, y * 2 + 1).r) /
          (255 * 4);
      if (alpha == 0) continue;
      final sx = cx + c * (l + x - cx) - s * (t + y - cy),
          sy = cy + s * (l + x - cx) + c * (t + y - cy);
      if (sx < 0 || sy < 0 || sx > image.width - 1 || sy > image.height - 1) {
        continue;
      }
      final color = image.getPixelInterpolate(sx, sy);
      final opacity = alpha * color.aNormalized;
      out.setPixelRgb(
        x,
        y,
        (color.r * opacity + 255 * (1 - opacity)).round(),
        (color.g * opacity + 255 * (1 - opacity)).round(),
        (color.b * opacity + 255 * (1 - opacity)).round(),
      );
    }
  }
  return Uint8List.fromList(img.encodePng(out, level: 3));
}
