/* 90-degree perspective-rectified flat-page renderer ("Ảnh văn bản" & "Đối chiếu") + homography math. */
import { polygonBounds, orderQuad } from './lens.mjs';

const warpCache = new Map();

/**
 * Wrap a single paragraph into lines that fit within maxWidth using ctx.measureText.
 */
export function wrapParagraph(ctx, text, maxWidth) {
  const trimmed = String(text ?? '');
  if (!trimmed.trim()) return [''];
  const words = trimmed.split(/\s+/);
  const lines = [];
  let cur = '';
  for (const word of words) {
    const candidate = cur ? `${cur} ${word}` : word;
    if (!cur || ctx.measureText(candidate).width <= maxWidth) {
      cur = candidate;
    } else {
      lines.push(cur);
      cur = word;
    }
  }
  if (cur) lines.push(cur);
  return lines;
}

/**
 * Compute gentle reading angle (in radians, clamped to +-12 deg) of a 4-point line polygon.
 */
export function estimateLineAngle(poly) {
  if (!Array.isArray(poly) || poly.length < 4) return 0;
  const dx = poly[1][0] - poly[0][0];
  const dy = poly[1][1] - poly[0][1];
  if (Math.hypot(dx, dy) < 8) return 0;
  const rad = Math.atan2(dy, dx);
  const maxRad = (12 * Math.PI) / 180;
  return Math.max(-maxRad, Math.min(maxRad, rad));
}

/**
 * Compute natural 90-degree straight landscape or portrait dimensions for a 4-point paper quad.
 */
export function computeQuadFlatSize(quad, fallbackW = 1000, fallbackH = 1000) {
  if (!Array.isArray(quad) || quad.length !== 4) {
    const w = Math.max(64, Math.round(fallbackW || 1000));
    const h = Math.max(64, Math.round(fallbackH || 1000));
    return { width: w, height: h, orientation: w >= h ? 'landscape' : 'portrait' };
  }
  const [tl, tr, br, bl] = orderQuad(quad) || quad;
  const topW = Math.hypot(tr[0] - tl[0], tr[1] - tl[1]);
  const botW = Math.hypot(br[0] - bl[0], br[1] - bl[1]);
  const leftH = Math.hypot(bl[0] - tl[0], bl[1] - tl[1]);
  const rightH = Math.hypot(br[0] - tr[0], br[1] - tr[1]);
  const w = Math.max(64, Math.round((topW + botW) / 2));
  const h = Math.max(64, Math.round((leftH + rightH) / 2));
  return { width: w, height: h, orientation: w >= h ? 'landscape' : 'portrait' };
}

/**
 * Solve exact 3x3 projective homography H mapping 4 source points -> 4 destination points.
 * Returns flat 9-element array [h0..h7, 1] or identity if singular.
 */
export function computeHomography(srcQuad, dstQuad) {
  if (!Array.isArray(srcQuad) || !Array.isArray(dstQuad) || srcQuad.length !== 4 || dstQuad.length !== 4) {
    return [1, 0, 0, 0, 1, 0, 0, 0, 1];
  }
  const A = [];
  const b = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = srcQuad[i];
    const [u, v] = dstQuad[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]);
    b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]);
    b.push(v);
  }
  // Gaussian elimination with partial pivoting (8x8)
  const n = 8;
  for (let col = 0; col < n; col++) {
    let pivot = col;
    let maxVal = Math.abs(A[col][col]);
    for (let row = col + 1; row < n; row++) {
      const val = Math.abs(A[row][col]);
      if (val > maxVal) { maxVal = val; pivot = row; }
    }
    if (maxVal < 1e-10) return [1, 0, 0, 0, 1, 0, 0, 0, 1];
    if (pivot !== col) {
      [A[col], A[pivot]] = [A[pivot], A[col]];
      [b[col], b[pivot]] = [b[pivot], b[col]];
    }
    const diag = A[col][col];
    for (let j = col; j < n; j++) A[col][j] /= diag;
    b[col] /= diag;
    for (let row = 0; row < n; row++) {
      if (row === col) continue;
      const factor = A[row][col];
      if (Math.abs(factor) < 1e-12) continue;
      for (let j = col; j < n; j++) A[row][j] -= factor * A[col][j];
      b[row] -= factor * b[col];
    }
  }
  return [b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], 1];
}

export function projectPoint(H, pt) {
  const x = pt[0], y = pt[1];
  const w = H[6] * x + H[7] * y + H[8];
  if (Math.abs(w) < 1e-9) return [x, y];
  return [(H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w];
}

/**
 * Perspective-warp an HTMLImageElement's 4-point paper quad into a straight 90-degree flat canvas.
 * Cached by image + quad so resizing & Đối chiếu slider dragging run at 60fps.
 */
export function warpImageQuadToFlatCanvas(imgElement, quad, maxSide = 1000) {
  const natW = imgElement?.naturalWidth || 0;
  const natH = imgElement?.naturalHeight || 0;
  if (!natW || !natH || typeof document === 'undefined') return null;

  const hasQuad = Array.isArray(quad) && quad.length === 4;
  const ordered = hasQuad ? (orderQuad(quad) || quad) : null;
  const flat = computeQuadFlatSize(ordered, natW, natH);
  const scaleOut = Math.min(1, maxSide / Math.max(flat.width, flat.height));
  const outW = Math.max(64, Math.round(flat.width * scaleOut));
  const outH = Math.max(64, Math.round(flat.height * scaleOut));

  const srcKey = String(imgElement.src || '');
  const quadKey = ordered ? ordered.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(';') : 'full';
  const cacheKey = `${srcKey.slice(0, 48)}:${srcKey.length}:${natW}x${natH}:${quadKey}:${outW}x${outH}`;
  if (warpCache.has(cacheKey)) return warpCache.get(cacheKey);

  const out = document.createElement('canvas');
  out.width = outW;
  out.height = outH;
  const outCtx = out.getContext('2d');
  if (!outCtx) return null;

  if (!ordered) {
    outCtx.drawImage(imgElement, 0, 0, outW, outH);
  } else {
    // Draw source at capped resolution (<= 1600px) for fast high-quality bilinear resampling
    const srcScale = Math.min(1, 1600 / Math.max(natW, natH));
    const sw = Math.max(16, Math.round(natW * srcScale));
    const sh = Math.max(16, Math.round(natH * srcScale));
    const srcCanvas = document.createElement('canvas');
    srcCanvas.width = sw;
    srcCanvas.height = sh;
    const srcCtx = srcCanvas.getContext('2d', { willReadFrequently: true });
    srcCtx.drawImage(imgElement, 0, 0, sw, sh);
    const srcData = srcCtx.getImageData(0, 0, sw, sh).data;

    const scaledSrcQuad = ordered.map(([x, y]) => [x * srcScale, y * srcScale]);
    const dstRect = [[0, 0], [outW - 1, 0], [outW - 1, outH - 1], [0, outH - 1]];
    const Hinv = computeHomography(dstRect, scaledSrcQuad);

    const dstImg = outCtx.createImageData(outW, outH);
    const dst = dstImg.data;
    const h0 = Hinv[0], h1 = Hinv[1], h2 = Hinv[2];
    const h3 = Hinv[3], h4 = Hinv[4], h5 = Hinv[5];
    const h6 = Hinv[6], h7 = Hinv[7], h8 = Hinv[8];
    const maxSx = sw - 1.001, maxSy = sh - 1.001;

    let p = 0;
    for (let y = 0; y < outH; y++) {
      let rx = h1 * y + h2;
      let ry = h4 * y + h5;
      let rw = h7 * y + h8;
      for (let x = 0; x < outW; x++) {
        const invW = 1 / (rw || 1e-9);
        const sx = Math.max(0, Math.min(maxSx, rx * invW));
        const sy = Math.max(0, Math.min(maxSy, ry * invW));
        const x0 = sx | 0;
        const y0 = sy | 0;
        const fx = sx - x0;
        const fy = sy - y0;
        const fx1 = 1 - fx;
        const fy1 = 1 - fy;

        const idx00 = (y0 * sw + x0) * 4;
        const idx10 = idx00 + 4;
        const idx01 = idx00 + sw * 4;
        const idx11 = idx01 + 4;

        const w00 = fx1 * fy1;
        const w10 = fx * fy1;
        const w01 = fx1 * fy;
        const w11 = fx * fy;

        dst[p]     = (srcData[idx00]     * w00 + srcData[idx10]     * w10 + srcData[idx01]     * w01 + srcData[idx11]     * w11) | 0;
        dst[p + 1] = (srcData[idx00 + 1] * w00 + srcData[idx10 + 1] * w10 + srcData[idx01 + 1] * w01 + srcData[idx11 + 1] * w11) | 0;
        dst[p + 2] = (srcData[idx00 + 2] * w00 + srcData[idx10 + 2] * w10 + srcData[idx01 + 2] * w01 + srcData[idx11 + 2] * w11) | 0;
        dst[p + 3] = 255;
        p += 4;
        rx += h0;
        ry += h3;
        rw += h6;
      }
    }
    outCtx.putImageData(dstImg, 0, 0);
  }

  warpCache.set(cacheKey, out);
  if (warpCache.size > 14) {
    const oldest = warpCache.keys().next().value;
    warpCache.delete(oldest);
  }
  return out;
}

/**
 * Draw a pre-warped flat photo onto target display canvas at crisp devicePixelRatio.
 */
export function drawRectifiedPhoto(canvas, warpedCanvas, cssWidth, cssHeight) {
  if (!canvas || !warpedCanvas || cssWidth < 16 || cssHeight < 16) return;
  const dpr = Math.min(2.5, Math.max(1, window.devicePixelRatio || 1));
  const pxW = Math.max(1, Math.round(cssWidth * dpr));
  const pxH = Math.max(1, Math.round(cssHeight * dpr));
  if (canvas.width !== pxW || canvas.height !== pxH) {
    canvas.width = pxW;
    canvas.height = pxH;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, pxW, pxH);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(warpedCanvas, 0, 0, pxW, pxH);
}

/**
 * Render a pure flat 90-degree straight Word document ("Ảnh văn bản") aligned 1:1 to the
 * perspective-warped paper sheet POV.
 * Returns { flatW, flatH, lineHits } so the SVG hover/selection layer lights up any line on hover!
 */
export function renderDigitalDocument(canvas, opts) {
  const {
    text = '',
    lens = null,
    paperQuad = null,
    cssWidth = 0,
    cssHeight = 0,
    sourceWidth = 1000,
    sourceHeight = 1000,
    isLight = false,
  } = opts || {};

  if (!canvas || cssWidth < 16 || cssHeight < 16) return { flatW: 0, flatH: 0, lineHits: [] };
  const dpr = Math.min(2.5, Math.max(1, window.devicePixelRatio || 1));
  const pxW = Math.max(1, Math.round(cssWidth * dpr));
  const pxH = Math.max(1, Math.round(cssHeight * dpr));
  if (canvas.width !== pxW || canvas.height !== pxH) {
    canvas.width = pxW;
    canvas.height = pxH;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return { flatW: cssWidth, flatH: cssHeight, lineHits: [] };

  ctx.save();
  ctx.scale(dpr, dpr);

  // Pure 90-degree flat crisp white Word page filling the rectified sheet area 1:1
  ctx.fillStyle = '#fcfcfa';
  ctx.fillRect(0, 0, cssWidth, cssHeight);
  ctx.strokeStyle = isLight ? 'rgba(148, 163, 184, 0.72)' : 'rgba(255, 255, 255, 0.24)';
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, cssWidth - 1, cssHeight - 1);

  const srcW = Math.max(1, Number(lens?.sourceWidth) || Number(sourceWidth) || 1);
  const srcH = Math.max(1, Number(lens?.sourceHeight) || Number(sourceHeight) || 1);
  const rawQuad = Array.isArray(paperQuad) && paperQuad.length === 4
    ? paperQuad
    : Array.isArray(lens?.paperQuad) && lens.paperQuad.length === 4
      ? lens.paperQuad
      : [[0, 0], [srcW, 0], [srcW, srcH], [0, srcH]];
  const orderedQuad = orderQuad(rawQuad) || rawQuad;
  const dstRect = [[0, 0], [cssWidth, 0], [cssWidth, cssHeight], [0, cssHeight]];
  const H = computeHomography(orderedQuad, dstRect);

  const lines = Array.isArray(lens?.lines) ? lens.lines : [];
  const editedLines = String(text ?? '').split('\n');
  const hasGeoLines = lines.length > 0 && lines.some(l => Array.isArray(l.polygon) && l.polygon.length >= 3);
  const fontStack = '"Calibri", "Segoe UI", "Roboto", system-ui, sans-serif';
  const lineHits = [];

  if (hasGeoLines) {
    // Warp every handwritten line polygon through exact Homography H into the 90-deg flat Word page!
    const metrics = [];
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (!Array.isArray(line.polygon) || line.polygon.length < 3) continue;
      const lineText = (editedLines.length === lines.length ? editedLines[i] : line.text) ?? '';
      if (!lineText.trim()) continue;
      const flatPoly = line.polygon.map(pt => projectPoint(H, pt));
      const b = polygonBounds(flatPoly);
      metrics.push({
        id: line.id ?? i + 1,
        lineText,
        rawText: line.rawText ?? lineText,
        changed: Boolean(line.changed),
        flatPoly,
        b,
        boxH: Math.max(10, b.maxY - b.minY),
      });
    }

    const sortedH = metrics.map(m => m.boxH).sort((a, b) => a - b);
    const medH = sortedH.length ? sortedH[Math.floor(sortedH.length / 2)] : 16;
    const uniformBaseSize = Math.max(10, Math.min(28, medH * 0.56));
    const padX = Math.max(8, cssWidth * 0.025);

    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#141a22';
    for (const m of metrics) {
      let fontSize = Math.max(uniformBaseSize * 0.9, Math.min(uniformBaseSize * 1.12, m.boxH * 0.6));
      ctx.font = `400 ${fontSize.toFixed(1)}px ${fontStack}`;

      const startX = Math.max(padX, Math.min(cssWidth - padX - 24, m.b.minX));
      const maxLineW = Math.max(24, cssWidth - padX - startX);
      let measured = ctx.measureText(m.lineText).width;
      if (measured > maxLineW && measured > 1) {
        fontSize = Math.max(8, fontSize * (maxLineW / measured));
        ctx.font = `400 ${fontSize.toFixed(1)}px ${fontStack}`;
        measured = ctx.measureText(m.lineText).width;
      }

      const drawY = Math.max(fontSize * 0.6, Math.min(cssHeight - fontSize * 0.6, m.b.cy));
      ctx.fillText(m.lineText, startX, drawY);

      const hitPadY = Math.max(3, fontSize * 0.24);
      const hitH = Math.max(m.boxH * 0.82, fontSize + hitPadY * 2);
      lineHits.push({
        id: m.id,
        text: m.lineText,
        rawText: m.rawText,
        changed: m.changed,
        x: Math.max(2, startX - 4),
        y: Math.max(2, drawY - hitH / 2),
        w: Math.min(cssWidth - Math.max(2, startX - 4) - 2, Math.max(measured, m.b.maxX - startX) + 8),
        h: Math.min(cssHeight - 4, hitH),
      });
    }
  } else {
    // 1-to-1 single-line Word layout (NEVER wraps a single recognized line onto 2 lines!)
    const padX = Math.max(16, cssWidth * 0.065);
    const padY = Math.max(16, cssHeight * 0.065);
    const contentW = Math.max(40, cssWidth - padX * 2);
    const availH = Math.max(40, cssHeight - padY * 2);
    const rawLines = String(text ?? '').trim()
      ? String(text).split('\n')
      : ['(Chưa có văn bản nhận dạng)'];
    const nonEmptyCount = Math.max(1, rawLines.length);

    // Choose largest uniform font size so EVERY single line fits cleanly on 1 straight horizontal line
    let fontSize = Math.min(24, Math.max(10, (availH / nonEmptyCount) * 0.54));
    for (let attempt = 0; attempt < 24; attempt++) {
      ctx.font = `400 ${fontSize.toFixed(1)}px ${fontStack}`;
      let maxW = 0;
      for (const s of rawLines) {
        const w = ctx.measureText(s).width;
        if (w > maxW) maxW = w;
      }
      const totalH = nonEmptyCount * (fontSize * 1.62);
      if (maxW <= contentW && totalH <= availH) break;
      fontSize *= 0.93;
      if (fontSize <= 8.5) break;
    }

    const lineStep = Math.min(fontSize * 1.72, availH / nonEmptyCount);
    ctx.font = `400 ${fontSize.toFixed(1)}px ${fontStack}`;
    ctx.textBaseline = 'middle';
    ctx.fillStyle = String(text ?? '').trim() ? '#141a22' : '#94a3b8';

    for (let i = 0; i < rawLines.length; i++) {
      const lineStr = rawLines[i];
      const y = padY + lineStep * (i + 0.5);
      if (y > cssHeight - padY * 0.35) break;
      if (!lineStr.trim()) continue;
      const measured = ctx.measureText(lineStr).width;
      ctx.fillText(lineStr, padX, y, contentW);
      const hitH = Math.max(fontSize * 1.35, lineStep * 0.82);
      lineHits.push({
        id: i + 1,
        text: lineStr,
        rawText: lineStr,
        changed: false,
        x: Math.max(2, padX - 5),
        y: Math.max(2, y - hitH / 2),
        w: Math.min(cssWidth - Math.max(2, padX - 5) - 2, Math.min(contentW, measured) + 10),
        h: hitH,
      });
    }
  }

  ctx.restore();
  return { flatW: cssWidth, flatH: cssHeight, lineHits };
}

/**
 * Perspective-warp and crop an HTMLImageElement tightly to a 4-point Lens quad at full high resolution.
 */
export function cropImageToQuad(imgElement, quad) {
  return warpImageQuadToFlatCanvas(imgElement, quad, 2048);
}
