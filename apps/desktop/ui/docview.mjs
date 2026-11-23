/* Digital Word-document renderer ("Ảnh văn bản") & Lens quad cropper for VietHandOCR Desktop. */
import { polygonBounds, orderQuad } from './lens.mjs';

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

function drawRoundedRect(ctx, x, y, w, h, r) {
  const rad = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + rad, y);
  ctx.lineTo(x + w - rad, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rad);
  ctx.lineTo(x + w, y + h - rad);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rad, y + h);
  ctx.lineTo(x + rad, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rad);
  ctx.lineTo(x, y + rad);
  ctx.quadraticCurveTo(x, y, x + rad, y);
  ctx.closePath();
}

function drawQuadPath(ctx, quad) {
  ctx.beginPath();
  quad.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
}

/**
 * Render a crisp Word-document visualization ("Ảnh văn bản") onto `canvas`.
 * - Matches the exact pixel frame of `#originalImage` so the Đối chiếu slider overlays 1:1.
 * - When `lens.lines` exists: renders a crisp white Word paper sheet aligned with `paperQuad`,
 *   placing every digital typed line at the exact position of its handwritten counterpart.
 * - When `lens.lines` is absent (older server or manual text): renders a clean Word A4 sheet
 *   fitted over `paperQuad` (or centered in frame) with clean wrapped Word typography.
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
    title = '',
    isLight = false,
  } = opts || {};

  if (!canvas || cssWidth < 16 || cssHeight < 16) return;
  const dpr = Math.min(2.5, Math.max(1, window.devicePixelRatio || 1));
  const pxW = Math.max(1, Math.round(cssWidth * dpr));
  const pxH = Math.max(1, Math.round(cssHeight * dpr));
  if (canvas.width !== pxW || canvas.height !== pxH) {
    canvas.width = pxW;
    canvas.height = pxH;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  ctx.save();
  ctx.scale(dpr, dpr);

  // Subtle Word-workspace backdrop behind the digital paper sheet
  const bgGrad = ctx.createLinearGradient(0, 0, cssWidth, cssHeight);
  if (isLight) {
    bgGrad.addColorStop(0, '#dde3ea');
    bgGrad.addColorStop(1, '#cfd7e0');
  } else {
    bgGrad.addColorStop(0, '#1e242c');
    bgGrad.addColorStop(1, '#14181e');
  }
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, cssWidth, cssHeight);

  const srcW = Math.max(1, Number(lens?.sourceWidth) || Number(sourceWidth) || 1);
  const srcH = Math.max(1, Number(lens?.sourceHeight) || Number(sourceHeight) || 1);
  const sx = cssWidth / srcW;
  const sy = cssHeight / srcH;

  const rawQuad = Array.isArray(paperQuad) && paperQuad.length === 4
    ? paperQuad
    : Array.isArray(lens?.paperQuad) && lens.paperQuad.length === 4
      ? lens.paperQuad
      : null;

  // Map paper quad into CSS pixel space (or build a crisp centered Word page sheet)
  let sheetQuad = null;
  let sheetRect = null;
  if (rawQuad) {
    const ordered = orderQuad(rawQuad) || rawQuad;
    sheetQuad = ordered.map(([x, y]) => [x * sx, y * sy]);
    const b = polygonBounds(sheetQuad);
    sheetRect = { x: b.minX, y: b.minY, w: Math.max(40, b.maxX - b.minX), h: Math.max(40, b.maxY - b.minY) };
  } else {
    const marginX = Math.max(12, cssWidth * 0.06);
    const marginY = Math.max(12, cssHeight * 0.05);
    sheetRect = {
      x: marginX,
      y: marginY,
      w: Math.max(60, cssWidth - marginX * 2),
      h: Math.max(60, cssHeight - marginY * 2),
    };
  }

  // Draw crisp white Word paper sheet with realistic page elevation shadow
  ctx.save();
  ctx.shadowColor = isLight ? 'rgba(15, 23, 42, 0.18)' : 'rgba(0, 0, 0, 0.55)';
  ctx.shadowBlur = 18;
  ctx.shadowOffsetY = 5;
  ctx.fillStyle = '#fcfcfa';
  if (sheetQuad) {
    drawQuadPath(ctx, sheetQuad);
    ctx.fill();
  } else {
    drawRoundedRect(ctx, sheetRect.x, sheetRect.y, sheetRect.w, sheetRect.h, 5);
    ctx.fill();
  }
  ctx.restore();

  // Crisp page border
  ctx.save();
  ctx.strokeStyle = isLight ? 'rgba(148, 163, 184, 0.7)' : 'rgba(255, 255, 255, 0.22)';
  ctx.lineWidth = 1;
  if (sheetQuad) {
    drawQuadPath(ctx, sheetQuad);
    ctx.stroke();
    ctx.clip();
  } else {
    drawRoundedRect(ctx, sheetRect.x, sheetRect.y, sheetRect.w, sheetRect.h, 5);
    ctx.stroke();
    ctx.clip();
  }

  const lines = Array.isArray(lens?.lines) ? lens.lines : [];
  const editedLines = String(text ?? '').split('\n');
  const hasGeoLines = lines.length > 0 && lines.some(l => Array.isArray(l.polygon) && l.polygon.length >= 3);

  const fontStack = '"Calibri", "Segoe UI", "Roboto", system-ui, sans-serif';
  ctx.fillStyle = '#151b23';
  ctx.textBaseline = 'middle';

function paperEdgeXAtY(a, b, y) {
  const dy = b[1] - a[1];
  if (Math.abs(dy) < 1e-3) return Math.min(a[0], b[0]);
  const t = Math.max(0, Math.min(1, (y - a[1]) / dy));
  return a[0] + (b[0] - a[0]) * t;
}

  if (hasGeoLines) {
    // Compute a uniform Word document base font size from the median line height
    const lineMetrics = [];
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (!Array.isArray(line.polygon) || line.polygon.length < 3) continue;
      const lineText = (editedLines.length === lines.length ? editedLines[i] : line.text) ?? '';
      if (!lineText.trim()) continue;
      const polyCss = line.polygon.map(([x, y]) => [x * sx, y * sy]);
      const b = polygonBounds(polyCss);
      lineMetrics.push({ lineText, polyCss, b, boxH: Math.max(10, b.maxY - b.minY) });
    }
    const sortedH = lineMetrics.map(m => m.boxH).sort((a, b) => a - b);
    const medH = sortedH.length ? sortedH[Math.floor(sortedH.length / 2)] : 16;
    const uniformBaseSize = Math.max(9.5, Math.min(24, medH * 0.56));
    const rightPad = Math.max(10, sheetRect.w * 0.04);

    // 1:1 aligned digital Word text placed directly over each handwritten line's coordinates
    for (const { lineText, polyCss, b, boxH } of lineMetrics) {
      const angle = estimateLineAngle(polyCss);
      // Keep typography uniform like a real Word document (allow only gentle +-12% local fit)
      let fontSize = Math.max(uniformBaseSize * 0.9, Math.min(uniformBaseSize * 1.12, boxH * 0.6));
      ctx.font = `400 ${fontSize.toFixed(1)}px ${fontStack}`;

      const rightEdge = sheetQuad
        ? paperEdgeXAtY(sheetQuad[1], sheetQuad[2], b.cy)
        : sheetRect.x + sheetRect.w;
      const leftEdge = sheetQuad
        ? paperEdgeXAtY(sheetQuad[0], sheetQuad[3], b.cy)
        : sheetRect.x;
      const startX = Math.max(leftEdge + rightPad * 0.7, b.minX);
      const maxLineW = Math.max(32, rightEdge - rightPad - startX);
      const measured = ctx.measureText(lineText).width;
      if (measured > maxLineW && measured > 1) {
        fontSize = Math.max(8, fontSize * (maxLineW / measured));
        ctx.font = `400 ${fontSize.toFixed(1)}px ${fontStack}`;
      }

      ctx.save();
      ctx.translate(startX, b.cy);
      if (Math.abs(angle) > 0.005) ctx.rotate(angle);
      ctx.fillStyle = '#141a22';
      ctx.fillText(lineText, 0, 0);
      ctx.restore();
    }
  } else {
    // Clean Microsoft Word A4 layout when line polygons are unavailable
    const padX = Math.max(14, sheetRect.w * 0.075);
    const padTop = Math.max(14, sheetRect.h * 0.065);
    const padBot = Math.max(12, sheetRect.h * 0.055);
    const contentW = Math.max(40, sheetRect.w - padX * 2);

    const paragraphs = String(text ?? '').trim() ? String(text).split('\n') : ['(Chưa có văn bản nhận dạng)'];
    const textStartY = sheetRect.y + padTop;
    const availH = Math.max(30, sheetRect.y + sheetRect.h - padBot - textStartY);

    // Auto-scale Word font size so all paragraphs fit neatly inside the paper sheet
    let fontSize = Math.max(10.5, Math.min(17.5, sheetRect.w * 0.042));
    let wrapped = [];
    let lineH = fontSize * 1.48;
    for (let attempt = 0; attempt < 16; attempt++) {
      ctx.font = `400 ${fontSize.toFixed(1)}px ${fontStack}`;
      wrapped = [];
      for (const p of paragraphs) {
        wrapped.push(...wrapParagraph(ctx, p, contentW));
      }
      lineH = fontSize * 1.46;
      if (wrapped.length * lineH <= availH || fontSize <= 8.5) break;
      fontSize *= 0.91;
    }

    ctx.textBaseline = 'top';
    ctx.fillStyle = String(text ?? '').trim() ? '#141a22' : '#94a3b8';
    ctx.font = `400 ${fontSize.toFixed(1)}px ${fontStack}`;
    let y = textStartY;
    for (const lineStr of wrapped) {
      if (y + lineH > sheetRect.y + sheetRect.h - padBot * 0.4) break;
      ctx.fillText(lineStr, sheetRect.x + padX, y);
      y += lineH;
    }
  }

  ctx.restore();
  ctx.restore();
}

/**
 * Crop an HTMLImageElement tightly to a 4-point Lens quad (axis-aligned bounding box clipped to quad
 * with clean white background outside the quad, preserving full original resolution).
 */
export function cropImageToQuad(imgElement, quad) {
  const natW = imgElement?.naturalWidth || 0;
  const natH = imgElement?.naturalHeight || 0;
  if (!natW || !natH || !Array.isArray(quad) || quad.length !== 4) return null;
  const ordered = orderQuad(quad) || quad;
  const b = polygonBounds(ordered);
  const l = Math.max(0, Math.floor(b.minX));
  const t = Math.max(0, Math.floor(b.minY));
  const r = Math.min(natW, Math.ceil(b.maxX));
  const bt = Math.min(natH, Math.ceil(b.maxY));
  const w = Math.max(16, r - l);
  const h = Math.max(16, bt - t);

  const out = document.createElement('canvas');
  out.width = w;
  out.height = h;
  const ctx = out.getContext('2d');
  if (!ctx) return null;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, w, h);
  ctx.save();
  ctx.beginPath();
  ordered.forEach(([x, y], i) => (i ? ctx.lineTo(x - l, y - t) : ctx.moveTo(x - l, y - t)));
  ctx.closePath();
  ctx.clip();
  ctx.drawImage(imgElement, -l, -t);
  ctx.restore();
  return out;
}
