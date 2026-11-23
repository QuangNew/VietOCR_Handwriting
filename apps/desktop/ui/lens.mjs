/* Pure geometry + robust client-side paper detection for Google Lens overlay on Ảnh gốc. */

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
  // Sort by angle around centroid, then rotate so top-left (min x+y) is index 0 clockwise
  let cx = 0, cy = 0;
  for (const [x, y] of arr) { cx += x; cy += y; }
  cx /= 4; cy /= 4;
  arr.sort((a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx));
  let tlIdx = 0, minS = Infinity;
  for (let i = 0; i < 4; i++) {
    const s = arr[i][0] + arr[i][1];
    if (s < minS) { minS = s; tlIdx = i; }
  }
  return [arr[tlIdx], arr[(tlIdx + 1) % 4], arr[(tlIdx + 2) % 4], arr[(tlIdx + 3) % 4]];
}

export function pointAlong(a, b, distance) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const t = Math.min(0.42, distance / len);
  return [a[0] + dx * t, a[1] + dy * t];
}

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

export function expandPolygon(poly, pad, maxW = Infinity, maxH = Infinity) {
  if (!Array.isArray(poly) || poly.length < 3) return [];
  let cx = 0, cy = 0;
  for (const p of poly) { cx += p[0]; cy += p[1]; }
  cx /= poly.length;
  cy /= poly.length;
  return poly.map(([x, y]) => {
    const dx = x - cx;
    const dy = y - cy;
    const len = Math.hypot(dx, dy) || 1;
    const nx = Math.max(0, Math.min(maxW, x + (dx / len) * pad));
    const ny = Math.max(0, Math.min(maxH, y + (dy / len) * pad));
    return [nx, ny];
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

export function pointInPolygon(px, py, poly) {
  if (!Array.isArray(poly) || poly.length < 3) return false;
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1];
    const xj = poly[j][0], yj = poly[j][1];
    const intersect = ((yi > py) !== (yj > py)) && (px < ((xj - xi) * (py - yi)) / ((yj - yi) || 1e-9) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

export function linesInsideQuad(lines, quad) {
  if (!Array.isArray(lines) || !Array.isArray(quad) || quad.length !== 4) return [];
  return lines.filter(l => {
    if (!Array.isArray(l.polygon) || l.polygon.length < 3) return true;
    const b = polygonBounds(l.polygon);
    return pointInPolygon(b.cx, b.cy, quad);
  });
}

/* ---------- Convex hull & minimum-area oriented bounding quad ---------- */
function cross2d(o, a, b) {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
}

export function convexHull(points) {
  if (!points || points.length < 3) return points || [];
  const pts = points.slice().sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross2d(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross2d(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

function polygonArea(poly) {
  let area = 0;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    area += poly[j][0] * poly[i][1] - poly[i][0] * poly[j][1];
  }
  return Math.abs(area) / 2;
}

export function minAreaRectFromHull(hull) {
  if (!hull || hull.length < 3) return null;
  let bestArea = Infinity;
  let bestQuad = null;
  for (let i = 0; i < hull.length; i++) {
    const a = hull[i];
    const b = hull[(i + 1) % hull.length];
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    if (len < 1e-6) continue;
    const ux = dx / len, uy = dy / len;
    const vx = -uy, vy = ux;
    let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
    for (const [px, py] of hull) {
      const u = px * ux + py * uy;
      const v = px * vx + py * vy;
      if (u < minU) minU = u;
      if (u > maxU) maxU = u;
      if (v < minV) minV = v;
      if (v > maxV) maxV = v;
    }
    const area = (maxU - minU) * (maxV - minV);
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
  return bestQuad ? orderQuad(bestQuad) : null;
}

function simplifyClosedPolygonToQuad(hull) {
  if (!hull || hull.length < 4) return null;
  if (hull.length === 4) return orderQuad(hull);
  const hullArea = Math.max(1, polygonArea(hull));
  // Iteratively drop the vertex whose removal changes polygon area the least (Visvalingam-Whyatt)
  let pts = hull.slice();
  while (pts.length > 4) {
    let minDrop = Infinity;
    let dropIdx = 0;
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const prev = pts[(i + n - 1) % n];
      const curr = pts[i];
      const next = pts[(i + 1) % n];
      const tri = Math.abs(cross2d(prev, curr, next)) / 2;
      if (tri < minDrop) { minDrop = tri; dropIdx = i; }
    }
    pts.splice(dropIdx, 1);
  }
  const quadArea = polygonArea(pts);
  if (quadArea / hullArea >= 0.86) return orderQuad(pts);
  return null;
}

/* ---------- Binary morphology helpers on downsampled mask ---------- */
function morphOp(mask, w, h, radius, dilate) {
  // Separable horizontal then vertical pass (O(w*h*r))
  const tmp = new Uint8Array(w * h);
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    for (let x = 0; x < w; x++) {
      let val = dilate ? 0 : 1;
      const x0 = Math.max(0, x - radius);
      const x1 = Math.min(w - 1, x + radius);
      for (let xx = x0; xx <= x1; xx++) {
        const m = mask[row + xx];
        if (dilate ? m : !m) { val = dilate ? 1 : 0; break; }
      }
      tmp[row + x] = val;
    }
  }
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - radius);
    const y1 = Math.min(h - 1, y + radius);
    for (let x = 0; x < w; x++) {
      let val = dilate ? 0 : 1;
      for (let yy = y0; yy <= y1; yy++) {
        const m = tmp[yy * w + x];
        if (dilate ? m : !m) { val = dilate ? 1 : 0; break; }
      }
      out[y * w + x] = val;
    }
  }
  return out;
}

/**
 * Pure RGBA buffer paper detector (testable in Node & browser).
 * Stage 1: Cool-achromatic seed finds the paper sheet's own white-point (coreR, coreG, coreB).
 * Stage 2: Relative normalized chromaticity + brightness matching against the paper's own white-point
 *          cleanly rejects warm specular wood-desk glare while keeping shadowed corners of the paper.
 * Stage 3: Morphological closing (fills handwriting ink) + opening + convex-hull quad fitting.
 */
export function detectPaperQuadFromRgba(data, w, h, natW = w, natH = h) {
  const n = w * h;
  if (w < 16 || h < 16 || !data || data.length < n * 4) return null;

  // Step 1: Blue-weighted achromatic paper score for initial seed finding
  const scores = new Uint8Array(n);
  const hist = new Uint32Array(256);
  for (let i = 0; i < n; i++) {
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    const maxC = r > g ? (r > b ? r : b) : (g > b ? g : b);
    const minC = r < g ? (r < b ? r : b) : (g < b ? g : b);
    const chroma = maxC - minC;
    const warmth = (r > b ? (r - b) * 1.65 : 0) + (g > b ? (g - b) * 0.45 : 0);
    const coolLuma = 0.52 * b + 0.32 * g + 0.16 * r;
    const s = Math.max(0, Math.min(255, Math.round(coolLuma - warmth - chroma * 0.45)));
    scores[i] = s;
    hist[s]++;
  }

  // Step 2: Otsu threshold on initial paper score
  let sumAll = 0;
  for (let t = 0; t < 256; t++) sumAll += t * hist[t];
  let sumB = 0, wB = 0, maxVar = -1, bestT = 110;
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

  const baseT = Math.max(78, bestT);
  // Find 90th percentile of foreground scores to build a strict pure-paper seed
  let fgTotal = 0;
  for (let t = baseT; t < 256; t++) fgTotal += hist[t];
  if (fgTotal / n < 0.06 || fgTotal / n > 0.94) return null;

  let acc = 0, p60Fg = baseT;
  for (let t = baseT; t < 256; t++) {
    acc += hist[t];
    if (acc >= fgTotal * 0.60) { p60Fg = t; break; }
  }
  const seedT = Math.max(baseT, p60Fg);

  // Compute paper core white-point from interior seed pixels (ignore outer 5% frame border)
  const bx0 = Math.floor(w * 0.05), bx1 = Math.ceil(w * 0.95);
  const by0 = Math.floor(h * 0.05), by1 = Math.ceil(h * 0.95);
  const rHist = new Uint32Array(256);
  const gHist = new Uint32Array(256);
  const bHist = new Uint32Array(256);
  let seedCount = 0;
  for (let y = by0; y < by1; y++) {
    const row = y * w;
    for (let x = bx0; x < bx1; x++) {
      const idx = row + x;
      if (scores[idx] >= seedT) {
        rHist[data[idx * 4]]++;
        gHist[data[idx * 4 + 1]]++;
        bHist[data[idx * 4 + 2]]++;
        seedCount++;
      }
    }
  }
  if (seedCount < n * 0.02) {
    // Fallback to whole image if paper is near edges
    for (let idx = 0; idx < n; idx++) {
      if (scores[idx] >= seedT) {
        rHist[data[idx * 4]]++;
        gHist[data[idx * 4 + 1]]++;
        bHist[data[idx * 4 + 2]]++;
        seedCount++;
      }
    }
  }
  if (seedCount < 16) return null;

  const medianOf = hArr => {
    let s = 0;
    const half = seedCount * 0.5;
    for (let v = 0; v < 256; v++) { s += hArr[v]; if (s >= half) return v; }
    return 200;
  };
  const coreR = medianOf(rHist);
  const coreG = medianOf(gHist);
  const coreB = medianOf(bHist);
  const coreSum = Math.max(1, coreR + coreG + coreB);
  const crn = coreR / coreSum;
  const cgn = coreG / coreSum;
  const cbn = coreB / coreSum;
  const coreLuma = 0.299 * coreR + 0.587 * coreG + 0.114 * coreB;
  const minLuma = Math.max(68, coreLuma * 0.62);

  // Step 3: Relative chromaticity + brightness mask matching the paper sheet's own illumination
  const rawMask = new Uint8Array(n);
  let paperPix = 0;
  for (let i = 0; i < n; i++) {
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    const luma = 0.299 * r + 0.587 * g + 0.114 * b;
    if (luma < minLuma) continue;
    const sum = r + g + b;
    if (sum < 60) continue;
    const rn = r / sum;
    const gn = g / sum;
    const bn = b / sum;
    const chromaL1 = Math.abs(rn - crn) + Math.abs(gn - cgn) + Math.abs(bn - cbn);
    // Specular glare on warm wood shifts rn up & bn down (chromaL1 ~ 0.08..0.15); true paper stays <= 0.048
    if (chromaL1 <= 0.050 && (rn - crn) <= 0.026 && (cbn - bn) <= 0.028) {
      rawMask[i] = 1;
      paperPix++;
    }
  }

  const paperFrac = paperPix / n;
  if (paperFrac < 0.05 || paperFrac > 0.94) return null;

  // Step 4: Closing (fills handwriting strokes inside sheet) then Opening (removes tiny edge speckles)
  let clean = morphOp(rawMask, w, h, 3, true);
  clean = morphOp(clean, w, h, 3, false);
  clean = morphOp(clean, w, h, 2, false);
  clean = morphOp(clean, w, h, 2, true);

  // Step 5: Connected components — select largest paper sheet (slight center preference beats edge objects)
  const visited = new Uint8Array(n);
  const queue = new Int32Array(n);
  let bestPixels = null;
  let bestScore = 0;
  let bestCount = 0;
  const cxImg = w / 2, cyImg = h / 2, maxDist = Math.hypot(cxImg, cyImg) || 1;

  for (let i = 0; i < n; i++) {
    if (!clean[i] || visited[i]) continue;
    let head = 0, tail = 0;
    let sumX = 0, sumY = 0;
    queue[tail++] = i;
    visited[i] = 1;
    while (head < tail) {
      const idx = queue[head++];
      const x = idx % w;
      const y = (idx - x) / w;
      sumX += x; sumY += y;
      if (x > 0 && clean[idx - 1] && !visited[idx - 1]) { visited[idx - 1] = 1; queue[tail++] = idx - 1; }
      if (x + 1 < w && clean[idx + 1] && !visited[idx + 1]) { visited[idx + 1] = 1; queue[tail++] = idx + 1; }
      if (y > 0 && clean[idx - w] && !visited[idx - w]) { visited[idx - w] = 1; queue[tail++] = idx - w; }
      if (y + 1 < h && clean[idx + w] && !visited[idx + w]) { visited[idx + w] = 1; queue[tail++] = idx + w; }
    }
    if (tail < n * 0.05) continue;
    const dNorm = Math.hypot(sumX / tail - cxImg, sumY / tail - cyImg) / maxDist;
    const compScore = tail * (1.28 - 0.50 * dNorm);
    if (compScore > bestScore) {
      bestScore = compScore;
      bestCount = tail;
      bestPixels = queue.slice(0, tail);
    }
  }

  if (!bestPixels || bestCount < n * 0.06 || bestCount > n * 0.94) return null;

  // Step 6: Extract boundary pixels -> Convex Hull -> Tight 4-corner quad (handles rotation & perspective!)
  const inBest = new Uint8Array(n);
  for (let k = 0; k < bestPixels.length; k++) inBest[bestPixels[k]] = 1;
  const boundary = [];
  for (let k = 0; k < bestPixels.length; k++) {
    const idx = bestPixels[k];
    const x = idx % w;
    const y = (idx - x) / w;
    if (x === 0 || y === 0 || x === w - 1 || y === h - 1 ||
      !inBest[idx - 1] || !inBest[idx + 1] || !inBest[idx - w] || !inBest[idx + w]) {
      boundary.push([x + 0.5, y + 0.5]);
    }
  }
  const hull = convexHull(boundary);
  const approxQuad = simplifyClosedPolygonToQuad(hull);
  const minRect = minAreaRectFromHull(hull);
  let chosen = approxQuad || minRect;
  if (approxQuad && minRect) {
    const hullA = Math.max(1, polygonArea(hull));
    const qA = polygonArea(approxQuad);
    const rA = polygonArea(minRect);
    // Prefer minAreaRect when it fits closer to hull (straight rectangular sheets), approxQuad when strong perspective
    chosen = Math.abs(rA - hullA) <= Math.abs(qA - hullA) * 1.15 ? minRect : approxQuad;
  }
  if (!chosen) return null;

  const sx = natW / w;
  const sy = natH / h;
  const scaled = chosen.map(([x, y]) => [
    Math.max(0, Math.min(natW, x * sx)),
    Math.max(0, Math.min(natH, y * sy)),
  ]);
  // Slight outward safety padding (+1.2% of paper size) so text near margins is never clipped
  const b = polygonBounds(scaled);
  const pad = Math.min(natW, natH) * 0.012;
  const padded = expandPolygon(scaled, Math.min(pad, Math.min(b.maxX - b.minX, b.maxY - b.minY) * 0.03), natW, natH);

  return {
    sourceWidth: natW,
    sourceHeight: natH,
    route: 'client-preview',
    paperDetected: true,
    paperQuad: orderQuad(padded).map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10]),
    lines: [],
    clientOnly: true,
  };
}

export function detectPaperQuadFromImage(imgElement) {
  const natW = imgElement?.naturalWidth || 0;
  const natH = imgElement?.naturalHeight || 0;
  if (natW < 32 || natH < 32 || typeof document === 'undefined') return null;

  const maxSide = 260;
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
  return detectPaperQuadFromRgba(data, w, h, natW, natH);
}
