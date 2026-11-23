/* Pure helpers for the 5-stage VietHandOCR visual Pipeline Demo (diffing, timings, labels). */

export function formatMs(ms) {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return '—';
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

export function routeLabel(route) {
  if (route === 'scanner') return 'Scanner (Ảnh chụp · Nền phức tạp)';
  if (route === 'legacy') return 'Legacy (Trang sạch / Đã cắt)';
  return route || 'Tự động';
}

const REASON_LABELS = {
  outside_paper: 'Phát hiện nền ngoài trang giấy',
  uneven_lighting: 'Ánh sáng / bóng đổ không đều',
  coherent_skew: 'Dòng chữ bị nghiêng góc',
  background_and_alignment_within_limits: 'Nền sạch và thẳng hàng — bỏ qua khử nền nặng',
  requested_scanner: 'Chế độ Scanner',
  requested_legacy: 'Chế độ Legacy',
};

export function translateReason(reason) {
  return REASON_LABELS[reason] || reason;
}

/**
 * Word-level LCS diff between raw ML_s44 line and BARTpho-corrected line.
 * Returns array of segments: { type: 'eq' | 'del' | 'ins', text: string }.
 */
export function diffWords(raw, fixed) {
  const a = String(raw || '').trim().split(/\s+/).filter(Boolean);
  const b = String(fixed || '').trim().split(/\s+/).filter(Boolean);
  if (!a.length && !b.length) return [];
  if (raw === fixed) return [{ type: 'eq', text: fixed || '' }];

  const m = a.length;
  const n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Uint16Array(n + 1));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (a[i] === b[j]) dp[i][j] = dp[i + 1][j + 1] + 1;
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const ops = [];
  let i = 0, j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      ops.push({ type: 'eq', text: a[i] });
      i++; j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: 'del', text: a[i++] });
    } else {
      ops.push({ type: 'ins', text: b[j++] });
    }
  }
  while (i < m) ops.push({ type: 'del', text: a[i++] });
  while (j < n) ops.push({ type: 'ins', text: b[j++] });

  // Merge consecutive tokens of same type
  const merged = [];
  for (const op of ops) {
    const last = merged.at(-1);
    if (last && last.type === op.type) last.text += ' ' + op.text;
    else merged.push({ ...op });
  }
  return merged;
}

export function computeTimingShares(timings = {}) {
  const pre = Math.max(0, Number(timings.preprocessMs) || 0);
  const seg = Math.max(0, Number(timings.segmentMs) || 0);
  const rec = Math.max(0, Number(timings.recognitionMs) || 0);
  const cor = Math.max(0, Number(timings.correctionMs) || 0);
  const sum = Math.max(1, pre + seg + rec + cor);
  return {
    preprocessPct: Math.round((pre / sum) * 1000) / 10,
    segmentPct: Math.round((seg / sum) * 1000) / 10,
    recognitionPct: Math.round((rec / sum) * 1000) / 10,
    correctionPct: Math.round((cor / sum) * 1000) / 10,
    totalMeasuredMs: pre + seg + rec + cor,
  };
}

export const LINE_COLORS = [
  '#72cfff', '#a6e38a', '#f7c873', '#f49393', '#c8a2ff',
  '#6ee7b7', '#fda4af', '#93c5fd', '#fcd34d', '#d8b4fe',
];
