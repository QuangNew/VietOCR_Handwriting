import test from 'node:test';
import assert from 'node:assert/strict';
import {
  computeContainedRect,
  orderQuad,
  buildCornerBracketPaths,
  expandPolygon,
  polygonBounds,
  quadScrimPath,
} from '../ui/lens.mjs';
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
