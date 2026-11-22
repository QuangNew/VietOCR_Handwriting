export function outline(points, shape, angle = 0) {
  if (
    !Number.isFinite(angle) ||
    Math.abs(angle) > 180 ||
    points.length > 4096 ||
    points.some(p => p.length !== 2 || p.some(n => !Number.isFinite(n)))
  ) {
    throw Error('Vùng crop không hợp lệ');
  }
  if (points.length < 2) return [];
  let polygon = points;
  if (shape !== 'freehand') {
    const [a, b] = [points[0], points.at(-1)];
    const l = Math.min(a[0], b[0]);
    const r = Math.max(a[0], b[0]);
    const t = Math.min(a[1], b[1]);
    const bt = Math.max(a[1], b[1]);
    polygon =
      shape === 'ellipse'
        ? Array.from({ length: 96 }, (_, i) => [
            (l + r) / 2 + ((r - l) / 2) * Math.cos((i * Math.PI) / 48),
            (t + bt) / 2 + ((bt - t) / 2) * Math.sin((i * Math.PI) / 48),
          ])
        : [
            [l, t],
            [r, t],
            [r, bt],
            [l, bt],
          ];
  }
  if (!angle) return polygon;
  const x = polygon.map(p => p[0]);
  const y = polygon.map(p => p[1]);
  const cx = (Math.min(...x) + Math.max(...x)) / 2;
  const cy = (Math.min(...y) + Math.max(...y)) / 2;
  const c = Math.cos((angle * Math.PI) / 180);
  const s = Math.sin((angle * Math.PI) / 180);
  return polygon.map(([px, py]) => [cx + c * (px - cx) - s * (py - cy), cy + s * (px - cx) + c * (py - cy)]);
}

export function bounds(points, width, height) {
  if (points.length < 3) throw Error('Vẽ vùng kín trước khi crop');
  const x = points.map(p => p[0]);
  const y = points.map(p => p[1]);
  const l = Math.floor(Math.min(...x));
  const t = Math.floor(Math.min(...y));
  const r = Math.ceil(Math.max(...x));
  const b = Math.ceil(Math.max(...y));
  if (l < 0 || t < 0 || r > width || b > height || r - l < 2 || b - t < 2) {
    throw Error('Vùng crop rỗng hoặc vượt mép ảnh');
  }
  return { l, t, w: r - l, h: b - t };
}

export function segmentIntersect(a, b, c, d) {
  const x1 = a[0], y1 = a[1], x2 = b[0], y2 = b[1];
  const x3 = c[0], y3 = c[1], x4 = d[0], y4 = d[1];
  const denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
  if (Math.abs(denom) < 1e-9) return null;
  const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom;
  const u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom;
  if (t >= 0 && t <= 1 && u >= 0 && u <= 1) {
    return [x1 + t * (x2 - x1), y1 + t * (y2 - y1)];
  }
  return null;
}

export function dist(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/**
 * Checks whether the newest freehand segment crosses any earlier segment.
 * If it does, trims the stroke cleanly into the exact closed loop (Photoshop Lasso style).
 */
export function detectSelfClose(points) {
  const n = points.length;
  if (n < 5) return null;
  const pA = points[n - 2];
  const pB = points[n - 1];
  for (let i = 0; i <= n - 4; i++) {
    const hit = segmentIntersect(points[i], points[i + 1], pA, pB);
    if (hit) {
      const loop = [hit, ...points.slice(i + 1, n - 1)];
      if (loop.length >= 3) return loop;
    }
  }
  return null;
}

/**
 * Finalizes a freehand stroke on pointer up: requires either self-intersection
 * or the end point meeting the start point within `snapDist` pixels.
 */
export function finalizeFreehand(points, snapDist = 24) {
  if (points.length < 4) return { closed: false, polygon: [] };
  const selfLoop = detectSelfClose(points);
  if (selfLoop) return { closed: true, polygon: selfLoop };
  if (dist(points[0], points.at(-1)) <= snapDist) {
    return { closed: true, polygon: points.slice(0, -1) };
  }
  return { closed: false, polygon: [] };
}

export function draftOnlyAction(action) {
  return ['import', 'capture', 'crop', 'blackWhite', 'rotate'].includes(action);
}
