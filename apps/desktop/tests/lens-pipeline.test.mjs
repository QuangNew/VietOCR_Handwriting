import test from 'node:test';
import assert from 'node:assert/strict';
import {
  computeContainedRect,
  orderQuad,
  buildCornerBracketPaths,
  expandPolygon,
  polygonBounds,
  quadScrimPath,
  pointInPolygon,
  linesInsideQuad,
  tightenLinePolygons,
  detectPaperQuadFromRgba,
} from '../ui/lens.mjs';
import {
  wrapParagraph,
  estimateLineAngle,
  computeQuadFlatSize,
  computeHomography,
  projectPoint,
  tightenFlatLineHits,
} from '../ui/docview.mjs';
import {
  formatMs,
  routeLabel,
  translateReason,
  diffWords,
  computeTimingShares,
} from '../ui/pipeline.mjs';

test('computeContainedRect centers image with exact aspect ratio', () => {
  const r = computeContainedRect(800, 600, 1920, 1080);
  assert.equal(Math.round(r.width), 800);
  assert.equal(Math.round(r.height), 450);
  assert.equal(Math.round(r.left), 0);
  assert.equal(Math.round(r.top), 75);
});

test('orderQuad orders scrambled corners as TL, TR, BR, BL', () => {
  const ordered = orderQuad([
    [500, 400],
    [100, 80],
    [110, 410],
    [490, 90],
  ]);
  assert.deepEqual(ordered, [
    [100, 80],
    [490, 90],
    [500, 400],
    [110, 410],
  ]);
});

test('buildCornerBracketPaths and quadScrimPath generate valid SVG paths', () => {
  const quad = [[100, 80], [500, 80], [500, 400], [100, 400]];
  const brackets = buildCornerBracketPaths(quad, 40, 12);
  assert.equal(brackets.length, 4);
  for (const d of brackets) {
    assert.match(d, /^M .+ L .+ Q .+ L .+$/);
  }
  const scrim = quadScrimPath(600, 500, quad);
  assert.ok(scrim.startsWith('M 0 0 H 600 V 500 H 0 Z M 100.0 80.0'));
});

test('expandPolygon pushes vertices outward around centroid', () => {
  const poly = [[10, 10], [110, 10], [110, 40], [10, 40]];
  const out = expandPolygon(poly, 5);
  const before = polygonBounds(poly);
  const after = polygonBounds(out);
  assert.ok(after.minX < before.minX && after.maxX > before.maxX);
  assert.ok(after.minY < before.minY && after.maxY > before.maxY);
});

test('diffWords highlights Vietnamese OCR corrections cleanly', () => {
  const segs = diffWords('Chợt hai thầy trò phát hiên ra', 'Chợt hai thầy trò phát hiện ra');
  assert.deepEqual(segs, [
    { type: 'eq', text: 'Chợt hai thầy trò phát' },
    { type: 'del', text: 'hiên' },
    { type: 'ins', text: 'hiện' },
    { type: 'eq', text: 'ra' },
  ]);
});

test('timing shares and Vietnamese labels format cleanly', () => {
  assert.equal(formatMs(124.6), '125 ms');
  assert.equal(formatMs(1850), '1.85 s');
  assert.match(routeLabel('scanner'), /Scanner/);
  assert.match(translateReason('outside_paper'), /giấy/);
  const shares = computeTimingShares({ preprocessMs: 100, segmentMs: 200, recognitionMs: 500, correctionMs: 200 });
  assert.equal(shares.preprocessPct, 10);
  assert.equal(shares.segmentPct, 20);
  assert.equal(shares.recognitionPct, 50);
  assert.equal(shares.correctionPct, 20);
});

test('detectPaperQuadFromRgba isolates cool paper sheet and rejects warm wood glare', () => {
  const w = 160, h = 100;
  const rgba = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      // Default warm wooden desk [145, 118, 90]
      let r = 145, g = 118, b = 90;
      // Specular warm glare patch on bottom-right desk [186, 174, 150]
      if (x >= 115 && y >= 65) { r = 186; g = 174; b = 150; }
      // White-cool paper sheet at x=[40..112], y=[16..84] with dark handwriting lines
      if (x >= 40 && x <= 112 && y >= 16 && y <= 84) {
        r = 196; g = 208; b = 216;
        if (y % 12 === 0 && x >= 48 && x <= 104) { r = 45; g = 60; b = 110; }
      }
      rgba[i] = r; rgba[i + 1] = g; rgba[i + 2] = b; rgba[i + 3] = 255;
    }
  }
  const det = detectPaperQuadFromRgba(rgba, w, h, 1600, 1000);
  assert.ok(det && det.paperDetected && det.paperQuad.length === 4);
  const pb = polygonBounds(det.paperQuad);
  assert.ok(pb.minX >= 340 && pb.minX <= 430, `minX=${pb.minX}`);
  assert.ok(pb.maxX >= 1090 && pb.maxX <= 1185, `maxX=${pb.maxX} (must exclude desk glare at 1150..1600)`);
  assert.ok(pb.minY >= 120 && pb.minY <= 190, `minY=${pb.minY}`);
  assert.ok(pb.maxY >= 810 && pb.maxY <= 890, `maxY=${pb.maxY}`);
});

test('pointInPolygon and linesInsideQuad filter lines inside adjusted Lens quad', () => {
  const quad = [[100, 100], [500, 100], [500, 300], [100, 300]];
  assert.equal(pointInPolygon(250, 200, quad), true);
  assert.equal(pointInPolygon(50, 200, quad), false);
  const lines = [
    { id: 1, text: 'Dòng trong khung', polygon: [[120, 140], [420, 140], [420, 180], [120, 180]] },
    { id: 2, text: 'Dòng ngoài khung', polygon: [[120, 360], [420, 360], [420, 400], [120, 400]] },
  ];
  const inside = linesInsideQuad(lines, quad);
  assert.deepEqual(inside.map(l => l.id), [1]);
});

test('docview wrapParagraph and estimateLineAngle work deterministically', () => {
  const fakeCtx = { measureText: s => ({ width: s.length * 10 }) };
  const wrapped = wrapParagraph(fakeCtx, 'Một hai ba bốn năm sáu', 110);
  assert.deepEqual(wrapped, ['Một hai ba', 'bốn năm sáu']);
  const flat = estimateLineAngle([[0, 100], [200, 100], [200, 130], [0, 130]]);
  assert.equal(flat, 0);
  const steep = estimateLineAngle([[0, 0], [100, 100], [80, 120], [-20, 20]]);
  assert.ok(Math.abs(steep - (12 * Math.PI) / 180) < 1e-6, 'angle clamped to +12 deg');
});

test('computeHomography and computeQuadFlatSize rectify tilted paper to exact 90-deg flat sheet', () => {
  const tilted = [[270, 50], [1470, 82], [1430, 926], [230, 894]];
  const flat = computeQuadFlatSize(tilted, 1920, 1080);
  assert.equal(flat.orientation, 'landscape');
  assert.ok(flat.width >= 1180 && flat.width <= 1220, `flatW=${flat.width}`);
  assert.ok(flat.height >= 830 && flat.height <= 860, `flatH=${flat.height}`);
  const dst = [[0, 0], [flat.width, 0], [flat.width, flat.height], [0, flat.height]];
  const H = computeHomography(tilted, dst);
  for (let i = 0; i < 4; i++) {
    const p = projectPoint(H, tilted[i]);
    assert.ok(Math.abs(p[0] - dst[i][0]) < 1e-4 && Math.abs(p[1] - dst[i][1]) < 1e-4);
  }
});

test('tightenLinePolygons and tightenFlatLineHits eliminate vertical bleed across overlapping lines', () => {
  // Real coordinates from 902437440 where raw axis-aligned line boxes were 104-118px tall while pitch was 52-65px
  const rawLines = [
    { id: 1, polygon: [[594.5, 510.5], [1500.5, 510.5], [1500.5, 619.5], [594.5, 619.5]] },
    { id: 2, polygon: [[587.5, 578.5], [1472.5, 578.5], [1472.5, 682.5], [587.5, 682.5]] },
    { id: 3, polygon: [[583.5, 630.5], [1481.5, 630.5], [1481.5, 748.5], [583.5, 748.5]] },
    { id: 4, polygon: [[577.5, 687.5], [1513.5, 687.5], [1513.5, 795.5], [577.5, 795.5]] },
  ];
  const tight = tightenLinePolygons(rawLines);
  for (let i = 1; i <= 3; i++) {
    const a = polygonBounds(tight.get(i));
    const b = polygonBounds(tight.get(i + 1));
    assert.ok(a.maxY < b.minY, `Lens poly #${i} bottom (${a.maxY}) must stay strictly above #${i + 1} top (${b.minY})`);
  }

  const hits = tightenFlatLineHits(
    rawLines.map((l, idx) => {
      const b = polygonBounds(l.polygon);
      return {
        id: idx + 1,
        lineText: `Line ${idx + 1}`,
        rawText: `Line ${idx + 1}`,
        changed: false,
        x1: 20,
        x2: 500,
        w: 480,
        drawY: (b.cy - 475) * 0.8,
        boxH: (b.maxY - b.minY) * 0.8,
        fontSize: 18,
      };
    }),
    540,
    460,
  );
  for (let i = 0; i < hits.length - 1; i++) {
    assert.ok(
      hits[i].y + hits[i].h < hits[i + 1].y,
      `Flat hit #${i + 1} bottom (${hits[i].y + hits[i].h}) must stay strictly above #${i + 2} top (${hits[i + 1].y})`,
    );
  }
});
