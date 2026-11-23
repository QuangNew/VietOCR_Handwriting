/* Pure geometry + fast client-side paper detection for Google Lens overlay on Ảnh gốc. */

export function computeContainedRect(containerW, containerH, naturalW, naturalH) {
  if (!containerW || !containerH || !naturalW || !naturalH) {
    return { left: 0, top: 0, width: 0, height: 0, scale: 1 };
  }
  const scale = Math.min(containerW / naturalW, containerH / naturalH);
  const width = naturalW * scale;
  const height = naturalH * scale;
  return {
    left: (containerW - width) / 2,
    top: (containerH - height) / 2,
    width,
    height,
    scale,
  };
}

export function orderQuad(pts) {
  if (!Array.isArray(pts) || pts.length !== 4) return null;
  const arr = pts.map(p => [Number(p[0]), Number(p[1])]);
  let tl = arr[0], br = arr[0], tr = arr[0], bl = arr[0];
  let minS = Infinity, maxS = -Infinity, minD = Infinity, maxD = -Infinity;
  for (const p of arr) {
    const s = p[0] + p[1];
    const d = p[1] - p[0];
    if (s < minS) { minS = s; tl = p; }
    if (s > maxS) { maxS = s; br = p; }
    if (d < minD) { minD = d; tr = p; }
    if (d > maxD) { maxD = d; bl = p; }
  }
  return [tl, tr, br, bl];
}

export function pointAlong(a, b, distance) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const t = Math.min(0.42, distance / len);
  return [a[0] + dx * t, a[1] + dy * t];
}

/**
 * Build the 4 Google-Lens-style white rounded L-brackets around a 4-corner quad [TL, TR, BR, BL].
 */
export function buildCornerBracketPaths(quad, armLen, radius) {
  if (!quad || quad.length !== 4) return [];
  const paths = [];
  for (let i = 0; i < 4; i++) {
    const prev = quad[(i + 3) % 4];
    const curr = quad[i];
    const next = quad[(i + 1) % 4];
    const r = Math.min(radius, armLen * 0.55);
    const pStart = pointAlong(curr, prev, armLen);
    const pCurveIn = pointAlong(curr, prev, r);
    const pCurveOut = pointAlong(curr, next, r);
    const pEnd = pointAlong(curr, next, armLen);
    paths.push(
      `M ${pStart[0].toFixed(1)} ${pStart[1].toFixed(1)} ` +
      `L ${pCurveIn[0].toFixed(1)} ${pCurveIn[1].toFixed(1)} ` +
      `Q ${curr[0].toFixed(1)} ${curr[1].toFixed(1)} ${pCurveOut[0].toFixed(1)} ${pCurveOut[1].toFixed(1)} ` +
      `L ${pEnd[0].toFixed(1)} ${pEnd[1].toFixed(1)}`
    );
  }
  return paths;
}

export function expandPolygon(poly, pad) {
  if (!Array.isArray(poly) || poly.length < 3) return [];
  let cx = 0, cy = 0;
  for (const p of poly) { cx += p[0]; cy += p[1]; }
  cx /= poly.length;
  cy /= poly.length;
  return poly.map(([x, y]) => {
    const dx = x - cx;
    const dy = y - cy;
    const len = Math.hypot(dx, dy) || 1;
    return [x + (dx / len) * pad, y + (dy / len) * pad];
  });
}

export function polygonBounds(poly) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of poly) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
}

export function quadScrimPath(sourceW, sourceH, quad) {
  if (!quad || quad.length !== 4) return '';
  const q = quad.map(p => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`);
  return `M 0 0 H ${sourceW} V ${sourceH} H 0 Z M ${q[0]} L ${q[1]} L ${q[2]} L ${q[3]} Z`;
}

/**
 * Fast client-side paper detection (runs in ~10-20ms on a 220px downsampled canvas)
 * so the Google Lens paper frame locks on immediately after import/capture, before OCR runs.
 */
export function detectPaperQuadFromImage(imgElement) {
  const natW = imgElement?.naturalWidth || 0;
  const natH = imgElement?.naturalHeight || 0;
  if (natW < 32 || natH < 32 || typeof document === 'undefined') return null;

  const maxSide = 220;
  const scale = Math.min(1, maxSide / Math.max(natW, natH));
  const w = Math.max(16, Math.round(natW * scale));
  const h = Math.max(16, Math.round(natH * scale));

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(imgElement, 0, 0, w, h);
  const { data } = ctx.getImageData(0, 0, w, h);

  // Score each pixel for "paper-ness": bright + low color saturation
  const n = w * h;
  const scores = new Float32Array(n);
  const hist = new Uint32Array(256);
  for (let i = 0; i < n; i++) {
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    const maxC = Math.max(r, g, b);
    const minC = Math.min(r, g, b);
    const luma = 0.299 * r + 0.587 * g + 0.114 * b;
    const sat = maxC > 0 ? (maxC - minC) / maxC : 0;
    const score = Math.max(0, Math.min(255, luma - sat * 140));
    scores[i] = score;
    hist[Math.round(score)]++;
  }

  // Otsu threshold on paper score
  let sumAll = 0;
  for (let t = 0; t < 256; t++) sumAll += t * hist[t];
  let sumB = 0, wB = 0, maxVar = -1, bestT = 135;
  for (let t = 0; t < 256; t++) {
    wB += hist[t];
    if (!wB) continue;
    const wF = n - wB;
    if (!wF) break;
    sumB += t * hist[t];
    const mB = sumB / wB;
    const mF = (sumAll - sumB) / wF;
    const between = wB * wF * (mB - mF) * (mB - mF);
    if (between > maxVar) { maxVar = between; bestT = t; }
  }

  // Check foreground vs background separation; if image is already flat white page, don't force a bogus box
  const threshold = Math.max(95, bestT);
  const mask = new Uint8Array(n);
  let brightCount = 0;
  for (let i = 0; i < n; i++) {
    if (scores[i] >= threshold) { mask[i] = 1; brightCount++; }
  }
  const brightFrac = brightCount / n;
  if (brightFrac < 0.08 || brightFrac > 0.93) {
    return null;
  }

  // Find largest connected component via BFS
  const visited = new Uint8Array(n);
  const queue = new Int32Array(n);
  let bestPixels = null;
  let bestCount = 0;
  for (let i = 0; i < n; i++) {
    if (!mask[i] || visited[i]) continue;
    let head = 0, tail = 0;
    queue[tail++] = i;
    visited[i] = 1;
    while (head < tail) {
      const idx = queue[head++];
      const x = idx % w;
      const y = (idx - x) / w;
      if (x > 0 && mask[idx - 1] && !visited[idx - 1]) { visited[idx - 1] = 1; queue[tail++] = idx - 1; }
      if (x + 1 < w && mask[idx + 1] && !visited[idx + 1]) { visited[idx + 1] = 1; queue[tail++] = idx + 1; }
      if (y > 0 && mask[idx - w] && !visited[idx - w]) { visited[idx - w] = 1; queue[tail++] = idx - w; }
      if (y + 1 < h && mask[idx + w] && !visited[idx + w]) { visited[idx + w] = 1; queue[tail++] = idx + w; }
    }
    if (tail > bestCount) {
      bestCount = tail;
      bestPixels = queue.slice(0, tail);
    }
  }

  if (!bestPixels || bestCount < n * 0.1 || bestCount > n * 0.93) return null;

  // Estimate tight quad using extreme corner projections (sum x+y, diff y-x) with slight percentile robustness
  let tlX = 0, tlY = 0, trX = 0, trY = 0, brX = 0, brY = 0, blX = 0, blY = 0;
  let minS = Infinity, maxS = -Infinity, minD = Infinity, maxD = -Infinity;
  let minX = w, minY = h, maxX = 0, maxY = 0;
  for (let k = 0; k < bestPixels.length; k++) {
    const idx = bestPixels[k];
    const x = idx % w;
    const y = (idx - x) / w;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
    const s = x + y;
    const d = y - x;
    if (s < minS) { minS = s; tlX = x; tlY = y; }
    if (s > maxS) { maxS = s; brX = x; brY = y; }
    if (d < minD) { minD = d; trX = x; trY = y; }
    if (d > maxD) { maxD = d; blX = x; blY = y; }
  }

  const bw = maxX - minX + 1;
  const bh = maxY - minY + 1;
  const rectArea = bw * bh;
  const fillRatio = bestCount / Math.max(1, rectArea);
  const sx = natW / w;
  const sy = natH / h;

  // Use extreme quad if clean rectangular fill, else tidy axis-aligned box
  const quad = fillRatio > 0.72
    ? orderQuad([
        [tlX * sx, tlY * sy],
        [(trX + 1) * sx, trY * sy],
        [(brX + 1) * sx, (brY + 1) * sy],
        [blX * sx, (blY + 1) * sy],
      ])
    : [
        [minX * sx, minY * sy],
        [(maxX + 1) * sx, minY * sy],
        [(maxX + 1) * sx, (maxY + 1) * sy],
        [minX * sx, (maxY + 1) * sy],
      ];

  return {
    sourceWidth: natW,
    sourceHeight: natH,
    route: 'client-preview',
    paperDetected: true,
    paperQuad: quad.map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10]),
    lines: [],
    clientOnly: true,
  };
}
