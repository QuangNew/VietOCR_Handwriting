import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:io';
import 'package:image/image.dart' as img;

const maxPhotoPixels = 40000000;

List<LineTensor> prepareDocument((String, bool, int) request) {
  final (path, split, rotation) = request;
  final file = File(path);
  if (file.lengthSync() > 40 * 1024 * 1024) {
    throw const FormatException('Ảnh vượt 40 MB.');
  }
  final lines = prepareLines((file.readAsBytesSync(), split, rotation));
  final tensors = <LineTensor>[];
  for (var i = 0; i < lines.length; i++) {
    tensors.add(makeTensor(lines[i]));
    // Release crop pixels as we go instead of retaining all lines plus tensors.
    lines[i] = GrayImage(1, 1, Uint8List(1));
  }
  return tensors;
}

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

Uint8List normalizePhoto(Uint8List bytes) {
  var image = decodePhoto(bytes);
  if (math.max(image.width, image.height) > 2200) {
    final scale = 2200 / math.max(image.width, image.height);
    image = img.copyResize(
      image,
      width: (image.width * scale).round(),
      height: (image.height * scale).round(),
      interpolation: img.Interpolation.average,
    );
  }
  return Uint8List.fromList(img.encodePng(image, level: 3));
}

class GrayImage {
  const GrayImage(this.width, this.height, this.pixels);
  final int width, height;
  final Uint8List pixels;

  GrayImage crop(int left, int top, int right, int bottom) {
    final result = Uint8List((right - left) * (bottom - top));
    for (var y = top; y < bottom; y++) {
      result.setRange(
        (y - top) * (right - left),
        (y - top + 1) * (right - left),
        pixels,
        y * width + left,
      );
    }
    return GrayImage(right - left, bottom - top, result);
  }
}

class LineTensor {
  const LineTensor(this.width, this.values);
  final int width;
  final Float32List values;
}

List<GrayImage> prepareLines((Uint8List, bool, int) request) {
  final (bytes, split, quarterTurns) = request;
  var image = decodePhoto(bytes);
  if (quarterTurns % 4 != 0) {
    image = img.copyRotate(image, angle: (quarterTurns % 4) * 90);
  }
  if (math.max(image.width, image.height) > 3200) {
    final scale = 3200 / math.max(image.width, image.height);
    image = img.copyResize(
      image,
      width: math.max(1, (image.width * scale).round()),
      height: math.max(1, (image.height * scale).round()),
      interpolation: img.Interpolation.average,
    );
  }
  final pixels = Uint8List(image.width * image.height);
  for (final pixel in image) {
    final alpha = pixel.aNormalized;
    final value =
        (pixel.r * .299 + pixel.g * .587 + pixel.b * .114) * alpha +
        255 * (1 - alpha);
    pixels[pixel.y * image.width + pixel.x] = value.round().clamp(0, 255);
  }
  var gray = GrayImage(image.width, image.height, pixels);
  gray = deskew(gray);
  var sum = 0.0, squares = 0.0;
  for (final value in gray.pixels) {
    sum += value;
    squares += value * value;
  }
  final mean = sum / gray.pixels.length;
  if (math.sqrt(math.max(0, squares / gray.pixels.length - mean * mean)) < 30) {
    gray = clahe(gray);
  }
  final lines = split ? splitLines(gray) : [gray];
  if (lines.isEmpty) {
    throw const FormatException(
      'Không thấy dòng chữ. Chụp rõ hơn hoặc thử chế độ Một dòng.',
    );
  }
  if (lines.length > 150) {
    throw const FormatException(
      'Ảnh có quá nhiều dòng. Hãy chia tài liệu thành các ảnh nhỏ hơn.',
    );
  }
  return lines;
}

int otsu(Uint8List pixels) {
  final histogram = List<int>.filled(256, 0);
  var total = 0.0;
  for (final value in pixels) {
    histogram[value]++;
    total += value;
  }
  var count = 0, sum = 0.0, best = -1.0, threshold = 0;
  for (var value = 0; value < 256; value++) {
    count += histogram[value];
    if (count == 0) continue;
    if (count == pixels.length) break;
    sum += value * histogram[value];
    final difference = sum / count - (total - sum) / (pixels.length - count);
    final score = count * (pixels.length - count) * difference * difference;
    if (score > best) {
      best = score;
      threshold = value;
    }
  }
  return threshold;
}

GrayImage deskew(GrayImage source) {
  final scale = math.min(
    1.0,
    math.min(600 / source.width, 400 / source.height),
  );
  final width = math.max(1, (source.width * scale).round());
  final height = math.max(1, (source.height * scale).round());
  final small = Uint8List(width * height);
  for (var y = 0; y < height; y++) {
    for (var x = 0; x < width; x++) {
      small[y * width + x] =
          source.pixels[math.min(source.height - 1, (y / scale).floor()) *
                  source.width +
              math.min(source.width - 1, (x / scale).floor())];
    }
  }
  final threshold = otsu(small), cx = width ~/ 2, cy = height ~/ 2;
  var bestScore = -1.0, bestAngle = 0.0;
  for (var step = -30; step < 30; step++) {
    final angle = step * .5, radians = angle * math.pi / 180;
    final cosine = math.cos(radians), sine = math.sin(radians);
    var previous = 0, score = 0.0;
    for (var y = 0; y < height; y++) {
      var count = 0;
      for (var x = 0; x < width; x++) {
        final sx = (cosine * (x - cx) - sine * (y - cy) + cx).round();
        final sy = (sine * (x - cx) + cosine * (y - cy) + cy).round();
        if (sx >= 0 &&
            sx < width &&
            sy >= 0 &&
            sy < height &&
            small[sy * width + sx] <= threshold) {
          count++;
        }
      }
      if (y > 0) score += (count - previous) * (count - previous);
      previous = count;
    }
    if (score > bestScore ||
        (score == bestScore && angle.abs() < bestAngle.abs())) {
      bestScore = score;
      bestAngle = angle;
    }
  }
  if (bestAngle.abs() < .5) return source;
  final result = Uint8List(source.pixels.length);
  final cosine = math.cos(bestAngle * math.pi / 180),
      sine = math.sin(bestAngle * math.pi / 180);
  final centerX = source.width ~/ 2, centerY = source.height ~/ 2;
  // Bilinear sampling with a white border preserves the original canvas size.
  for (var y = 0; y < source.height; y++) {
    for (var x = 0; x < source.width; x++) {
      final sx = cosine * (x - centerX) - sine * (y - centerY) + centerX;
      final sy = sine * (x - centerX) + cosine * (y - centerY) + centerY;
      final x0 = sx.floor(), y0 = sy.floor(), dx = sx - x0, dy = sy - y0;
      double value(int px, int py) =>
          px < 0 || px >= source.width || py < 0 || py >= source.height
          ? 255
          : source.pixels[py * source.width + px].toDouble();
      result[y * source.width + x] =
          (value(x0, y0) * (1 - dx) * (1 - dy) +
                  value(x0 + 1, y0) * dx * (1 - dy) +
                  value(x0, y0 + 1) * (1 - dx) * dy +
                  value(x0 + 1, y0 + 1) * dx * dy)
              .round()
              .clamp(0, 255);
    }
  }
  return GrayImage(source.width, source.height, result);
}

GrayImage clahe(GrayImage source) {
  final tileWidth = (source.width / 8).ceil(),
      tileHeight = (source.height / 8).ceil();
  final maps = <Uint8List>[];
  for (var ty = 0; ty < 8; ty++) {
    for (var tx = 0; tx < 8; tx++) {
      final histogram = List<int>.filled(256, 0);
      for (
        var y = ty * tileHeight;
        y < math.min(source.height, (ty + 1) * tileHeight);
        y++
      ) {
        for (
          var x = tx * tileWidth;
          x < math.min(source.width, (tx + 1) * tileWidth);
          x++
        ) {
          histogram[source.pixels[y * source.width + x]]++;
        }
      }
      final area = math.max(
        1,
        math.min(tileWidth, source.width - tx * tileWidth) *
            math.min(tileHeight, source.height - ty * tileHeight),
      );
      final limit = math.max(1, (2 * area / 256).floor());
      var clipped = 0;
      for (var i = 0; i < 256; i++) {
        if (histogram[i] > limit) {
          clipped += histogram[i] - limit;
          histogram[i] = limit;
        }
      }
      final each = clipped ~/ 256, remainder = clipped % 256;
      for (var i = 0; i < 256; i++) {
        histogram[i] += each;
      }
      if (remainder > 0) {
        final stride = math.max(1, 256 ~/ remainder);
        for (
          var i = 0, remaining = remainder;
          i < 256 && remaining > 0;
          i += stride, remaining--
        ) {
          histogram[i]++;
        }
      }
      final mapping = Uint8List(256);
      var sum = 0;
      for (var i = 0; i < 256; i++) {
        sum += histogram[i];
        mapping[i] = (sum * 255 / area).round().clamp(0, 255);
      }
      maps.add(mapping);
    }
  }
  final output = Uint8List(source.pixels.length);
  for (var y = 0; y < source.height; y++) {
    final fy = y / tileHeight - .5, rawY = fy.floor(), dy = fy - rawY;
    final y0 = rawY.clamp(0, 7), y1 = (rawY + 1).clamp(0, 7);
    for (var x = 0; x < source.width; x++) {
      final fx = x / tileWidth - .5, rawX = fx.floor(), dx = fx - rawX;
      final x0 = rawX.clamp(0, 7),
          x1 = (rawX + 1).clamp(0, 7),
          value = source.pixels[y * source.width + x];
      output[y * source.width + x] =
          (maps[y0 * 8 + x0][value] * (1 - dx) * (1 - dy) +
                  maps[y0 * 8 + x1][value] * dx * (1 - dy) +
                  maps[y1 * 8 + x0][value] * (1 - dx) * dy +
                  maps[y1 * 8 + x1][value] * dx * dy)
              .round()
              .clamp(0, 255);
    }
  }
  return GrayImage(source.width, source.height, output);
}

List<GrayImage> splitLines(GrayImage source) {
  final threshold = otsu(source.pixels), size = source.pixels.length;
  final visited = Uint8List(size),
      clean = Uint8List(size),
      queue = Int32List(size),
      heights = <int>[];
  for (var start = 0; start < size; start++) {
    if (visited[start] != 0 || source.pixels[start] > threshold) continue;
    var head = 0,
        tail = 1,
        left = source.width,
        right = 0,
        top = source.height,
        bottom = 0;
    queue[0] = start;
    visited[start] = 1;
    while (head < tail) {
      final index = queue[head++],
          x = index % source.width,
          y = index ~/ source.width;
      left = math.min(left, x);
      right = math.max(right, x);
      top = math.min(top, y);
      bottom = math.max(bottom, y);
      for (var dy = -1; dy <= 1; dy++) {
        for (var dx = -1; dx <= 1; dx++) {
          final nx = x + dx, ny = y + dy;
          if (nx < 0 || nx >= source.width || ny < 0 || ny >= source.height) {
            continue;
          }
          final next = ny * source.width + nx;
          if (visited[next] == 0 && source.pixels[next] <= threshold) {
            visited[next] = 1;
            queue[tail++] = next;
          }
        }
      }
    }
    final width = right - left + 1, height = bottom - top + 1;
    if (tail < 3 ||
        height < 2 ||
        (height > source.height * .7 && width < 4) ||
        (width > source.width * .8 && height < 4)) {
      continue;
    }
    for (var i = 0; i < tail; i++) {
      clean[queue[i]] = 1;
    }
    if (height >= 5) heights.add(height);
  }
  heights.sort();
  final typical = heights.isEmpty
      ? 8
      : heights[((heights.length - 1) * .65).round()];
  final gap = math.max(3, (typical * .45).floor()),
      rows = List<bool>.filled(source.height, false);
  for (var y = 0; y < source.height; y++) {
    var count = 0;
    for (var x = 0; x < source.width; x++) {
      count += clean[y * source.width + x];
    }
    rows[y] = count >= math.max(2, (source.width * .0015).floor());
  }
  var last = -1;
  for (var y = 0; y < rows.length; y++) {
    if (!rows[y]) continue;
    if (last >= 0 && y - last <= gap) {
      for (var k = last; k < y; k++) {
        rows[k] = true;
      }
    }
    last = y;
  }
  final spans = <(int, int)>[];
  for (var y = 0; y < rows.length; y++) {
    if (!rows[y]) continue;
    final top = y;
    while (y < rows.length && rows[y]) {
      y++;
    }
    if (y - top >= 3) spans.add((top, y));
  }
  final lines = <GrayImage>[];
  for (var i = 0; i < spans.length; i++) {
    final (top, bottom) = spans[i];
    var left = source.width, right = -1;
    for (var y = top; y < bottom; y++) {
      for (var x = 0; x < source.width; x++) {
        if (clean[y * source.width + x] != 0) {
          left = math.min(left, x);
          right = math.max(right, x);
        }
      }
    }
    if (right < left) continue;
    final pad = math.max(3, ((bottom - top) * .25).floor());
    final lower = i == 0 ? 0 : (spans[i - 1].$2 + top) ~/ 2;
    final upper = i == spans.length - 1
        ? source.height
        : (bottom + spans[i + 1].$1) ~/ 2;
    lines.add(
      source.crop(
        math.max(0, left - pad),
        math.max(lower, top - pad),
        math.min(source.width, right + pad + 1),
        math.min(upper, bottom + pad),
      ),
    );
  }
  return lines;
}

LineTensor makeTensor(GrayImage image) {
  final rawWidth = (32 * image.width / image.height).floor();
  final width = ((rawWidth / 10).ceil() * 10).clamp(32, 1024);
  List<List<(int, double)>> weights(int from, int to) {
    final scale = from / to, filterScale = math.max(1.0, scale);
    return List.generate(to, (output) {
      final center = (output + .5) * scale;
      final values = <(int, double)>[];
      var sum = 0.0;
      for (
        var input = math.max(0, (center - filterScale * 3 - .5).ceil());
        input <= math.min(from - 1, (center + filterScale * 3 - .5).floor());
        input++
      ) {
        final x = (input + .5 - center) / filterScale;
        final weight = x.abs() < 1e-10
            ? 1.0
            : x.abs() >= 3
            ? 0.0
            : 3 *
                  math.sin(math.pi * x) *
                  math.sin(math.pi * x / 3) /
                  (math.pi * math.pi * x * x);
        values.add((input, weight));
        sum += weight;
      }
      return values.map((entry) => (entry.$1, entry.$2 / sum)).toList();
    });
  }

  final xs = weights(image.width, width), ys = weights(image.height, 32);
  final horizontal = Uint8List(width * image.height);
  for (var y = 0; y < image.height; y++) {
    for (var x = 0; x < width; x++) {
      var value = 0.0;
      for (final (input, weight) in xs[x]) {
        value += image.pixels[y * image.width + input] * weight;
      }
      horizontal[y * width + x] = value.round().clamp(0, 255);
    }
  }
  final tensor = Float32List(3 * 32 * width);
  for (var y = 0; y < 32; y++) {
    for (var x = 0; x < width; x++) {
      var value = 0.0;
      for (final (input, weight) in ys[y]) {
        value += horizontal[input * width + x] * weight;
      }
      value = value.round().clamp(0, 255) / 255;
      for (var channel = 0; channel < 3; channel++) {
        tensor[channel * 32 * width + y * width + x] = value;
      }
    }
  }
  return LineTensor(width, tensor);
}
