import 'dart:math' as math;
import 'dart:typed_data';
import 'package:image/image.dart' as img;
import 'image_processing.dart' show decodePhoto;

typedef Point2D = List<double>;

class QuadBounds {
  const QuadBounds({
    required this.minX,
    required this.minY,
    required this.maxX,
    required this.maxY,
  });
  final double minX, minY, maxX, maxY;
  double get width => maxX - minX;
  double get height => maxY - minY;
  double get cx => (minX + maxX) / 2;
  double get cy => (minY + maxY) / 2;
}

class DetectedPaperResult {
  const DetectedPaperResult({
    required this.sourceWidth,
    required this.sourceHeight,
    required this.paperQuad,
  });
  final double sourceWidth;
  final double sourceHeight;
  final List<Point2D> paperQuad;
}

QuadBounds polygonBounds(List<Point2D> poly) {
  var minX = double.infinity;
  var minY = double.infinity;
  var maxX = double.negativeInfinity;
  var maxY = double.negativeInfinity;
  for (final p in poly) {
    if (p[0] < minX) minX = p[0];
    if (p[1] < minY) minY = p[1];
    if (p[0] > maxX) maxX = p[0];
    if (p[1] > maxY) maxY = p[1];
  }
  return QuadBounds(minX: minX, minY: minY, maxX: maxX, maxY: maxY);
}

List<Point2D>? orderQuad(List<Point2D> pts) {
  if (pts.length != 4) return null;
  final arr = pts.map((p) => <double>[p[0], p[1]]).toList();
  var cx = 0.0, cy = 0.0;
  for (final p in arr) {
    cx += p[0];
    cy += p[1];
  }
  cx /= 4;
  cy /= 4;
  arr.sort(
    (a, b) => math
        .atan2(a[1] - cy, a[0] - cx)
        .compareTo(math.atan2(b[1] - cy, b[0] - cx)),
  );
  var tlIdx = 0;
  var minS = double.infinity;
  for (var i = 0; i < 4; i++) {
    final s = arr[i][0] + arr[i][1];
    if (s < minS) {
      minS = s;
      tlIdx = i;
    }
  }
  return [
    arr[tlIdx],
    arr[(tlIdx + 1) % 4],
    arr[(tlIdx + 2) % 4],
    arr[(tlIdx + 3) % 4],
  ];
}

List<Point2D> expandPolygon(
  List<Point2D> poly,
  double pad, {
  double maxW = double.infinity,
  double maxH = double.infinity,
}) {
  if (poly.length < 3) return [];
  var cx = 0.0, cy = 0.0;
  for (final p in poly) {
    cx += p[0];
    cy += p[1];
  }
  cx /= poly.length;
  cy /= poly.length;
  return poly.map((p) {
    final dx = p[0] - cx;
    final dy = p[1] - cy;
    final len = math.sqrt(dx * dx + dy * dy);
    final inv = len > 1e-6 ? 1.0 / len : 1.0;
    final nx = (p[0] + dx * inv * pad).clamp(0.0, maxW);
    final ny = (p[1] + dy * inv * pad).clamp(0.0, maxH);
    return <double>[nx, ny];
  }).toList();
}

bool pointInPolygon(double px, double py, List<Point2D> poly) {
  if (poly.length < 3) return false;
  var inside = false;
  for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    final xi = poly[i][0], yi = poly[i][1];
    final xj = poly[j][0], yj = poly[j][1];
    final denom = (yj - yi) == 0 ? 1e-9 : (yj - yi);
    final intersect =
        ((yi > py) != (yj > py)) && (px < ((xj - xi) * (py - yi)) / denom + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

List<Map<String, dynamic>> linesInsideQuad(
  List<Map<String, dynamic>> lines,
  List<Point2D> quad,
) {
  if (quad.length != 4) return [];
  return lines.where((l) {
    final rawPoly = l['polygon'];
    if (rawPoly is! List || rawPoly.length < 3) return true;
    final poly = rawPoly
        .whereType<List>()
        .where((p) => p.length >= 2)
        .map((p) => <double>[(p[0] as num).toDouble(), (p[1] as num).toDouble()])
        .toList();
    if (poly.length < 3) return true;
    final b = polygonBounds(poly);
    return pointInPolygon(b.cx, b.cy, quad);
  }).toList();
}

/// Tighten handwritten line polygons so tilted/ascender bounding boxes never bleed across neighbor lines.
Map<int, List<Point2D>> tightenLinePolygons(List<Map<String, dynamic>> lines) {
  final out = <int, List<Point2D>>{};
  if (lines.isEmpty) return out;
  final items = <Map<String, dynamic>>[];
  for (var i = 0; i < lines.length; i++) {
    final raw = lines[i]['polygon'];
    if (raw is! List || raw.length < 3) continue;
    final pts = raw
        .whereType<List>()
        .where((p) => p.length >= 2)
        .map<Point2D>((p) => [(p[0] as num).toDouble(), (p[1] as num).toDouble()])
        .toList();
    if (pts.length < 3) continue;
    final b = polygonBounds(pts);
    final poly = pts.length == 4
        ? (orderQuad(pts) ?? pts)
        : <Point2D>[
            [b.minX, b.minY],
            [b.maxX, b.minY],
            [b.maxX, b.maxY],
            [b.minX, b.maxY],
          ];
    final leftMidY = (poly[0][1] + poly[3][1]) * 0.5;
    final rightMidY = (poly[1][1] + poly[2][1]) * 0.5;
    final halfL = math.max(4.0, (poly[3][1] - poly[0][1]).abs() * 0.5);
    final halfR = math.max(4.0, (poly[2][1] - poly[1][1]).abs() * 0.5);
    items.add({
      'id': (lines[i]['id'] as num?)?.toInt() ?? (i + 1),
      'minX': b.minX,
      'maxX': b.maxX,
      'w': math.max(1.0, b.width),
      'cy': (leftMidY + rightMidY) * 0.5,
      'leftX': (poly[0][0] + poly[3][0]) * 0.5,
      'rightX': (poly[1][0] + poly[2][0]) * 0.5,
      'leftMidY': leftMidY,
      'rightMidY': rightMidY,
      'topOffL': (poly[0][1] - leftMidY).abs(),
      'botOffL': (poly[3][1] - leftMidY).abs(),
      'topOffR': (poly[1][1] - rightMidY).abs(),
      'botOffR': (poly[2][1] - rightMidY).abs(),
      'rawHalf': math.max(4.0, (halfL + halfR) * 0.5),
    });
  }
  items.sort((a, b) => (a['cy'] as double).compareTo(b['cy'] as double));

  final pitches = <double>[];
  for (var i = 0; i < items.length; i++) {
    final cur = items[i];
    var up = double.infinity;
    var down = double.infinity;
    for (var j = i - 1; j >= 0; j--) {
      final prev = items[j];
      final ov =
          math.min(cur['maxX'] as double, prev['maxX'] as double) -
          math.max(cur['minX'] as double, prev['minX'] as double);
      if (ov > 0.15 * math.min(cur['w'] as double, prev['w'] as double)) {
        final dy = (cur['cy'] as double) - (prev['cy'] as double);
        if (dy > 4.0) {
          up = dy;
          break;
        }
      }
    }
    for (var j = i + 1; j < items.length; j++) {
      final next = items[j];
      final ov =
          math.min(cur['maxX'] as double, next['maxX'] as double) -
          math.max(cur['minX'] as double, next['minX'] as double);
      if (ov > 0.15 * math.min(cur['w'] as double, next['w'] as double)) {
        final dy = (next['cy'] as double) - (cur['cy'] as double);
        if (dy > 4.0) {
          down = dy;
          break;
        }
      }
    }
    cur['up'] = up;
    cur['down'] = down;
    if (down.isFinite) pitches.add(down);
  }
  pitches.sort();
  final medPitch = pitches.isNotEmpty ? pitches[pitches.length ~/ 2] : null;

  for (final cur in items) {
    final up = cur['up'] as double;
    final down = cur['down'] as double;
    final local = math.min(up, down);
    final refPitch = local.isFinite ? local : medPitch;
    final maxHalf = refPitch != null
        ? math.max(6.0, refPitch * 0.37)
        : (cur['rawHalf'] as double) * 0.85;
    final capTop = math.min(
      maxHalf,
      up.isFinite ? math.max(5.0, up * 0.43) : maxHalf,
    );
    final capBot = math.min(
      maxHalf,
      down.isFinite ? math.max(5.0, down * 0.43) : maxHalf,
    );
    final lx = cur['leftX'] as double;
    final rx = cur['rightX'] as double;
    final lmy = cur['leftMidY'] as double;
    final rmy = cur['rightMidY'] as double;
    out[cur['id'] as int] = [
      [lx, lmy - math.min(cur['topOffL'] as double, capTop)],
      [rx, rmy - math.min(cur['topOffR'] as double, capTop)],
      [rx, rmy + math.min(cur['botOffR'] as double, capBot)],
      [lx, lmy + math.min(cur['botOffL'] as double, capBot)],
    ];
  }
  return out;
}

double _cross2d(Point2D o, Point2D a, Point2D b) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

List<Point2D> convexHull(List<Point2D> points) {
  if (points.length < 3) return points;
  final pts = List<Point2D>.from(points)
    ..sort((a, b) {
      final dx = a[0].compareTo(b[0]);
      return dx != 0 ? dx : a[1].compareTo(b[1]);
    });
  final lower = <Point2D>[];
  for (final p in pts) {
    while (lower.length >= 2 &&
        _cross2d(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.removeLast();
    }
    lower.add(p);
  }
  final upper = <Point2D>[];
  for (var i = pts.length - 1; i >= 0; i--) {
    final p = pts[i];
    while (upper.length >= 2 &&
        _cross2d(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.removeLast();
    }
    upper.add(p);
  }
  lower.removeLast();
  upper.removeLast();
  return [...lower, ...upper];
}

double _polygonArea(List<Point2D> poly) {
  var area = 0.0;
  for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    area += poly[j][0] * poly[i][1] - poly[i][0] * poly[j][1];
  }
  return area.abs() / 2;
}

List<Point2D>? _minAreaRectFromHull(List<Point2D> hull) {
  if (hull.length < 3) return null;
  var bestArea = double.infinity;
  List<Point2D>? bestQuad;
  for (var i = 0; i < hull.length; i++) {
    final a = hull[i];
    final b = hull[(i + 1) % hull.length];
    final dx = b[0] - a[0];
    final dy = b[1] - a[1];
    final len = math.sqrt(dx * dx + dy * dy);
    if (len < 1e-6) continue;
    final ux = dx / len, uy = dy / len;
    final vx = -uy, vy = ux;
    var minU = double.infinity, maxU = double.negativeInfinity;
    var minV = double.infinity, maxV = double.negativeInfinity;
    for (final p in hull) {
      final u = p[0] * ux + p[1] * uy;
      final v = p[0] * vx + p[1] * vy;
      if (u < minU) minU = u;
      if (u > maxU) maxU = u;
      if (v < minV) minV = v;
      if (v > maxV) maxV = v;
    }
    final area = (maxU - minU) * (maxV - minV);
    if (area < bestArea) {
      bestArea = area;
      bestQuad = [
        [minU * ux + minV * vx, minU * uy + minV * vy],
        [maxU * ux + minV * vx, maxU * uy + minV * vy],
        [maxU * ux + maxV * vx, maxU * uy + maxV * vy],
        [minU * ux + maxV * vx, minU * uy + maxV * vy],
      ];
    }
  }
  return bestQuad != null ? orderQuad(bestQuad) : null;
}

List<Point2D>? _simplifyClosedPolygonToQuad(List<Point2D> hull) {
  if (hull.length < 4) return null;
  if (hull.length == 4) return orderQuad(hull);
  final hullArea = math.max(1.0, _polygonArea(hull));
  final pts = List<Point2D>.from(hull);
  while (pts.length > 4) {
    var minDrop = double.infinity;
    var dropIdx = 0;
    final n = pts.length;
    for (var i = 0; i < n; i++) {
      final prev = pts[(i + n - 1) % n];
      final curr = pts[i];
      final next = pts[(i + 1) % n];
      final tri = _cross2d(prev, curr, next).abs() / 2;
      if (tri < minDrop) {
        minDrop = tri;
        dropIdx = i;
      }
    }
    pts.removeAt(dropIdx);
  }
  if (_polygonArea(pts) / hullArea >= 0.86) return orderQuad(pts);
  return null;
}

Uint8List _morphOp(Uint8List mask, int w, int h, int radius, bool dilate) {
  final tmp = Uint8List(w * h);
  final out = Uint8List(w * h);
  for (var y = 0; y < h; y++) {
    final row = y * w;
    for (var x = 0; x < w; x++) {
      var val = dilate ? 0 : 1;
      final x0 = math.max(0, x - radius);
      final x1 = math.min(w - 1, x + radius);
      for (var xx = x0; xx <= x1; xx++) {
        final m = mask[row + xx] != 0;
        if (dilate ? m : !m) {
          val = dilate ? 1 : 0;
          break;
        }
      }
      tmp[row + x] = val;
    }
  }
  for (var y = 0; y < h; y++) {
    final y0 = math.max(0, y - radius);
    final y1 = math.min(h - 1, y + radius);
    for (var x = 0; x < w; x++) {
      var val = dilate ? 0 : 1;
      for (var yy = y0; yy <= y1; yy++) {
        final m = tmp[yy * w + x] != 0;
        if (dilate ? m : !m) {
          val = dilate ? 1 : 0;
          break;
        }
      }
      out[y * w + x] = val;
    }
  }
  return out;
}

/// Pure RGBA paper sheet detector (mirrors desktop lens.mjs).
/// Stage 1: Cool-achromatic seed discovers the sheet's own white-point.
/// Stage 2: Relative normalized chromaticity + brightness cleanly separates paper from wood glare.
/// Stage 3: Morphological closing/opening + convex hull 4-corner quad fit + +1.2% safety pad.
DetectedPaperResult? detectPaperQuadFromRgba(
  Uint8List rgba,
  int w,
  int h, {
  double? natW,
  double? natH,
}) {
  final n = w * h;
  if (w < 16 || h < 16 || rgba.length < n * 4) return null;
  final outW = natW ?? w.toDouble();
  final outH = natH ?? h.toDouble();

  final scores = Uint8List(n);
  final hist = Uint32List(256);
  for (var i = 0; i < n; i++) {
    final r = rgba[i * 4];
    final g = rgba[i * 4 + 1];
    final b = rgba[i * 4 + 2];
    final maxC = math.max(r, math.max(g, b));
    final minC = math.min(r, math.min(g, b));
    final chroma = maxC - minC;
    final warmth = (r > b ? (r - b) * 1.65 : 0.0) + (g > b ? (g - b) * 0.45 : 0.0);
    final coolLuma = 0.52 * b + 0.32 * g + 0.16 * r;
    final s = (coolLuma - warmth - chroma * 0.45).round().clamp(0, 255);
    scores[i] = s;
    hist[s]++;
  }

  var sumAll = 0.0;
  for (var t = 0; t < 256; t++) {
    sumAll += t * hist[t];
  }
  var sumB = 0.0;
  var wB = 0;
  var maxVar = -1.0;
  var bestT = 110;
  for (var t = 0; t < 256; t++) {
    wB += hist[t];
    if (wB == 0) continue;
    final wF = n - wB;
    if (wF == 0) break;
    sumB += t * hist[t];
    final mB = sumB / wB;
    final mF = (sumAll - sumB) / wF;
    final between = wB.toDouble() * wF.toDouble() * (mB - mF) * (mB - mF);
    if (between > maxVar) {
      maxVar = between;
      bestT = t;
    }
  }

  final baseT = math.max(78, bestT);
  var fgTotal = 0;
  for (var t = baseT; t < 256; t++) {
    fgTotal += hist[t];
  }
  if (fgTotal / n < 0.06 || fgTotal / n > 0.94) return null;

  var acc = 0;
  var p60Fg = baseT;
  for (var t = baseT; t < 256; t++) {
    acc += hist[t];
    if (acc >= fgTotal * 0.60) {
      p60Fg = t;
      break;
    }
  }
  final seedT = math.max(baseT, p60Fg);

  final bx0 = (w * 0.05).floor(), bx1 = (w * 0.95).ceil();
  final by0 = (h * 0.05).floor(), by1 = (h * 0.95).ceil();
  final rHist = Uint32List(256);
  final gHist = Uint32List(256);
  final bHist = Uint32List(256);
  var seedCount = 0;
  for (var y = by0; y < by1; y++) {
    final row = y * w;
    for (var x = bx0; x < bx1; x++) {
      final idx = row + x;
      if (scores[idx] >= seedT) {
        rHist[rgba[idx * 4]]++;
        gHist[rgba[idx * 4 + 1]]++;
        bHist[rgba[idx * 4 + 2]]++;
        seedCount++;
      }
    }
  }
  if (seedCount < n * 0.02) {
    for (var idx = 0; idx < n; idx++) {
      if (scores[idx] >= seedT) {
        rHist[rgba[idx * 4]]++;
        gHist[rgba[idx * 4 + 1]]++;
        bHist[rgba[idx * 4 + 2]]++;
        seedCount++;
      }
    }
  }
  if (seedCount < 16) return null;

  int medianOf(Uint32List hArr) {
    var s = 0;
    final half = seedCount * 0.5;
    for (var v = 0; v < 256; v++) {
      s += hArr[v];
      if (s >= half) return v;
    }
    return 200;
  }

  final coreR = medianOf(rHist).toDouble();
  final coreG = medianOf(gHist).toDouble();
  final coreB = medianOf(bHist).toDouble();
  final coreSum = math.max(1.0, coreR + coreG + coreB);
  final crn = coreR / coreSum;
  final cgn = coreG / coreSum;
  final cbn = coreB / coreSum;
  final coreLuma = 0.299 * coreR + 0.587 * coreG + 0.114 * coreB;
  final minLuma = math.max(68.0, coreLuma * 0.62);

  final rawMask = Uint8List(n);
  var paperPix = 0;
  for (var i = 0; i < n; i++) {
    final r = rgba[i * 4].toDouble();
    final g = rgba[i * 4 + 1].toDouble();
    final b = rgba[i * 4 + 2].toDouble();
    final luma = 0.299 * r + 0.587 * g + 0.114 * b;
    if (luma < minLuma) continue;
    final sum = r + g + b;
    if (sum < 60) continue;
    final rn = r / sum;
    final gn = g / sum;
    final bn = b / sum;
    final chromaL1 = (rn - crn).abs() + (gn - cgn).abs() + (bn - cbn).abs();
    if (chromaL1 <= 0.050 && (rn - crn) <= 0.026 && (cbn - bn) <= 0.028) {
      rawMask[i] = 1;
      paperPix++;
    }
  }

  final paperFrac = paperPix / n;
  if (paperFrac < 0.05 || paperFrac > 0.94) return null;

  var clean = _morphOp(rawMask, w, h, 3, true);
  clean = _morphOp(clean, w, h, 3, false);
  clean = _morphOp(clean, w, h, 2, false);
  clean = _morphOp(clean, w, h, 2, true);

  final visited = Uint8List(n);
  final queue = Int32List(n);
  Int32List? bestPixels;
  var bestScore = 0.0;
  var bestCount = 0;
  final cxImg = w / 2.0, cyImg = h / 2.0;
  final maxDist = math.max(1.0, math.sqrt(cxImg * cxImg + cyImg * cyImg));

  for (var i = 0; i < n; i++) {
    if (clean[i] == 0 || visited[i] != 0) continue;
    var head = 0, tail = 0;
    var sumX = 0.0, sumY = 0.0;
    queue[tail++] = i;
    visited[i] = 1;
    while (head < tail) {
      final idx = queue[head++];
      final x = idx % w;
      final y = idx ~/ w;
      sumX += x;
      sumY += y;
      if (x > 0 && clean[idx - 1] != 0 && visited[idx - 1] == 0) {
        visited[idx - 1] = 1;
        queue[tail++] = idx - 1;
      }
      if (x + 1 < w && clean[idx + 1] != 0 && visited[idx + 1] == 0) {
        visited[idx + 1] = 1;
        queue[tail++] = idx + 1;
      }
      if (y > 0 && clean[idx - w] != 0 && visited[idx - w] == 0) {
        visited[idx - w] = 1;
        queue[tail++] = idx - w;
      }
      if (y + 1 < h && clean[idx + w] != 0 && visited[idx + w] == 0) {
        visited[idx + w] = 1;
        queue[tail++] = idx + w;
      }
    }
    if (tail < n * 0.05) continue;
    final dx = sumX / tail - cxImg;
    final dy = sumY / tail - cyImg;
    final dNorm = math.sqrt(dx * dx + dy * dy) / maxDist;
    final compScore = tail * (1.28 - 0.50 * dNorm);
    if (compScore > bestScore) {
      bestScore = compScore;
      bestCount = tail;
      bestPixels = Int32List.fromList(queue.sublist(0, tail));
    }
  }

  if (bestPixels == null || bestCount < n * 0.06 || bestCount > n * 0.94) {
    return null;
  }

  final inBest = Uint8List(n);
  for (final idx in bestPixels) {
    inBest[idx] = 1;
  }
  final boundary = <Point2D>[];
  for (final idx in bestPixels) {
    final x = idx % w;
    final y = idx ~/ w;
    if (x == 0 ||
        y == 0 ||
        x == w - 1 ||
        y == h - 1 ||
        inBest[idx - 1] == 0 ||
        inBest[idx + 1] == 0 ||
        inBest[idx - w] == 0 ||
        inBest[idx + w] == 0) {
      boundary.add([x + 0.5, y + 0.5]);
    }
  }
  final hull = convexHull(boundary);
  final approxQuad = _simplifyClosedPolygonToQuad(hull);
  final minRect = _minAreaRectFromHull(hull);
  var chosen = approxQuad ?? minRect;
  if (approxQuad != null && minRect != null) {
    final hullA = math.max(1.0, _polygonArea(hull));
    final qA = _polygonArea(approxQuad);
    final rA = _polygonArea(minRect);
    chosen = (rA - hullA).abs() <= (qA - hullA).abs() * 1.15
        ? minRect
        : approxQuad;
  }
  if (chosen == null) return null;

  final sx = outW / w;
  final sy = outH / h;
  final scaled = chosen
      .map((p) => <double>[(p[0] * sx).clamp(0.0, outW), (p[1] * sy).clamp(0.0, outH)])
      .toList();
  final b = polygonBounds(scaled);
  final pad = math.min(
    math.min(outW, outH) * 0.012,
    math.min(b.width, b.height) * 0.03,
  );
  final padded = orderQuad(expandPolygon(scaled, pad, maxW: outW, maxH: outH));
  if (padded == null) return null;

  return DetectedPaperResult(
    sourceWidth: outW,
    sourceHeight: outH,
    paperQuad: padded
        .map((p) => <double>[(p[0] * 10).round() / 10, (p[1] * 10).round() / 10])
        .toList(),
  );
}

/// Isolate entrypoint: decode, orient, downsample to <= 240px, and detect paper quad.
DetectedPaperResult? detectPaperQuadFromFileBytes((Uint8List, int) job) {
  final (bytes, rotation) = job;
  var decoded = decodePhoto(bytes);
  if (rotation % 4 != 0) {
    decoded = img.copyRotate(decoded, angle: (rotation % 4) * 90);
  }
  final natW = decoded.width.toDouble();
  final natH = decoded.height.toDouble();
  const maxSide = 240;
  final scale = math.min(1.0, maxSide / math.max(natW, natH));
  final w = math.max(16, (natW * scale).round());
  final h = math.max(16, (natH * scale).round());
  final small = (w == decoded.width && h == decoded.height)
      ? decoded
      : img.copyResize(decoded, width: w, height: h);
  final rgba = Uint8List(w * h * 4);
  var p = 0;
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      final px = small.getPixel(x, y);
      rgba[p++] = px.r.toInt();
      rgba[p++] = px.g.toInt();
      rgba[p++] = px.b.toInt();
      rgba[p++] = 255;
    }
  }
  return detectPaperQuadFromRgba(rgba, w, h, natW: natW, natH: natH);
}

/// Compute natural 90-degree flat landscape or portrait dimensions for a 4-point quad.
({int width, int height}) computeQuadFlatSize(
  List<Point2D>? quad,
  double fallbackW,
  double fallbackH,
) {
  if (quad == null || quad.length != 4) {
    return (
      width: math.max(64, fallbackW.round()),
      height: math.max(64, fallbackH.round()),
    );
  }
  final q = orderQuad(quad) ?? quad;
  double dist(Point2D a, Point2D b) =>
      math.sqrt((b[0] - a[0]) * (b[0] - a[0]) + (b[1] - a[1]) * (b[1] - a[1]));
  final w = ((dist(q[0], q[1]) + dist(q[3], q[2])) / 2).round();
  final h = ((dist(q[0], q[3]) + dist(q[1], q[2])) / 2).round();
  return (width: math.max(64, w), height: math.max(64, h));
}

/// Solve exact 3x3 projective homography H mapping 4 source points -> 4 destination points.
List<double> computeHomography(List<Point2D> srcQuad, List<Point2D> dstQuad) {
  if (srcQuad.length != 4 || dstQuad.length != 4) {
    return [1, 0, 0, 0, 1, 0, 0, 0, 1];
  }
  final a = List.generate(8, (_) => List<double>.filled(8, 0));
  final b = List<double>.filled(8, 0);
  for (var i = 0; i < 4; i++) {
    final x = srcQuad[i][0], y = srcQuad[i][1];
    final u = dstQuad[i][0], v = dstQuad[i][1];
    final r0 = i * 2, r1 = r0 + 1;
    a[r0] = [x, y, 1, 0, 0, 0, -u * x, -u * y];
    b[r0] = u;
    a[r1] = [0, 0, 0, x, y, 1, -v * x, -v * y];
    b[r1] = v;
  }
  const n = 8;
  for (var col = 0; col < n; col++) {
    var pivot = col;
    var maxVal = a[col][col].abs();
    for (var row = col + 1; row < n; row++) {
      final v = a[row][col].abs();
      if (v > maxVal) {
        maxVal = v;
        pivot = row;
      }
    }
    if (maxVal < 1e-10) return [1, 0, 0, 0, 1, 0, 0, 0, 1];
    if (pivot != col) {
      final tmpA = a[col];
      a[col] = a[pivot];
      a[pivot] = tmpA;
      final tmpB = b[col];
      b[col] = b[pivot];
      b[pivot] = tmpB;
    }
    final diag = a[col][col];
    for (var j = col; j < n; j++) {
      a[col][j] /= diag;
    }
    b[col] /= diag;
    for (var row = 0; row < n; row++) {
      if (row == col) continue;
      final factor = a[row][col];
      if (factor.abs() < 1e-12) continue;
      for (var j = col; j < n; j++) {
        a[row][j] -= factor * a[col][j];
      }
      b[row] -= factor * b[col];
    }
  }
  return [b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], 1];
}

Point2D projectPoint(List<double> h, Point2D pt) {
  final x = pt[0], y = pt[1];
  final w = h[6] * x + h[7] * y + h[8];
  if (w.abs() < 1e-9) return [x, y];
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}

/// Isolate entrypoint: perspective-warp photo bytes to a pure flat 90-degree JPEG/PNG sheet.
Uint8List warpPhotoToFlat90Bytes(
  ({Uint8List bytes, int rotation, List<Point2D> quad, int maxSide, bool png}) job,
) {
  var image = decodePhoto(job.bytes);
  if (job.rotation % 4 != 0) {
    image = img.copyRotate(image, angle: (job.rotation % 4) * 90);
  }
  final ordered = orderQuad(job.quad) ?? job.quad;
  final flat = computeQuadFlatSize(
    ordered,
    image.width.toDouble(),
    image.height.toDouble(),
  );
  final scaleOut = math.min(1.0, job.maxSide / math.max(flat.width, flat.height));
  final outW = math.max(64, (flat.width * scaleOut).round());
  final outH = math.max(64, (flat.height * scaleOut).round());

  final dstRect = <Point2D>[
    [0, 0],
    [(outW - 1).toDouble(), 0],
    [(outW - 1).toDouble(), (outH - 1).toDouble()],
    [0, (outH - 1).toDouble()],
  ];
  final hInv = computeHomography(dstRect, ordered);
  final out = img.Image(width: outW, height: outH);
  final maxSx = image.width - 1.001;
  final maxSy = image.height - 1.001;

  for (var y = 0; y < outH; y++) {
    var rx = hInv[1] * y + hInv[2];
    var ry = hInv[4] * y + hInv[5];
    var rw = hInv[7] * y + hInv[8];
    for (var x = 0; x < outW; x++) {
      final invW = 1.0 / (rw.abs() < 1e-9 ? 1e-9 : rw);
      final sx = (rx * invW).clamp(0.0, maxSx);
      final sy = (ry * invW).clamp(0.0, maxSy);
      final x0 = sx.floor();
      final y0 = sy.floor();
      final fx = sx - x0;
      final fy = sy - y0;
      final fx1 = 1.0 - fx;
      final fy1 = 1.0 - fy;

      final p00 = image.getPixel(x0, y0);
      final p10 = image.getPixel(x0 + 1, y0);
      final p01 = image.getPixel(x0, y0 + 1);
      final p11 = image.getPixel(x0 + 1, y0 + 1);

      final w00 = fx1 * fy1, w10 = fx * fy1, w01 = fx1 * fy, w11 = fx * fy;
      final r = (p00.r * w00 + p10.r * w10 + p01.r * w01 + p11.r * w11).round();
      final g = (p00.g * w00 + p10.g * w10 + p01.g * w01 + p11.g * w11).round();
      final b = (p00.b * w00 + p10.b * w10 + p01.b * w01 + p11.b * w11).round();
      out.setPixelRgb(x, y, r, g, b);

      rx += hInv[0];
      ry += hInv[3];
      rw += hInv[6];
    }
  }
  return Uint8List.fromList(
    job.png ? img.encodePng(out, level: 3) : img.encodeJpg(out, quality: 90),
  );
}

/// Isolate entrypoint: crop & perspective-rectify photo bytes cleanly to a flat 90-degree PNG.
Uint8List cropPhotoToLensQuad(
  ({Uint8List bytes, int rotation, List<Point2D> quad}) job,
) => warpPhotoToFlat90Bytes((
  bytes: job.bytes,
  rotation: job.rotation,
  quad: job.quad,
  maxSide: 2048,
  png: true,
));
