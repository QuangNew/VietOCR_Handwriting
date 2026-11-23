import { outline, bounds, detectSelfClose, finalizeFreehand, dist } from './editor.mjs';
import {
  computeContainedRect,
  buildCornerBracketPaths,
  expandPolygon,
  polygonBounds,
  quadScrimPath,
  detectPaperQuadFromImage,
  orderQuad,
  linesInsideQuad,
} from './lens.mjs';
import {
  renderDigitalDocument,
  cropImageToQuad,
  computeQuadFlatSize,
  warpImageQuadToFlatCanvas,
  drawRectifiedPhoto,
} from './docview.mjs';
import {
  formatMs,
  routeLabel,
  translateReason,
  diffWords,
  computeTimingShares,
  LINE_COLORS,
} from './pipeline.mjs';

const $ = id => document.getElementById(id);
const invoke = (name, args = {}) =>
  window.__TAURI__?.core.invoke(name, args) ??
  Promise.reject(Error('Mở ứng dụng Tauri để sử dụng chức năng này.'));
const channel = handler => {
  const c = new window.__TAURI__.core.Channel();
  c.onmessage = handler;
  return c;
};

let drafts = [];
let selected = null;
let config = null;
let verified = false;
let verifiedInfo = null;
let isDebug = false;
let busy = false;
let liveURL = null;
let reviewTimer = null;
let editorSource = null;
let points = [];
let freehandClosed = false;
let freehandNearStart = false;
let freehandError = '';
let drawing = false;
let textTimer = null;
let toastTimer = null;
let transferTimer = null;
let userId = null;
let accountEpoch = 0;

const runningResults = new Map();
const transferRows = new Map();
const operations = new Map();
const thumbCache = new Map();
const thumbLoading = new Set();
const clientPaperCache = new Map();
const customPaperQuads = new Map();
const pipelineCache = new Map();
const lensSelectedLines = new Set();
let lensEnabled = localStorage.getItem('viethandocr.lensEnabled') !== '0';
let demoPipelineMode = localStorage.getItem('viethandocr.demoPipeline') === '1';
let imageViewMode = 'original'; // 'original' | 'digital' | 'compare'
let compareSplit = 50; // 0..100: left 0..X% = Ảnh văn bản, right X..100% = Ảnh gốc
let compareDragging = false;
let lensHoveredLine = null;
let activeDigitalLineHits = [];
let activeFlatRect = null;
let pendingPipelineOpenDraftId = null;
let lensDragging = false;
let lensDragDidMove = false;
let lensDragAction = 'add';
let lensHandleDrag = null;
const autoSendQueue = [];
let autoSendWorkers = 0;
let pipeViewMode = 'overview';
let pipeActiveStep = 0;
let pipeAutoTimer = null;
let activePipelineData = null;
let activePipelineDraft = null;
const sendableStates = ['draft', 'awaiting_upload', 'upload_granted', 'uploading', 'cancelled', 'succeeded', 'failed', 'expired'];
const terminalStates = ['succeeded', 'failed', 'cancelled', 'expired'];
let transfersCollapsed = false;
let stoppingAll = false;

const label = state =>
({
  draft: 'Bản nháp',
  awaiting_upload: 'Chờ lượt gửi',
  upload_granted: 'Được phép gửi',
  uploading: 'Đang gửi',
  queued: 'Chờ worker',
  running: 'Đang đọc chữ',
  succeeded: 'Hoàn tất',
  failed: 'Không nhận diện được',
  cancelled: 'Đã dừng',
  cancel_pending: 'Đang dừng…',
  expired: 'Đã hết hạn',
}[state] ?? state);

function sanitizeError(e) {
  const text = String(e ?? '');
  if (/result_expired|intent_expired|HTTP 410/i.test(text)) {
    return '';
  }
  return text;
}

function toast(text) {
  const cleaned = sanitizeError(text);
  if (!cleaned) return;
  $('toast').textContent = cleaned;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($('toast').hidden = true), 5000);
}

function fail(e) {
  const text = sanitizeError(e);
  if (!text) return;
  $('message').textContent = text;
  toast(text);
  invoke('record_log', { message: text }).catch(() => { });
}

async function run(action) {
  try {
    return await action();
  } catch (e) {
    fail(e);
    return null;
  }
}

/* ---------- Local sent history metadata cache (name + sentAt + latest text) ---------- */
function historyMetaKey() {
  return `viethandocr.historyMeta.${userId || 'anon'}`;
}
function loadHistoryMeta() {
  try {
    return JSON.parse(localStorage.getItem(historyMetaKey()) || '{}') || {};
  } catch {
    return {};
  }
}
function saveHistoryMeta(entry) {
  if (!entry || (!entry.jobId && !entry.sha256)) return;
  const map = loadHistoryMeta();
  const keys = Object.keys(map);
  if (keys.length > 140) {
    for (const k of keys.slice(0, keys.length - 100)) delete map[k];
  }
  const merge = existing => ({
    name: entry.name || existing?.name || '',
    sentAt: entry.sentAt || existing?.sentAt || new Date().toISOString(),
    text: entry.text !== undefined && entry.text !== '' ? entry.text : existing?.text || '',
    state: entry.state || existing?.state || '',
    thumb: entry.thumb || existing?.thumb || '',
  });
  if (entry.jobId) map[`job:${entry.jobId}`] = merge(map[`job:${entry.jobId}`]);
  if (entry.sha256) map[`sha:${entry.sha256}`] = merge(map[`sha:${entry.sha256}`]);
  try {
    localStorage.setItem(historyMetaKey(), JSON.stringify(map));
  } catch {
    // If localStorage is tight, retry without thumbnails
    for (const k of Object.keys(map)) {
      if (map[k]?.thumb) map[k].thumb = '';
    }
    try {
      localStorage.setItem(historyMetaKey(), JSON.stringify(map));
    } catch {
      /* ignore */
    }
  }
}
async function makeMiniThumb(dataUrl) {
  if (!dataUrl) return '';
  try {
    const img = new Image();
    img.src = dataUrl;
    await img.decode();
    const maxW = 96, maxH = 72;
    const s = Math.min(maxW / Math.max(1, img.naturalWidth), maxH / Math.max(1, img.naturalHeight), 1);
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(img.naturalWidth * s));
    c.height = Math.max(1, Math.round(img.naturalHeight * s));
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.65);
  } catch {
    return '';
  }
}
function recordDraftHistory(d) {
  if (!d) return;
  if (d.jobId || d.state === 'succeeded') {
    saveHistoryMeta({
      jobId: d.jobId,
      sha256: d.sha256,
      name: d.name,
      text: d.text,
      state: d.state,
    });
    const fullUrl = thumbCache.get(d.id);
    if (fullUrl) {
      makeMiniThumb(fullUrl).then(thumb => {
        if (thumb) saveHistoryMeta({ jobId: d.jobId, sha256: d.sha256, thumb });
      });
    }
  }
}

/* ---------- Sidebar auto-hide ("Giữ" / "Ẩn đi" after 2s mouse leave) ---------- */
const sidebar = $('sidebar');
const revealBtn = $('sidebarReveal');
let sidebarMode = localStorage.getItem('viethandocr.sidebarMode') === 'hide' ? 'hide' : 'stay';
let sidebarHideTimer = null;
let resizingSidebar = false;

function anyDialogOpen() {
  return Boolean(document.querySelector('dialog[open]'));
}
function cancelSidebarHide() {
  clearTimeout(sidebarHideTimer);
  sidebarHideTimer = null;
}
function showSidebar() {
  cancelSidebarHide();
  sidebar.classList.remove('collapsed');
  revealBtn.hidden = true;
}
function hideSidebarNow() {
  if (sidebarMode !== 'hide' || resizingSidebar || anyDialogOpen()) return;
  closeAllPopMenus();
  sidebar.classList.add('collapsed');
  revealBtn.hidden = false;
}
function scheduleSidebarHide() {
  cancelSidebarHide();
  if (sidebarMode !== 'hide' || resizingSidebar || anyDialogOpen()) return;
  sidebarHideTimer = setTimeout(hideSidebarNow, 2000);
}
function applySidebarMode(mode) {
  sidebarMode = mode === 'hide' ? 'hide' : 'stay';
  localStorage.setItem('viethandocr.sidebarMode', sidebarMode);
  $('pinStay').classList.toggle('active', sidebarMode === 'stay');
  $('pinHide').classList.toggle('active', sidebarMode === 'hide');
  if (sidebarMode === 'stay') {
    showSidebar();
  } else {
    scheduleSidebarHide();
  }
}
$('pinStay').onclick = () => applySidebarMode('stay');
$('pinHide').onclick = () => applySidebarMode('hide');
sidebar.addEventListener('mouseenter', showSidebar);
sidebar.addEventListener('mouseleave', scheduleSidebarHide);
revealBtn.addEventListener('mouseenter', showSidebar);
revealBtn.addEventListener('click', showSidebar);
applySidebarMode(sidebarMode);

/* ---------- Account limit display ---------- */
function renderAccountLimit() {
  const acct = verifiedInfo?.account;
  if (acct && typeof acct.dailyLimit === 'number') {
    const used = acct.usedToday ?? 0;
    const rpm = acct.ratePerMinute ?? 30;
    $('accountLimit').textContent = `Hạn mức: ${used}/${acct.dailyLimit} ảnh · ${rpm}/phút`;
  } else {
    $('accountLimit').textContent = verified ? 'Hạn mức: đang cập nhật' : 'Hạn mức: Offline';
  }
}
async function refreshSessionQuota() {
  if (!verified) return;
  try {
    const info = await invoke('session_status');
    if (info) {
      verifiedInfo = info;
      renderAccountLimit();
    }
  } catch {
    /* keep existing display */
  }
}

/* ---------- Thumbnails & Draft Grid ---------- */
function isRemovable(d) {
  if (!d) return false;
  if (!terminalStates.includes(d.state) && d.state !== 'draft') return false;
  const op = operations.get(d.id);
  return !(op && !op.finished);
}

function ensureThumb(id) {
  if (thumbCache.has(id) || thumbLoading.has(id)) return;
  thumbLoading.add(id);
  const epoch = accountEpoch;
  invoke('draft_image', { id })
    .then(url => {
      if (epoch !== accountEpoch || !url) return;
      thumbCache.set(id, url);
      for (const img of document.querySelectorAll(`img[data-thumb-id="${id}"]`)) {
        img.src = url;
        img.hidden = false;
        const ph = img.parentElement?.querySelector('.draft-thumb-placeholder');
        if (ph) ph.hidden = true;
      }
    })
    .catch(() => { })
    .finally(() => thumbLoading.delete(id));
}

function patch(d) {
  if (!userId || d.ownerId !== userId) return;
  const i = drafts.findIndex(x => x.id === d.id);
  if (i < 0) drafts.push(d);
  else drafts[i] = d;
  recordDraftHistory(d);
  renderList();
}

function renderList() {
  $('count').textContent = drafts.length;
  $('drafts').replaceChildren();

  for (const [d, i] of drafts.map((d, i) => [d, i])) {
    const card = document.createElement('div');
    card.className = `draft-row ${selected === d.id ? 'active' : ''}`;

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = d.included !== false;
    checkbox.disabled = busy;
    checkbox.setAttribute('aria-label', `Gửi ${d.name}`);
    checkbox.onclick = e => e.stopPropagation();
    checkbox.onchange = () =>
      run(async () => {
        patch(await invoke('set_included', { id: d.id, included: checkbox.checked }));
      });

    const num = document.createElement('span');
    num.className = 'draft-number';
    num.textContent = String(i + 1).padStart(2, '0');

    const thumbBtn = document.createElement('button');
    thumbBtn.type = 'button';
    thumbBtn.className = 'draft-thumb-wrap';
    thumbBtn.title = d.name;
    const img = document.createElement('img');
    img.dataset.thumbId = d.id;
    img.alt = d.name;
    const ph = document.createElement('span');
    ph.className = 'draft-thumb-placeholder';
    ph.textContent = '…';
    if (thumbCache.has(d.id)) {
      img.src = thumbCache.get(d.id);
      img.hidden = false;
      ph.hidden = true;
    } else {
      img.hidden = true;
      ensureThumb(d.id);
    }
    thumbBtn.append(img, ph);
    thumbBtn.onclick = () => run(() => select(d.id));

    const block = document.createElement('button');
    block.type = 'button';
    block.className = 'draft-name';
    const title = document.createElement('strong');
    title.textContent = d.name;
    title.title = d.name;
    const hint = document.createElement('small');
    hint.textContent = label(d.state);
    block.append(title, hint);
    block.onclick = () => run(() => select(d.id));

    card.append(checkbox, num, thumbBtn, block);
    $('drafts').append(card);
  }

  const current = drafts.find(x => x.id === selected);
  $('jobState').textContent = current ? label(current.state) : 'Chưa gửi';
  const sendable = drafts.filter(d => {
    if (d.included === false || !sendableStates.includes(d.state)) return false;
    const op = operations.get(d.id);
    return !(op && !op.finished);
  });
  $('send').disabled = busy || !verified || !sendable.length;
  $('send').textContent = `Gửi ${sendable.length} ảnh →`;
  $('downloadMenuBtn').disabled = !drafts.length;
  $('clearMenuBtn').disabled = !drafts.some(isRemovable);
  $('dlCurrent').disabled = !current;
  $('dlAll').disabled = !drafts.length;
  $('dlPick').disabled = !drafts.length;
  $('clearCurrent').disabled = !isRemovable(current);
  $('clearAll').disabled = !drafts.some(isRemovable);
  $('clearPick').disabled = !drafts.some(isRemovable);
  $('historyButton').disabled = !verified;
  $('lensToggleBtn').hidden = !current || imageViewMode !== 'original';
  $('editImageBtn').hidden = !current;
  $('pipelineBtn').hidden = !(current && (current.state === 'succeeded' || current.hasPipeline || demoPipelineMode));
  $('pipelineBtn').disabled = !current || current.state !== 'succeeded';
  $('pipelineBtn').classList.toggle('pulse-ready', Boolean(demoPipelineMode && current?.state === 'succeeded'));
  $('text').disabled = !!current && ['queued', 'running', 'cancel_pending'].includes(current.state);
  syncViewModeButtons(current);
  renderPipelineMiniBar();
}

async function select(id) {
  selected = id;
  lensSelectedLines.clear();
  lensHoveredLine = null;
  renderList();
  const d = drafts.find(x => x.id === id);
  $('text').value = d?.text ?? '';
  countText();
  if (!d) {
    $('originalImage').hidden = true;
    $('originalStage').hidden = true;
    $('originalImage').removeAttribute('src');
    $('rectifiedLayer').hidden = true;
    $('digitalLayer').hidden = true;
    $('digitalHoverSvg').style.display = 'none';
    $('compareOverlay').hidden = true;
    $('lensSvg').style.display = 'none';
    $('lensFloatingBar').hidden = true;
    $('lensTooltip').hidden = true;
    $('emptyImage').hidden = false;
    $('imageInfo').textContent = 'Bản nháp riêng';
    syncViewModeButtons(null);
    renderPipelineMiniBar();
    return;
  }
  const url = thumbCache.get(id) ?? (await invoke('draft_image', { id }));
  if (url) thumbCache.set(id, url);
  if (selected !== id) return;
  $('originalImage').hidden = false;
  const img = $('originalImage');
  $('originalStage').hidden = false;
  $('emptyImage').hidden = true;
  $('imageInfo').textContent = `${d.width && d.height ? `${d.width} × ${d.height} px · ` : ''}${(d.imageBytes / 1024).toFixed(0)} KiB · ${d.mediaType.replace('image/', '').toUpperCase()}`;
  const afterImageReady = () => {
    if (selected !== id) return;
    if (!d.lens && !clientPaperCache.has(id)) {
      const detected = detectPaperQuadFromImage(img);
      if (detected) clientPaperCache.set(id, detected);
    }
    syncViewModeButtons(d);
    renderImageStage();
  };
  img.onload = afterImageReady;
  img.src = url;
  if (img.complete && img.naturalWidth > 0) afterImageReady();
  if (demoPipelineMode && d.state === 'succeeded' && d.jobId) {
    void prefetchPipeline(d);
  }
  renderPipelineMiniBar();
}

async function boot() {
  const data = await invoke('bootstrap');
  config = data.config;
  drafts = data.drafts;
  verified = !!data.verified;
  verifiedInfo = data.verified || null;
  isDebug = Boolean(data.isDebug) || new URLSearchParams(location.search).get('dev') === '1';
  userId = data.session?.userId ?? null;

  $('logsButton').hidden = !isDebug;
  $('email').textContent = data.session?.email ?? 'Chưa đăng nhập Google';
  renderAccountLimit();
  $('connection').textContent = verified
    ? 'Raspberry đã xác minh'
    : data.session
      ? 'Offline · bản nháp được giữ'
      : 'Chưa xác minh Raspberry';
  $('connectionDot').classList.toggle('connected', verified);
  $('authGate').hidden = !!data.session && !!(verified || data.workspaceAllowed);
  $('workspace').hidden = !$('authGate').hidden;
  $('authMessage').textContent =
    data.session && !verified
      ? 'Chưa xác minh được với Pi. Kiểm tra địa chỉ gateway và kết nối mạng.'
      : '';
  $('gateway').value = config.gateway;

  for (const d of drafts) recordDraftHistory(d);
  renderList();
  await select(drafts.some(d => d.id === selected) ? selected : drafts[0]?.id ?? null);

  for (const d of drafts) {
    if (d.state === 'cancel_pending') transfer(d.id, d.error || label(d.state));
    else if (d.jobId && !terminalStates.includes(d.state)) pollResult(d.id);
  }
}

/* ---------- Theme toggle: 1.5s Left-to-Right sweep + centered SVG icon ---------- */
const SUN_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>';
const MOON_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/></svg>';

function syncThemeIcon() {
  const isLight = document.body.classList.contains('light');
  $('theme').innerHTML = isLight ? MOON_SVG : SUN_SVG;
  $('theme').title = isLight ? 'Chuyển sang giao diện tối' : 'Chuyển sang giao diện sáng';
}
document.body.classList.toggle('light', localStorage.getItem('theme') === 'light');
syncThemeIcon();

$('theme').onclick = () => {
  const applyNext = () => {
    document.body.classList.toggle('light');
    localStorage.setItem('theme', document.body.classList.contains('light') ? 'light' : 'dark');
    syncThemeIcon();
    if (imageViewMode !== 'original') renderImageStage();
  };
  if (typeof document.startViewTransition === 'function') {
    document.startViewTransition(applyNext);
  } else {
    document.body.classList.add('theme-fallback');
    applyNext();
    setTimeout(() => document.body.classList.remove('theme-fallback'), 1550);
  }
};

/* ---------- Settings / Login / Import ---------- */
function settings() {
  $('settings').showModal();
}
$('settingsButton').onclick = settings;
$('gateSettings').onclick = settings;
$('saveSettings').onclick = () =>
  run(async () => {
    resetOperations();
    await invoke('configure', { gateway: $('gateway').value.trim().replace(/\/$/, '') });
    $('settings').close();
    await boot();
  });

$('login').onclick = () =>
  run(async () => {
    $('login').disabled = true;
    $('authMessage').textContent = 'Hoàn tất đăng nhập trong trình duyệt…';
    try {
      await invoke('login');
      await boot();
    } finally {
      $('login').disabled = false;
    }
  });

$('logoutButton').onclick = () =>
  run(async () => {
    resetOperations();
    userId = null;
    verified = false;
    verifiedInfo = null;
    thumbCache.clear();
    thumbLoading.clear();
    clientPaperCache.clear();
    customPaperQuads.clear();
    pipelineCache.clear();
    lensSelectedLines.clear();
    imageViewMode = 'original';
    closeCamera();
    await invoke('logout');
    drafts = [];
    selected = null;
    await boot();
  });

$('import').onclick = () =>
  run(async () => {
    const items = await invoke('pick_import');
    items.forEach(patch);
    if (items.length) await select(items.at(-1).id);
    if (items.length) $('message').textContent = `Đã thêm ${items.length} ảnh vào danh sách.`;
  });

$('editImageBtn').onclick = e => {
  e.stopPropagation();
  if (selected) run(openEditor);
};
$('lensToggleBtn').onclick = e => {
  e.stopPropagation();
  lensEnabled = !lensEnabled;
  localStorage.setItem('viethandocr.lensEnabled', lensEnabled ? '1' : '0');
  renderImageStage();
};
$('original').onclick = e => {
  if (lensDragDidMove || compareDragging) {
    lensDragDidMove = false;
    return;
  }
  if (
    e.target.closest?.('.lens-floating-bar') ||
    e.target.closest?.('.lens-line') ||
    e.target.closest?.('.lens-corner-hit') ||
    e.target.closest?.('.lens-edge-hit') ||
    e.target.closest?.('.compare-overlay')
  ) {
    return;
  }
  if (!selected) {
    $('import').click();
    return;
  }
  if (imageViewMode !== 'original') return;
  run(openEditor);
};
$('original').onkeydown = e => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    if (selected) run(openEditor);
    else $('import').click();
  }
};
$('copy').onclick = () =>
  run(async () => {
    await navigator.clipboard.writeText($('text').value);
    toast('Đã sao chép văn bản');
  });
function formatExportTimestamp(date = new Date()) {
  const p = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`;
}
function cleanImageStem(name) {
  const stem = String(name || 'VietHandOCR').replace(/\.[^./\\]+$/, '').trim();
  return stem.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/^\.+|\.+$/g, '') || 'VietHandOCR';
}
$('exportText').onclick = () =>
  run(() => {
    const cur = drafts.find(d => d.id === selected);
    const stem = cur ? cleanImageStem(cur.name) : 'TatCa';
    const suggestedName = `${formatExportTimestamp()}_${stem}_Script.txt`;
    return invoke('export_text', { id: selected, suggestedName });
  });

function countText() {
  $('textCount').textContent = `${$('text').value.length.toLocaleString('vi')} ký tự`;
}
$('text').oninput = () => {
  countText();
  clearTimeout(textTimer);
  const id = selected;
  const text = $('text').value;
  const d = drafts.find(x => x.id === id);
  if (d) {
    d.text = text;
    recordDraftHistory(d);
    syncViewModeButtons(d);
    if (imageViewMode !== 'original') renderImageStage();
  }
  textTimer = setTimeout(() => run(() => invoke('save_text', { id, text })), 400);
};

/* ---------- Popover menus for Tải & Clear ---------- */
function closeAllPopMenus() {
  $('downloadMenu').hidden = true;
  $('clearMenu').hidden = true;
  $('downloadMenuBtn').setAttribute('aria-expanded', 'false');
  $('clearMenuBtn').setAttribute('aria-expanded', 'false');
}
function togglePopMenu(menuId, btnId) {
  const menu = $(menuId);
  const wasHidden = menu.hidden;
  closeAllPopMenus();
  if (wasHidden) {
    menu.hidden = false;
    $(btnId).setAttribute('aria-expanded', 'true');
  }
}
$('downloadMenuBtn').onclick = e => {
  e.stopPropagation();
  togglePopMenu('downloadMenu', 'downloadMenuBtn');
};
$('clearMenuBtn').onclick = e => {
  e.stopPropagation();
  togglePopMenu('clearMenu', 'clearMenuBtn');
};
document.addEventListener('click', e => {
  if (!e.target.closest?.('.menu-wrap')) closeAllPopMenus();
});

/* ---------- Export Dialog (Tải: 3 options -> 2-column preview + Tải cùng text) ---------- */
let exportSelection = new Set();

function renderExportDialog() {
  const listEl = $('exportImageList');
  const textEl = $('exportTextList');
  listEl.replaceChildren();
  textEl.replaceChildren();

  const chosenDrafts = drafts.filter(d => exportSelection.has(d.id));
  $('exportSelectedCount').textContent = String(chosenDrafts.length);
  $('exportImagesOnly').disabled = !chosenDrafts.length;
  $('exportWithText').disabled = !chosenDrafts.length;

  for (const d of drafts) {
    const isSel = exportSelection.has(d.id);
    const row = document.createElement('label');
    row.className = `export-row ${isSel ? 'selected' : ''}`;
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = isSel;
    cb.onchange = () => {
      if (cb.checked) exportSelection.add(d.id);
      else exportSelection.delete(d.id);
      renderExportDialog();
    };
    const img = document.createElement('img');
    img.className = 'export-thumb';
    img.alt = d.name;
    if (thumbCache.has(d.id)) img.src = thumbCache.get(d.id);
    else ensureThumb(d.id);
    const meta = document.createElement('div');
    meta.className = 'export-meta';
    const title = document.createElement('strong');
    title.textContent = d.name;
    const sub = document.createElement('small');
    sub.textContent = `${label(d.state)} · ${d.text ? `${d.text.length} ký tự` : 'Chưa có văn bản'}`;
    meta.append(title, sub);
    row.append(cb, img, meta);
    listEl.append(row);
  }

  if (!chosenDrafts.length) {
    const empty = document.createElement('p');
    empty.className = 'export-text-empty';
    empty.textContent = 'Chọn ít nhất một ảnh ở cột bên trái để xem văn bản đi kèm.';
    textEl.append(empty);
    return;
  }

  for (const d of chosenDrafts) {
    const card = document.createElement('div');
    card.className = 'export-text-card';
    const head = document.createElement('header');
    const name = document.createElement('strong');
    name.textContent = d.name;
    const len = document.createElement('small');
    len.className = 'muted';
    len.textContent = d.text ? `${d.text.length} ký tự` : 'Trống';
    head.append(name, len);
    const body = document.createElement('pre');
    if (d.text && d.text.trim()) {
      body.textContent = d.text;
    } else {
      body.className = 'export-text-empty';
      body.textContent = '(Ảnh này chưa có văn bản nhận dạng)';
    }
    card.append(head, body);
    textEl.append(card);
  }
}

function openExportPreview(mode) {
  closeAllPopMenus();
  exportSelection.clear();
  if (mode === 'current') {
    if (!selected) return;
    exportSelection.add(selected);
    $('exportTitle').textContent = 'Tải ảnh hiện tại';
  } else if (mode === 'all') {
    drafts.forEach(d => exportSelection.add(d.id));
    $('exportTitle').textContent = 'Tải toàn bộ ảnh';
  } else {
    if (selected) exportSelection.add(selected);
    $('exportTitle').textContent = 'Chọn ảnh để tải';
  }
  renderExportDialog();
  $('exportDialog').showModal();
}

$('dlCurrent').onclick = () => openExportPreview('current');
$('dlAll').onclick = () => openExportPreview('all');
$('dlPick').onclick = () => openExportPreview('pick');
$('exportSelectAll').onclick = () => {
  drafts.forEach(d => exportSelection.add(d.id));
  renderExportDialog();
};
$('exportUnselectAll').onclick = () => {
  exportSelection.clear();
  renderExportDialog();
};

async function performExport(withText) {
  const ids = drafts.filter(d => exportSelection.has(d.id)).map(d => d.id);
  if (!ids.length) return;
  const timestamp = formatExportTimestamp();
  const count = await invoke('export_images', { ids, withText, timestamp });
  if (count > 0) {
    $('exportDialog').close();
    toast(withText ? `Đã tải ${count} ảnh kèm file văn bản (_Script.txt)` : `Đã tải ${count} ảnh`);
  }
}
$('exportImagesOnly').onclick = () => run(() => performExport(false));
$('exportWithText').onclick = () => run(() => performExport(true));

/* ---------- Clear actions (3 options) ---------- */
let clearSelection = new Set();

async function removeDraftIds(ids) {
  if (!ids.length) return;
  const removed = await invoke('remove_drafts', { ids });
  const removedSet = new Set(removed);
  for (const id of removedSet) {
    thumbCache.delete(id);
    clientPaperCache.delete(id);
    customPaperQuads.delete(id);
    pipelineCache.delete(id);
  }
  drafts = drafts.filter(d => !removedSet.has(d.id));
  const nextSel = drafts.some(d => d.id === selected) ? selected : drafts[0]?.id ?? null;
  await select(nextSel);
  if (removed.length) toast(`Đã xoá ${removed.length} ảnh khỏi danh sách`);
}

$('clearCurrent').onclick = () =>
  run(async () => {
    closeAllPopMenus();
    const cur = drafts.find(d => d.id === selected);
    if (!isRemovable(cur)) return;
    await removeDraftIds([cur.id]);
  });

$('clearAll').onclick = () =>
  run(async () => {
    closeAllPopMenus();
    const ids = drafts.filter(isRemovable).map(d => d.id);
    if (!ids.length) return;
    await removeDraftIds(ids);
  });

function renderClearDialog() {
  const grid = $('clearGrid');
  grid.replaceChildren();
  const removableCount = drafts.filter(d => isRemovable(d) && clearSelection.has(d.id)).length;
  $('clearSelectedInfo').textContent = `Đã chọn ${removableCount} ảnh`;
  $('confirmClearSelected').disabled = removableCount === 0;

  for (const d of drafts) {
    const ok = isRemovable(d);
    const checked = ok && clearSelection.has(d.id);
    const card = document.createElement('label');
    card.className = `clear-card ${checked ? 'checked' : ''} ${ok ? '' : 'locked'}`;
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = checked;
    cb.disabled = !ok;
    cb.onchange = () => {
      if (cb.checked) clearSelection.add(d.id);
      else clearSelection.delete(d.id);
      renderClearDialog();
    };
    const img = document.createElement('img');
    img.alt = d.name;
    if (thumbCache.has(d.id)) img.src = thumbCache.get(d.id);
    else ensureThumb(d.id);
    const title = document.createElement('strong');
    title.textContent = d.name;
    const sub = document.createElement('small');
    sub.textContent = ok ? label(d.state) : `${label(d.state)} (đang xử lý)`;
    card.append(cb, img, title, sub);
    grid.append(card);
  }
}

$('clearPick').onclick = () => {
  closeAllPopMenus();
  clearSelection.clear();
  renderClearDialog();
  $('clearDialog').showModal();
};
$('clearSelectAll').onclick = () => {
  drafts.filter(isRemovable).forEach(d => clearSelection.add(d.id));
  renderClearDialog();
};
$('clearUnselectAll').onclick = () => {
  clearSelection.clear();
  renderClearDialog();
};
$('cancelClearDialog').onclick = () => $('clearDialog').close();
$('confirmClearSelected').onclick = () =>
  run(async () => {
    const ids = drafts.filter(d => isRemovable(d) && clearSelection.has(d.id)).map(d => d.id);
    $('clearDialog').close();
    await removeDraftIds(ids);
  });

/* ---------- Operations & Transfers ---------- */
function newOperation(id) {
  const op = { epoch: accountEpoch, controller: new AbortController(), finished: false, stopping: false };
  operations.set(id, op);
  return op;
}
const currentOperation = (id, op) => operations.get(id) === op && op.epoch === accountEpoch;
const activeOperation = (id, op) => currentOperation(id, op) && !op.controller.signal.aborted;

function resetOperations() {
  accountEpoch++;
  busy = false;
  autoSendQueue.length = 0;
  for (const op of operations.values()) op.controller.abort();
  operations.clear();
  runningResults.clear();
  transferRows.clear();
  clearTimeout(transferTimer);
  renderTransfers();
}

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(Error('operation_stopped'));
      return;
    }
    const stop = () => {
      clearTimeout(timer);
      reject(Error('operation_stopped'));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', stop);
      resolve();
    }, ms);
    signal.addEventListener('abort', stop, { once: true });
  });
}

function canStop(id) {
  const op = operations.get(id);
  return (op && !op.finished) || drafts.some(d => d.id === id && d.state === 'cancel_pending');
}

function renderTransfers() {
  const ids = [...transferRows.keys()];
  const active = ids.filter(canStop);
  $('transfers').hidden = !ids.length || transfersCollapsed;
  $('showTransfers').hidden = !ids.length || !transfersCollapsed;
  $('showTransfers').setAttribute('aria-label', `Mở tiến trình · ${active.length} ảnh chưa xong`);
  $('showTransfers').setAttribute('aria-expanded', String(!transfersCollapsed));
  $('transferTitle').textContent = active.length ? `Tiến trình gửi & đọc · ${active.length}` : 'Đã xử lý lượt gửi';
  $('stopAllTransfers').disabled = stoppingAll || !active.some(id => !operations.get(id)?.stopping);
  $('transferRows').replaceChildren();

  for (const [id, row] of transferRows) {
    const div = document.createElement('div');
    div.className = 'transfer-row';
    div.dataset.id = id;
    const heading = document.createElement('div');
    heading.className = 'transfer-heading';
    const title = document.createElement('span');
    title.textContent = drafts.find(x => x.id === id)?.name ?? 'Tài liệu';
    heading.append(title);
    if (canStop(id)) {
      const op = operations.get(id);
      const stop = document.createElement('button');
      stop.type = 'button';
      stop.className = 'stop-transfer';
      stop.dataset.stopId = id;
      stop.textContent = op?.stopping
        ? 'Đang dừng…'
        : op?.controller.signal.aborted || drafts.find(d => d.id === id)?.state === 'cancel_pending'
          ? 'Thử dừng lại'
          : 'Dừng';
      stop.disabled = stoppingAll || !!op?.stopping;
      stop.onclick = () => run(() => stopTransfer(id));
      heading.append(stop);
    }
    const progress = document.createElement('progress');
    progress.max = 1;
    if (row.done !== null) progress.value = Math.min(1, row.done / Math.max(1, row.total));
    const status = document.createElement('small');
    status.textContent = row.text;
    div.append(heading, progress, status);
    $('transferRows').append(div);
  }
}

function transfer(id, text, done = null, total = 1) {
  const cleanText = sanitizeError(text) || label(drafts.find(d => d.id === id)?.state ?? 'draft');
  transferRows.set(id, { text: cleanText, done, total });
  clearTimeout(transferTimer);
  renderTransfers();
  if ([...transferRows.values()].every(row => row.done === row.total)) {
    transferTimer = setTimeout(() => {
      transfersCollapsed = true;
      renderTransfers();
    }, 5000);
  }
}

$('hideTransfers').onclick = () => {
  transfersCollapsed = true;
  renderTransfers();
};
$('showTransfers').onclick = () => {
  transfersCollapsed = false;
  clearTimeout(transferTimer);
  renderTransfers();
};

$('stopAllTransfers').onclick = () =>
  run(async () => {
    if (stoppingAll) return;
    stoppingAll = true;
    const epoch = accountEpoch;
    const queue = [...transferRows.keys()].filter(canStop);
    for (const id of queue) (operations.get(id) ?? newOperation(id)).controller.abort();
    renderTransfers();
    async function worker() {
      let id;
      while (epoch === accountEpoch && (id = queue.shift())) await stopTransfer(id);
    }
    try {
      await Promise.all([worker(), worker()]);
    } finally {
      stoppingAll = false;
      renderTransfers();
    }
  });

async function stopTransfer(id) {
  const op = operations.get(id) ?? newOperation(id);
  if (op.stopping || !canStop(id)) return;
  op.stopping = true;
  op.controller.abort();
  transfer(id, 'Đã dừng gửi trên máy · đang xác nhận với server');
  try {
    const d = await invoke('stop_draft', { id });
    if (!currentOperation(id, op)) return;
    patch(d);
    op.finished = d.state !== 'cancel_pending';
    op.stopping = false;
    transfer(id, d.error || label(d.state), op.finished ? 1 : null);
    if (selected === id) {
      $('text').value = d.text ?? '';
      countText();
    }
  } catch (e) {
    if (currentOperation(id, op)) {
      op.stopping = false;
      transfer(id, `Đã dừng trên máy · chưa xác nhận server: ${String(e)}`);
    }
  } finally {
    renderList();
    renderTransfers();
  }
}

async function pollResult(id, op = operations.get(id) ?? newOperation(id)) {
  if (runningResults.get(id) === op || !activeOperation(id, op)) return;
  runningResults.set(id, op);
  let interruptions = 0;
  try {
    while (drafts.some(d => d.id === id) && verified && activeOperation(id, op)) {
      let d;
      try {
        d = await invoke('read_result', { id });
        interruptions = 0;
      } catch (e) {
        if (!activeOperation(id, op)) return;
        if (/HTTP (401|403)|Đăng nhập Google/.test(String(e))) throw e;
        interruptions++;
        transfer(id, 'Server giữ lượt gửi · đang kết nối lại để nhận kết quả');
        await delay(Math.min(15000, 1500 * interruptions) + Math.random() * 500, op.controller.signal);
        continue;
      }
      if (!activeOperation(id, op)) return;
      op.finished =
        terminalStates.includes(d.state) || sendableStates.includes(d.state) || d.state === 'cancel_pending';
      patch(d);
      transfer(id, d.error || label(d.state), op.finished ? 1 : null);
      if (selected === id && document.activeElement !== $('text')) {
        $('text').value = d.text;
        countText();
      }
      if (selected === id && d.state === 'succeeded') {
        syncViewModeButtons(d);
        renderImageStage();
        if (demoPipelineMode && d.jobId) void prefetchPipeline(d);
        renderPipelineMiniBar();
        if (pendingPipelineOpenDraftId === d.id) {
          pendingPipelineOpenDraftId = null;
          void openPipelineDialog(0, 'overview');
        }
      }
      if (op.finished) {
        void refreshSessionQuota();
        break;
      }
      await delay(500, op.controller.signal);
    }
  } catch (e) {
    if (activeOperation(id, op)) {
      op.finished = true;
      const msg = sanitizeError(e);
      transfer(id, msg ? `Kết quả đang lưu ở server · ${msg}` : 'Hoàn tất', 1);
      if (msg) $('message').textContent = 'Chưa nhận kết quả. Mở app lại để lấy tiếp.';
    }
  } finally {
    if (runningResults.get(id) === op) runningResults.delete(id);
  }
}

/* ---------- History Modal (Left/Right split, max 50, filename + optional sent time + latest text) ---------- */
function formatHistoryTime(rawTime) {
  if (!rawTime) return '';
  const dt = new Date(rawTime);
  if (Number.isNaN(dt.getTime())) return '';
  return dt.toLocaleString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function syncHistoryTimeVisibility() {
  $('historyRows').classList.toggle('history-hide-time', !$('historyShowTime').checked);
}
$('historyShowTime').checked = localStorage.getItem('viethandocr.historyShowTime') !== '0';
$('historyShowTime').onchange = () => {
  localStorage.setItem('viethandocr.historyShowTime', $('historyShowTime').checked ? '1' : '0');
  syncHistoryTimeVisibility();
};

$('historyButton').onclick = () =>
  run(async () => {
    const epoch = accountEpoch;
    const rawRows = await invoke('history');
    if (epoch !== accountEpoch) return;
    const rows = Array.isArray(rawRows) ? rawRows.slice(0, 50) : [];
    const meta = loadHistoryMeta();

    $('historyRows').replaceChildren();
    $('historyText').value = '';
    $('historyState').textContent = rows.length ? '' : 'Chưa có lượt gửi nào.';
    syncHistoryTimeVisibility();

    for (let idx = 0; idx < rows.length; idx++) {
      const item = rows[idx];
      const localDraft = drafts.find(d => d.jobId === item.id || (item.sha256 && d.sha256 === item.sha256));
      const cached = meta[`job:${item.id}`] || (item.sha256 ? meta[`sha:${item.sha256}`] : null);
      const displayName =
        localDraft?.name || cached?.name || `Ảnh #${String(item.id || idx + 1).slice(0, 8)}`;
      const timeStr = formatHistoryTime(item.created_at ?? item.createdAt ?? cached?.sentAt);
      const subText = timeStr ? `${timeStr} · ${label(item.state)}` : label(item.state);

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'history-item';

      const thumbUrl = (localDraft && thumbCache.get(localDraft.id)) || cached?.thumb || '';
      if (thumbUrl) {
        const img = document.createElement('img');
        img.className = 'history-thumb';
        img.src = thumbUrl;
        img.alt = displayName;
        btn.append(img);
      } else if (localDraft) {
        const img = document.createElement('img');
        img.className = 'history-thumb';
        img.alt = displayName;
        img.dataset.thumbId = localDraft.id;
        ensureThumb(localDraft.id);
        btn.append(img);
      } else {
        const ph = document.createElement('span');
        ph.className = 'history-thumb';
        ph.textContent = '🖼';
        btn.append(ph);
      }

      const metaBox = document.createElement('div');
      metaBox.className = 'history-item-meta';
      const titleEl = document.createElement('span');
      titleEl.className = 'history-item-title';
      titleEl.textContent = displayName;
      titleEl.title = displayName;
      const timeEl = document.createElement('span');
      timeEl.className = 'history-item-time';
      timeEl.textContent = subText;
      metaBox.append(titleEl, timeEl);
      btn.append(metaBox);

      btn.onclick = () =>
        run(async () => {
          for (const el of $('historyRows').querySelectorAll('.history-item.active')) {
            el.classList.remove('active');
          }
          btn.classList.add('active');
          $('historyState').textContent = 'Đang tải…';
          const fallbackText = localDraft?.text || cached?.text || '';
          try {
            const data = await invoke('history_result', { id: item.id });
            if (epoch !== accountEpoch) return;
            const resolvedText = data?.text || fallbackText || sanitizeError(data?.error) || '';
            $('historyText').value = resolvedText;
            $('historyState').textContent = label(data?.state ?? item.state);
            if (resolvedText) {
              saveHistoryMeta({
                jobId: item.id,
                sha256: item.sha256,
                name: displayName,
                sentAt: item.created_at ?? item.createdAt ?? cached?.sentAt,
                text: resolvedText,
                state: data?.state ?? item.state,
              });
            }
          } catch (err) {
            if (epoch !== accountEpoch) return;
            if (fallbackText) {
              $('historyText').value = fallbackText;
              $('historyState').textContent = `${label(item.state)} (lưu cục bộ)`;
            } else {
              $('historyText').value = '';
              $('historyState').textContent =
                /result_expired|HTTP 410/i.test(String(err))
                  ? 'Kết quả đã hết hạn lưu trên server'
                  : sanitizeError(err) || label(item.state);
            }
          }
        });
      $('historyRows').append(btn);
    }

    $('history').showModal();
    $('historyRows').querySelector('.history-item')?.click();
  });

$('historyCopy').onclick = () =>
  run(async () => {
    await navigator.clipboard.writeText($('historyText').value);
    toast('Đã sao chép kết quả');
  });

/* ---------- Dev-only Logs ---------- */
$('logsButton').onclick = () =>
  run(async () => {
    $('logText').value = await invoke('read_logs');
    $('logs').showModal();
  });
$('reloadLogs').onclick = () =>
  run(async () => {
    $('logText').value = await invoke('read_logs');
  });
$('copyLogs').onclick = () =>
  run(async () => {
    await navigator.clipboard.writeText($('logText').value);
    toast('Đã sao chép nhật ký');
  });

/* ---------- Send (always layout='auto', optional BARTpho correction) ---------- */
const correctInput = $('correct');
if (correctInput) {
  correctInput.checked = localStorage.getItem('vietocr.correct') === '1';
  correctInput.onchange = () => localStorage.setItem('vietocr.correct', correctInput.checked ? '1' : '0');
}
const demoPipelineInput = $('demoPipeline');
if (demoPipelineInput) {
  demoPipelineInput.checked = demoPipelineMode;
  demoPipelineInput.onchange = () => {
    demoPipelineMode = demoPipelineInput.checked;
    localStorage.setItem('viethandocr.demoPipeline', demoPipelineMode ? '1' : '0');
    const cur = drafts.find(x => x.id === selected);
    if (demoPipelineMode && cur?.state === 'succeeded' && cur.jobId) void prefetchPipeline(cur);
    renderList();
  };
}

async function runDraftSend(d, op, { layout = 'auto', correct = false, epoch = accountEpoch }) {
  if (!activeOperation(d.id, op) || epoch !== accountEpoch) return;
  try {
    let result;
    const deadline = Date.now() + 20 * 60000;
    while (activeOperation(d.id, op) && epoch === accountEpoch) {
      try {
        result = await invoke('send_draft', {
          id: d.id,
          layout,
          correct,
          progress: channel(p => {
            if (activeOperation(d.id, op)) {
              transfer(
                d.id,
                p.stage === 'optimizing'
                  ? 'Đang tự tối ưu ảnh · giữ bản gốc'
                  : p.stage === 'uploading'
                    ? `Đang gửi ${Math.round((p.done / Math.max(1, p.total)) * 100)}%`
                    : p.stage,
                p.total ? p.done : null,
                p.total || 1,
              );
            }
          }),
        });
        break;
      } catch (e) {
        if (!activeOperation(d.id, op)) break;
        if (
          !/queue_wait|compute_queue_busy|uploads_busy|auth_capacity|database_capacity|compute_capacity|compute_unreachable|compute_unavailable|identity_database_unavailable|jwks_unavailable|server_not_ready|minute_quota|offset_mismatch|stale_lease/.test(
            String(e),
          ) ||
          Date.now() > deadline
        ) {
          throw e;
        }
        transfer(d.id, 'Đang chờ công suất hoặc kết nối lại');
        await delay(3000 + Math.random() * 1000, op.controller.signal);
      }
    }
    if (!activeOperation(d.id, op) || !result) return;
    saveHistoryMeta({
      jobId: result.jobId,
      sha256: result.sha256,
      name: result.name,
      sentAt: new Date().toISOString(),
      text: result.text,
      state: result.state,
    });
    patch(result);
    if (terminalStates.includes(result.state)) {
      op.finished = true;
      transfer(d.id, result.error || label(result.state), 1);
      if (selected === result.id) {
        $('text').value = result.text ?? '';
        countText();
        syncViewModeButtons(result);
        renderImageStage();
      }
    } else {
      pollResult(d.id, op);
    }
  } catch (e) {
    if (activeOperation(d.id, op)) {
      op.finished = true;
      const msg = sanitizeError(e);
      transfer(d.id, msg || 'Lỗi gửi ảnh', 1);
      if (msg) fail(msg);
    }
  }
}

function pumpAutoSendWorkers() {
  while (autoSendWorkers < 2 && autoSendQueue.length > 0) {
    autoSendWorkers++;
    (async () => {
      try {
        while (autoSendQueue.length > 0) {
          const item = autoSendQueue.shift();
          if (!item || item.epoch !== accountEpoch) continue;
          await runDraftSend(item.d, item.op, item);
          void refreshSessionQuota();
        }
      } finally {
        autoSendWorkers--;
        renderList();
      }
    })();
  }
}

async function enqueueAutoSend(draft) {
  if (!verified || !draft?.id) return;
  const existingOp = operations.get(draft.id);
  if (existingOp && !existingOp.finished) return;
  const epoch = accountEpoch;
  const correct = Boolean($('correct')?.checked);
  try {
    const prepared = await invoke('prepare_send', { ids: [draft.id] });
    if (epoch !== accountEpoch || !Array.isArray(prepared) || !prepared.length) return;
    prepared.forEach(patch);
    const d = prepared[0];
    const op = newOperation(d.id);
    transfersCollapsed = false;
    transfer(d.id, 'Tự động gửi OCR…');
    renderList();
    autoSendQueue.push({ d, op, layout: 'auto', correct, epoch });
    pumpAutoSendWorkers();
  } catch (e) {
    if (epoch === accountEpoch) fail(e);
  }
}

$('send').onclick = () =>
  run(async () => {
    if (busy || !verified) return;
    busy = true;
    renderList();
    const selectedDrafts = drafts.filter(d => {
      if (d.included === false || !sendableStates.includes(d.state)) return false;
      const op = operations.get(d.id);
      return !(op && !op.finished);
    });
    if (!selectedDrafts.length) {
      busy = false;
      renderList();
      return;
    }
    const epoch = accountEpoch;
    const layout = 'auto';
    const correct = Boolean($('correct')?.checked);

    async function worker(queue) {
      let item;
      while (epoch === accountEpoch && (item = queue.shift())) {
        await runDraftSend(item.d, item.op, { layout, correct, epoch });
      }
    }

    try {
      const prepared = await invoke('prepare_send', { ids: selectedDrafts.map(d => d.id) });
      if (epoch !== accountEpoch) return;
      prepared.forEach(patch);
      transfersCollapsed = false;
      const queue = prepared.map(d => ({ d, op: newOperation(d.id) }));
      for (const { d } of queue) transfer(d.id, 'Chờ tự tối ưu và gửi');
      await Promise.all([worker(queue), worker(queue)]);
      void refreshSessionQuota();
    } finally {
      if (epoch === accountEpoch) {
        busy = false;
        renderList();
      }
    }
  });

/* ---------- Sidebar Splitter ---------- */
const splitter = $('splitter');
splitter.onpointerdown = e => {
  resizingSidebar = true;
  cancelSidebarHide();
  splitter.setPointerCapture(e.pointerId);
  splitter.onpointermove = ev => {
    sidebar.style.width = `${Math.max(240, Math.min(440, ev.clientX))}px`;
  };
  splitter.onpointerup = () => {
    splitter.onpointermove = null;
    resizingSidebar = false;
  };
};

/* ---------- Pi Camera ---------- */
let review = false;
let reviewMirrored = false;
let cameraGeneration = 0;
let cameraAutoSend = localStorage.getItem('viethandocr.cameraAutoSend') !== '0';
const cameraAutoSendInput = $('cameraAutoSend');
if (cameraAutoSendInput) {
  cameraAutoSendInput.checked = cameraAutoSend;
  cameraAutoSendInput.onchange = () => {
    cameraAutoSend = cameraAutoSendInput.checked;
    localStorage.setItem('viethandocr.cameraAutoSend', cameraAutoSend ? '1' : '0');
  };
}

function liveTransform() {
  $('live').style.transform =
    (!review && $('mirror').checked) || (review && $('mirror').checked !== reviewMirrored) ? 'scaleX(-1)' : '';
}
function closeCamera() {
  cameraGeneration++;
  clearTimeout(reviewTimer);
  reviewTimer = null;
  review = false;
  $('camera').close();
  run(() => invoke('camera_stop'));
  if (liveURL) {
    URL.revokeObjectURL(liveURL);
    liveURL = null;
  }
}
async function startCamera() {
  const generation = ++cameraGeneration;
  review = false;
  clearTimeout(reviewTimer);
  reviewTimer = null;
  $('skip').hidden = true;
  $('shoot').disabled = false;
  liveTransform();
  $('cameraStatus').textContent = 'Đang mở camera…';
  await invoke('camera_stop');
  const frames = channel(async buffer => {
    try {
      if (generation === cameraGeneration && !review && $('camera').open) {
        const next = URL.createObjectURL(new Blob([buffer], { type: 'image/jpeg' }));
        const old = liveURL;
        liveURL = next;
        $('live').src = next;
        $('cameraStatus').textContent = 'Đang xem trực tiếp';
        if (old) URL.revokeObjectURL(old);
      }
    } finally {
      await invoke('camera_ack');
    }
  });
  invoke('camera_stream', { id: $('cameraSelect').value, frames })
    .then(() => {
      if (generation === cameraGeneration && $('camera').open && !review) {
        $('cameraStatus').textContent = 'Stream đã dừng. Chọn lại camera để nối lại.';
      }
    })
    .catch(e => {
      if (generation === cameraGeneration && $('camera').open) $('cameraStatus').textContent = String(e);
    });
}
$('cameraButton').onclick = () =>
  run(async () => {
    const items = await invoke('cameras');
    $('cameraSelect').replaceChildren();
    for (const c of items) {
      const option = document.createElement('option');
      option.value = c.id;
      option.textContent = c.name;
      $('cameraSelect').append(option);
    }
    if (!items.length) throw Error('Pi chưa có webcam được cấu hình.');
    $('camera').showModal();
    await startCamera();
  });
$('cameraSelect').onchange = () => run(startCamera);
$('cameraClose').onclick = closeCamera;
$('camera').addEventListener('cancel', () => closeCamera());
$('mirror').onchange = liveTransform;
function skip() {
  clearTimeout(reviewTimer);
  reviewTimer = null;
  review = false;
  $('skip').hidden = true;
  $('shoot').disabled = false;
  $('reviewStatus').textContent = verified && cameraAutoSend
    ? 'Đã tự động gửi OCR · sẵn sàng chụp ảnh kế tiếp'
    : 'Đã lưu bản nháp · sẵn sàng chụp ảnh kế tiếp';
  liveTransform();
}
$('skip').onclick = skip;
$('shoot').onclick = () =>
  run(async () => {
    $('shoot').disabled = true;
    const epoch = accountEpoch;
    const generation = cameraGeneration;
    const mirrored = $('mirror').checked;
    const autoSendNow = verified && cameraAutoSend;
    try {
      let d = await invoke('capture', { id: $('cameraSelect').value });
      if (epoch !== accountEpoch || generation !== cameraGeneration) return;
      patch(d);
      if (mirrored) {
        const image = new Image();
        image.src = await invoke('draft_image', { id: d.id });
        await image.decode();
        const out = document.createElement('canvas');
        out.width = image.naturalWidth;
        out.height = image.naturalHeight;
        const c = out.getContext('2d');
        c.translate(out.width, 0);
        c.scale(-1, 1);
        c.drawImage(image, 0, 0);
        d = await saveCanvas(out, `Mirror-${Date.now()}.png`, d.id);
      }
      if (epoch !== accountEpoch || generation !== cameraGeneration) return;
      await select(d.id);
      // Automatically send captured photo to OCR in background when user enabled cameraAutoSend
      if (autoSendNow) {
        void enqueueAutoSend(d);
      }
      review = true;
      reviewMirrored = mirrored;
      liveTransform();
      $('live').src = thumbCache.get(d.id) ?? (await invoke('draft_image', { id: d.id }));
      $('skip').hidden = false;
      $('reviewStatus').textContent = autoSendNow
        ? 'Đã chụp · đang tự động gửi OCR (chuyển ảnh kế sau 0.5s)…'
        : 'Đã lưu bản nháp · chuyển ảnh kế sau 0.5s…';
      reviewTimer = setTimeout(skip, 500);
    } catch (e) {
      $('shoot').disabled = false;
      throw e;
    }
  });

/* ---------- Image Editor: Center & Fit 100% at Zoom=0, Angle=0, Photoshop Freehand Lasso ---------- */
const canvas = $('canvas');
const ctx = canvas.getContext('2d');
const editorStage = $('editorStage');

function computeEditorScale() {
  if (!editorSource) return 1;
  const pad = 22;
  const availW = Math.max(120, editorStage.clientWidth - pad);
  const availH = Math.max(120, editorStage.clientHeight - pad);
  const fitScale = Math.min(availW / canvas.width, availH / canvas.height);
  const zoomPct = Number($('zoom').value) || 0;
  return fitScale * (1 + zoomPct / 100);
}

function snapRadiusImgPx() {
  const scale = Math.max(0.05, computeEditorScale());
  return Math.max(14 / scale, Math.min(canvas.width, canvas.height) * 0.025);
}

async function openEditor() {
  if (!selected) return;
  const image = new Image();
  image.src = thumbCache.get(selected) ?? (await invoke('draft_image', { id: selected }));
  await image.decode();
  editorSource = image;
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  points = [];
  freehandClosed = false;
  freehandNearStart = false;
  freehandError = '';
  $('shape').value = 'rectangle';
  $('angle').value = '0';
  $('zoom').value = '0';
  $('editor').showModal();
  requestAnimationFrame(drawEditor);
}

function drawEditor(preserveCenter = false) {
  if (!editorSource) return;
  const shape = $('shape').value;
  const angle = Number($('angle').value) || 0;
  const zoomPct = Number($('zoom').value) || 0;
  $('angleVal').textContent = `${angle}°`;
  $('zoomVal').textContent = zoomPct === 0 ? '0% (Vừa khung)' : `+${zoomPct}%`;

  const stageW = editorStage.clientWidth;
  const stageH = editorStage.clientHeight;
  const prevScrollW = editorStage.scrollWidth || stageW;
  const prevScrollH = editorStage.scrollHeight || stageH;
  const relX =
    preserveCenter && prevScrollW > stageW
      ? (editorStage.scrollLeft + stageW / 2) / prevScrollW
      : 0.5;
  const relY =
    preserveCenter && prevScrollH > stageH
      ? (editorStage.scrollTop + stageH / 2) / prevScrollH
      : 0.5;

  const scale = computeEditorScale();
  const nextW = Math.round(canvas.width * scale);
  const nextH = Math.round(canvas.height * scale);
  canvas.style.width = `${nextW}px`;
  canvas.style.height = `${nextH}px`;

  if (preserveCenter) {
    const newScrollW = editorStage.scrollWidth;
    const newScrollH = editorStage.scrollHeight;
    editorStage.scrollLeft = newScrollW > stageW ? Math.max(0, Math.round(relX * newScrollW - stageW / 2)) : 0;
    editorStage.scrollTop = newScrollH > stageH ? Math.max(0, Math.round(relY * newScrollH - stageH / 2)) : 0;
  }

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(editorSource, 0, 0);

  const strokeW = Math.max(2, 2.2 / Math.max(0.1, scale));
  if (shape === 'freehand') {
    if (points.length >= 1) {
      ctx.save();
      ctx.lineWidth = strokeW;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';

      if (freehandClosed) {
        const polygon = outline(points, 'freehand', angle);
        ctx.strokeStyle = '#72cfff';
        ctx.fillStyle = '#72cfff28';
        ctx.beginPath();
        polygon.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      } else {
        // Open stroke: draw 1-to-1 cursor trail without rotating or forcing chord closure
        ctx.strokeStyle = drawing ? '#72cfff' : '#fbbf24';
        if (!drawing) ctx.setLineDash([strokeW * 3, strokeW * 2]);
        ctx.beginPath();
        points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.stroke();
        ctx.setLineDash([]);

        // Draw start anchor dot so user knows where to close the loop
        const [sx, sy] = points[0];
        const dotR = Math.max(5, 6 / Math.max(0.1, scale));
        ctx.beginPath();
        ctx.arc(sx, sy, dotR, 0, Math.PI * 2);
        ctx.fillStyle = freehandNearStart ? '#4ade80' : '#72cfff';
        ctx.fill();
        ctx.lineWidth = Math.max(1.5, strokeW * 0.7);
        ctx.strokeStyle = '#0c0e10';
        ctx.stroke();
      }
      ctx.restore();
    }
  } else {
    const polygon = outline(points, shape, angle);
    if (polygon.length) {
      ctx.save();
      ctx.lineWidth = strokeW;
      ctx.strokeStyle = '#72cfff';
      ctx.fillStyle = '#72cfff22';
      ctx.beginPath();
      polygon.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }
  }

  const baseInfo = `${canvas.width} × ${canvas.height} px · gốc được giữ nguyên`;
  if (shape === 'freehand') {
    if (freehandClosed) {
      $('editorInfo').textContent = `${baseInfo} · Đã khép kín vùng chọn`;
    } else if (freehandNearStart && drawing) {
      $('editorInfo').textContent = 'Thả chuột để khép kín vùng chọn';
    } else if (freehandError) {
      $('editorInfo').textContent = freehandError;
    } else {
      $('editorInfo').textContent = `${baseInfo} · Vẽ một vòng khép kín (chạm điểm đầu hoặc cắt qua nét cũ)`;
    }
  } else {
    $('editorInfo').textContent = baseInfo;
  }
  $('crop').disabled = shape === 'freehand' ? !freehandClosed : points.length < 2;
}

const editorResizeObserver = new ResizeObserver(() => {
  if ($('editor').open && editorSource) drawEditor();
});
editorResizeObserver.observe(editorStage);

const point = e => {
  const r = canvas.getBoundingClientRect();
  return [
    Math.max(0, Math.min(canvas.width, ((e.clientX - r.left) * canvas.width) / r.width)),
    Math.max(0, Math.min(canvas.height, ((e.clientY - r.top) * canvas.height) / r.height)),
  ];
};

canvas.onpointerdown = e => {
  drawing = true;
  freehandError = '';
  freehandClosed = false;
  freehandNearStart = false;
  canvas.setPointerCapture(e.pointerId);
  const p = point(e);
  if ($('shape').value === 'freehand') {
    $('angle').value = '0';
    points = [p];
  } else {
    points = [p, p];
  }
  drawEditor();
};

canvas.onpointermove = e => {
  if (!drawing) return;
  const p = point(e);
  if ($('shape').value === 'freehand') {
    const minStep = Math.max(2, 3 / Math.max(0.1, computeEditorScale()));
    const prev = points.at(-1);
    if (!prev || dist(prev, p) < minStep) return;
    if (points.length < 4096) points.push(p);

    // Check self-intersection -> immediately lock exact Photoshop Lasso closed loop!
    const selfLoop = detectSelfClose(points);
    if (selfLoop) {
      points = selfLoop;
      freehandClosed = true;
      freehandNearStart = false;
      drawing = false;
      drawEditor();
      return;
    }
    freehandNearStart = points.length >= 6 && dist(points[0], p) <= snapRadiusImgPx();
  } else {
    points[1] = p;
  }
  drawEditor();
};

canvas.onpointerup = () => {
  if (!drawing) return;
  drawing = false;
  if ($('shape').value === 'freehand') {
    const res = finalizeFreehand(points, snapRadiusImgPx());
    if (res.closed) {
      points = res.polygon;
      freehandClosed = true;
      freehandError = '';
    } else {
      freehandClosed = false;
      freehandError = 'Nét chưa khép kín — hãy vẽ chạm điểm đầu hoặc cắt qua nét cũ để tạo vùng cắt.';
    }
  }
  drawEditor();
};

$('shape').onchange = () => {
  points = [];
  freehandClosed = false;
  freehandNearStart = false;
  freehandError = '';
  $('angle').value = '0';
  drawEditor();
};
$('angle').oninput = () => drawEditor(false);
$('zoom').oninput = () => drawEditor(true);
$('editorClose').onclick = () => {
  $('editor').close();
  editorSource = null;
};

async function saveCanvas(output, name, sourceId = selected) {
  const d = await invoke('save_edit', { data: output.toDataURL('image/png'), name, sourceId });
  const original = drafts.find(x => x.id === sourceId);
  if (original) original.included = false;
  patch(d);
  await select(d.id);
  toast('Đã lưu bản chỉnh sửa và chọn gửi · bản gốc vẫn được giữ');
  return d;
}

$('crop').onclick = () =>
  run(async () => {
    const shape = $('shape').value;
    if (shape === 'freehand' && !freehandClosed) {
      throw Error('Hãy vẽ một nét khép kín (chạm điểm đầu hoặc cắt qua nét cũ) trước khi cắt.');
    }
    const polygon = outline(points, shape, Number($('angle').value));
    const r = bounds(polygon, canvas.width, canvas.height);
    const out = document.createElement('canvas');
    out.width = r.w;
    out.height = r.h;
    const c = out.getContext('2d');
    c.fillStyle = '#fff';
    c.fillRect(0, 0, r.w, r.h);
    c.save();
    c.beginPath();
    polygon.forEach(([x, y], i) => (i ? c.lineTo(x - r.l, y - r.t) : c.moveTo(x - r.l, y - r.t)));
    c.closePath();
    c.clip();
    c.drawImage(editorSource, -r.l, -r.t);
    c.restore();
    await saveCanvas(out, `Crop-${Date.now()}.png`);
    $('editor').close();
  });

$('rotate').onclick = () =>
  run(async () => {
    const out = document.createElement('canvas');
    out.width = canvas.height;
    out.height = canvas.width;
    const c = out.getContext('2d');
    c.translate(out.width, 0);
    c.rotate(Math.PI / 2);
    c.drawImage(editorSource, 0, 0);
    await saveCanvas(out, `Rotate-${Date.now()}.png`);
    $('editor').close();
  });

$('bw').onclick = () =>
  run(async () => {
    $('bw').disabled = true;
    try {
      const out = document.createElement('canvas');
      out.width = canvas.width;
      out.height = canvas.height;
      out.getContext('2d').drawImage(editorSource, 0, 0);
      const blob = await new Promise(r => out.toBlob(r, 'image/png'));
      const worker = new Worker('bw-worker.mjs', { type: 'module' });
      const result = await new Promise((resolve, reject) => {
        worker.onmessage = e => (e.data.error ? reject(Error(e.data.error)) : resolve(e.data.blob));
        worker.onerror = reject;
        worker.postMessage(blob);
      });
      worker.terminate();
      const data = await new Promise(resolve => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(result);
      });
      const sourceId = selected;
      const d = await invoke('save_edit', { data, name: `BW-${Date.now()}.png`, sourceId });
      const original = drafts.find(x => x.id === sourceId);
      if (original) original.included = false;
      patch(d);
      await select(d.id);
      $('editor').close();
      toast('Đã lưu bản đen trắng và chọn gửi · bản gốc vẫn được giữ');
    } finally {
      $('bw').disabled = false;
    }
  });

/* ---------- View Modes ("Ảnh gốc" | "Ảnh văn bản" | "Đối chiếu") + Draggable Google Lens ---------- */
const SVG_NS = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

const CUSTOM_QUAD_STORE_KEY = 'viethandocr.customQuads.v1';
function loadCustomQuadsFromStorage() {
  try {
    const obj = JSON.parse(localStorage.getItem(CUSTOM_QUAD_STORE_KEY) || '{}');
    if (obj && typeof obj === 'object') {
      for (const [k, v] of Object.entries(obj)) {
        if (Array.isArray(v) && v.length === 4) customPaperQuads.set(k, v);
      }
    }
  } catch {
    /* ignore */
  }
}
function persistCustomQuads() {
  try {
    const entries = [...customPaperQuads.entries()].slice(-60);
    localStorage.setItem(CUSTOM_QUAD_STORE_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    /* ignore */
  }
}
loadCustomQuadsFromStorage();

function getBaseLensData(d) {
  if (!d) return null;
  if (d.lens && typeof d.lens === 'object') return d.lens;
  return clientPaperCache.get(d.id) || null;
}

function getActiveLensData(d) {
  if (!d) return null;
  const base = getBaseLensData(d);
  const img = $('originalImage');
  const natW = base?.sourceWidth || img?.naturalWidth || d.width || 0;
  const natH = base?.sourceHeight || img?.naturalHeight || d.height || 0;
  const customQuad = customPaperQuads.get(d.id);
  if (customQuad && customQuad.length === 4 && natW > 0 && natH > 0) {
    return {
      sourceWidth: natW,
      sourceHeight: natH,
      route: base?.route || 'custom-lens',
      lines: Array.isArray(base?.lines) ? base.lines : [],
      ...(base || {}),
      paperDetected: true,
      paperQuad: customQuad,
      customAdjusted: true,
    };
  }
  if (base) return base;
  // Provide an adjustable inset frame even on full-bleed scans so user can always drag Lens corners
  if (natW >= 32 && natH >= 32) {
    const px = Math.round(natW * 0.03);
    const py = Math.round(natH * 0.03);
    return {
      sourceWidth: natW,
      sourceHeight: natH,
      route: 'default-frame',
      paperDetected: false,
      defaultFrame: true,
      paperQuad: [
        [px, py],
        [natW - px, py],
        [natW - px, natH - py],
        [px, natH - py],
      ],
      lines: [],
      clientOnly: true,
    };
  }
  return null;
}

function hasDigitalText(d) {
  return Boolean(d && typeof d.text === 'string' && d.text.trim().length > 0);
}

function syncViewModeButtons(d = drafts.find(x => x.id === selected)) {
  const canDigital = hasDigitalText(d);
  if (!canDigital && imageViewMode !== 'original') {
    imageViewMode = 'original';
  }
  const tabs = [
    ['viewOriginal', 'original', false],
    ['viewDigital', 'digital', !canDigital],
    ['viewCompare', 'compare', !canDigital],
  ];
  for (const [id, mode, disabled] of tabs) {
    const btn = $(id);
    if (!btn) continue;
    btn.disabled = disabled;
    const active = imageViewMode === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', String(active));
  }
  $('lensToggleBtn').hidden = !d || imageViewMode !== 'original';
  $('original').classList.toggle('view-non-original', imageViewMode !== 'original');
}

function setImageViewMode(mode) {
  const d = drafts.find(x => x.id === selected);
  if (mode !== 'original' && !hasDigitalText(d)) return;
  imageViewMode = mode;
  syncViewModeButtons(d);
  renderImageStage();
}

$('viewOriginal').onclick = () => setImageViewMode('original');
$('viewDigital').onclick = () => setImageViewMode('digital');
$('viewCompare').onclick = () => setImageViewMode('compare');

function applyCompareSplit(pct) {
  compareSplit = Math.max(0, Math.min(100, pct));
  const digitalLayer = $('digitalLayer');
  const divider = $('compareDivider');
  // Left 0..compareSplit% = Ảnh văn bản (drag RIGHT -> reveals more Ảnh văn bản; drag LEFT -> reveals more Ảnh gốc)
  digitalLayer.style.clipPath = `inset(0 ${(100 - compareSplit).toFixed(2)}% 0 0)`;
  divider.style.left = `${compareSplit.toFixed(2)}%`;
  divider.setAttribute('aria-valuenow', String(Math.round(compareSplit)));
  $('compareTagLeft').style.opacity = compareSplit < 14 ? '0' : '1';
  $('compareTagRight').style.opacity = compareSplit > 86 ? '0' : '1';
}

function positionOverlayBox(el, rect) {
  el.style.left = `${rect.left}px`;
  el.style.top = `${rect.top}px`;
  el.style.width = `${rect.width}px`;
  el.style.height = `${rect.height}px`;
}

function updateDigitalHoverClasses() {
  const svg = $('digitalHoverSvg');
  for (const rect of svg.querySelectorAll('.digital-line-hit')) {
    const lid = Number(rect.getAttribute('data-line-id'));
    rect.classList.toggle('hovered', lensHoveredLine === lid);
    rect.classList.toggle('selected', lensSelectedLines.has(lid));
  }
}

function renderDigitalHoverLayer(flatRect, lineHits) {
  const svg = $('digitalHoverSvg');
  activeDigitalLineHits = Array.isArray(lineHits) ? lineHits : [];
  activeFlatRect = flatRect;
  if (!flatRect || !activeDigitalLineHits.length) {
    svg.style.display = 'none';
    svg.replaceChildren();
    return;
  }
  positionOverlayBox(svg, flatRect);
  svg.setAttribute('viewBox', `0 0 ${flatRect.width.toFixed(1)} ${flatRect.height.toFixed(1)}`);
  svg.replaceChildren();

  for (const hit of activeDigitalLineHits) {
    const isHov = lensHoveredLine === hit.id;
    const isSel = lensSelectedLines.has(hit.id);
    const el = svgEl('rect', {
      class: `digital-line-hit${isSel ? ' selected' : ''}${isHov ? ' hovered' : ''}`,
      x: hit.x.toFixed(1),
      y: hit.y.toFixed(1),
      width: Math.max(8, hit.w).toFixed(1),
      height: Math.max(8, hit.h).toFixed(1),
      rx: '4',
      ry: '4',
      'data-line-id': hit.id,
    });
    el.addEventListener('pointerenter', () => {
      lensHoveredLine = hit.id;
      updateDigitalHoverClasses();
      updateLensTooltip(hit, true);
    });
    el.addEventListener('pointerleave', () => {
      if (lensHoveredLine === hit.id) {
        lensHoveredLine = null;
        updateDigitalHoverClasses();
        updateLensTooltip(null, true);
      }
    });
    el.addEventListener('pointerdown', e => {
      e.stopPropagation();
      if (lensSelectedLines.has(hit.id)) lensSelectedLines.delete(hit.id);
      else lensSelectedLines.add(hit.id);
      highlightLineInTextarea(hit.id);
      updateDigitalHoverClasses();
      updateLensTooltip(hit, true);
    });
    svg.append(el);
  }
  // In compare mode, pointer events pass through #compareOverlay which hit-tests activeDigitalLineHits
  svg.style.pointerEvents = imageViewMode === 'digital' ? 'none' : 'none';
  svg.style.display = 'block';
}

function renderImageStage() {
  const d = drafts.find(x => x.id === selected);
  const stage = $('originalStage');
  const img = $('originalImage');
  const rectifiedLayer = $('rectifiedLayer');
  const digitalLayer = $('digitalLayer');
  const digitalHoverSvg = $('digitalHoverSvg');
  const compareOverlay = $('compareOverlay');

  if (!d || stage.hidden || !img.naturalWidth) {
    rectifiedLayer.hidden = true;
    digitalLayer.hidden = true;
    digitalHoverSvg.style.display = 'none';
    compareOverlay.hidden = true;
    $('lensSvg').style.display = 'none';
    $('lensFloatingBar').hidden = true;
    $('lensTooltip').hidden = true;
    activeDigitalLineHits = [];
    activeFlatRect = null;
    return;
  }

  if (imageViewMode === 'original') {
    rectifiedLayer.hidden = true;
    digitalLayer.hidden = true;
    digitalHoverSvg.style.display = 'none';
    compareOverlay.hidden = true;
    img.style.visibility = 'visible';
    activeDigitalLineHits = [];
    activeFlatRect = null;
    renderLensOverlay();
    return;
  }

  // Hide original un-warped photo & Lens handles in 90-deg flat Word / Đối chiếu modes
  img.style.visibility = 'hidden';
  $('lensSvg').style.display = 'none';
  $('lensFloatingBar').hidden = true;

  const lensData = getActiveLensData(d);
  const activeQuad = lensData?.paperDetected && Array.isArray(lensData.paperQuad) && lensData.paperQuad.length === 4
    ? lensData.paperQuad
    : null;
  const flatSize = computeQuadFlatSize(activeQuad, img.naturalWidth, img.naturalHeight);
  const pad = 10;
  const innerW = Math.max(40, stage.clientWidth - pad * 2);
  const innerH = Math.max(40, stage.clientHeight - pad * 2);
  const fitted = computeContainedRect(innerW, innerH, flatSize.width, flatSize.height);
  if (fitted.width < 10 || fitted.height < 10) return;
  const flatRect = {
    left: fitted.left + pad,
    top: fitted.top + pad,
    width: fitted.width,
    height: fitted.height,
    scale: fitted.scale,
  };

  positionOverlayBox(digitalLayer, flatRect);
  digitalLayer.hidden = false;
  const { lineHits } = renderDigitalDocument($('digitalCanvas'), {
    text: d.text ?? '',
    lens: d.lens || null,
    paperQuad: activeQuad,
    cssWidth: flatRect.width,
    cssHeight: flatRect.height,
    sourceWidth: lensData?.sourceWidth || img.naturalWidth,
    sourceHeight: lensData?.sourceHeight || img.naturalHeight,
    isLight: document.body.classList.contains('light'),
  });
  renderDigitalHoverLayer(flatRect, lineHits);

  if (imageViewMode === 'digital') {
    rectifiedLayer.hidden = true;
    digitalLayer.style.clipPath = '';
    compareOverlay.hidden = true;
  } else {
    // Đối chiếu mode: 90-deg perspective-warped flat photo on RIGHT (X..100%), matching 90-deg Word sheet on LEFT (0..X%)
    const warped = warpImageQuadToFlatCanvas(img, activeQuad, 1100);
    if (warped) {
      positionOverlayBox(rectifiedLayer, flatRect);
      rectifiedLayer.hidden = false;
      drawRectifiedPhoto($('rectifiedCanvas'), warped, flatRect.width, flatRect.height);
    } else {
      rectifiedLayer.hidden = true;
      img.style.visibility = 'visible';
    }
    positionOverlayBox(compareOverlay, flatRect);
    compareOverlay.hidden = false;
    applyCompareSplit(compareSplit);
  }
}

/* Interactive drag, keyboard, AND line-hover glow support for Đối chiếu slider */
function updateCompareFromPointer(clientX) {
  const overlay = $('compareOverlay');
  const r = overlay.getBoundingClientRect();
  if (r.width <= 0) return;
  const pct = ((clientX - r.left) / r.width) * 100;
  applyCompareSplit(pct);
}

function hitTestFlatLine(clientX, clientY) {
  if (!activeFlatRect || !activeDigitalLineHits.length) return null;
  const r = $('compareOverlay').getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  const fx = clientX - r.left;
  const fy = clientY - r.top;
  for (const hit of activeDigitalLineHits) {
    if (fx >= hit.x && fx <= hit.x + hit.w && fy >= hit.y && fy <= hit.y + hit.h) {
      return hit;
    }
  }
  return null;
}

$('compareOverlay').addEventListener('pointerdown', e => {
  e.stopPropagation();
  e.preventDefault();
  compareDragging = true;
  $('compareOverlay').classList.add('dragging');
  $('compareOverlay').setPointerCapture(e.pointerId);
  updateCompareFromPointer(e.clientX);
});
$('compareOverlay').addEventListener('pointermove', e => {
  if (compareDragging) {
    e.stopPropagation();
    updateCompareFromPointer(e.clientX);
    return;
  }
  const hit = hitTestFlatLine(e.clientX, e.clientY);
  const nextId = hit ? hit.id : null;
  if (nextId !== lensHoveredLine) {
    lensHoveredLine = nextId;
    updateDigitalHoverClasses();
    updateLensTooltip(hit, true);
  }
});
$('compareOverlay').addEventListener('pointerleave', () => {
  if (lensHoveredLine !== null) {
    lensHoveredLine = null;
    updateDigitalHoverClasses();
    updateLensTooltip(null, true);
  }
});
$('compareOverlay').addEventListener('pointerup', e => {
  if (!compareDragging) return;
  e.stopPropagation();
  $('compareOverlay').classList.remove('dragging');
  setTimeout(() => { compareDragging = false; }, 0);
});
$('compareOverlay').addEventListener('pointercancel', () => {
  $('compareOverlay').classList.remove('dragging');
  compareDragging = false;
});
$('compareDivider').addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft') { e.preventDefault(); applyCompareSplit(compareSplit - 5); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); applyCompareSplit(compareSplit + 5); }
  else if (e.key === 'Home') { e.preventDefault(); applyCompareSplit(0); }
  else if (e.key === 'End') { e.preventDefault(); applyCompareSplit(100); }
});

/* ---------- Draggable Google Lens Paper Frame & Text Highlight Overlay ---------- */
function highlightLineInTextarea(lineIdx1Based) {
  const ta = $('text');
  if (!ta || !ta.value) return;
  const lines = ta.value.split('\n');
  const idx = lineIdx1Based - 1;
  if (idx < 0 || idx >= lines.length) return;
  let start = 0;
  for (let i = 0; i < idx; i++) start += lines[i].length + 1;
  const end = start + lines[idx].length;
  ta.focus({ preventScroll: true });
  ta.setSelectionRange(start, end);
  const ratio = lines.length > 1 ? idx / (lines.length - 1) : 0;
  ta.scrollTop = Math.max(0, ratio * (ta.scrollHeight - ta.clientHeight));
}

function updateLensTooltip(line, allowNonOriginal = false) {
  const tip = $('lensTooltip');
  if (!line || (!allowNonOriginal && (!lensEnabled || imageViewMode !== 'original'))) {
    tip.hidden = true;
    return;
  }
  tip.replaceChildren();
  const badge = document.createElement('span');
  badge.className = 'lens-tip-idx';
  badge.textContent = `#${line.id}`;
  const text = document.createElement('span');
  text.className = 'lens-tip-text';
  text.textContent = line.text || '';
  tip.append(badge, text);
  if (line.changed) {
    const bp = document.createElement('span');
    bp.className = 'lens-tip-badge';
    bp.textContent = 'BARTpho';
    tip.append(bp);
  }
  tip.hidden = false;
}

async function applyLensQuadCrop(autoSend = false) {
  const d = drafts.find(x => x.id === selected);
  const img = $('originalImage');
  if (!d || !img?.naturalWidth) return;
  const lensData = getActiveLensData(d);
  if (!lensData?.paperQuad || lensData.paperQuad.length !== 4) return;
  const out = cropImageToQuad(img, lensData.paperQuad);
  if (!out) return;
  const cropped = await saveCanvas(out, `LensCrop-${Date.now()}.png`, d.id);
  if (autoSend && verified && cropped) {
    void enqueueAutoSend(cropped);
    toast('Đã cắt theo khung Lens và tự động gửi OCR');
  }
}

function renderLensFloatingBar(lensData, rect) {
  const bar = $('lensFloatingBar');
  const d = drafts.find(x => x.id === selected);
  if (!d || !lensEnabled || imageViewMode !== 'original' || !lensData || !rect || rect.width < 40) {
    bar.hidden = true;
    return;
  }
  const lines = Array.isArray(lensData.lines) ? lensData.lines : [];
  const hasLines = lines.length > 0;
  const isCustom = Boolean(customPaperQuads.has(d.id));
  if (!hasLines && !lensData.paperDetected && !isCustom) {
    bar.hidden = true;
    return;
  }

  bar.replaceChildren();
  const addResetBtn = () => {
    if (!isCustom) return;
    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'lens-pill-btn';
    resetBtn.textContent = 'Đặt lại';
    resetBtn.title = 'Khôi phục khung giấy tự động nhận diện';
    resetBtn.onclick = e => {
      e.stopPropagation();
      customPaperQuads.delete(d.id);
      persistCustomQuads();
      lensSelectedLines.clear();
      renderLensOverlay();
    };
    bar.append(resetBtn);
  };
  const addCropSendBtn = labelText => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'lens-pill-btn primary-lens';
    btn.textContent = labelText;
    btn.title = verified
      ? 'Cắt ảnh theo khung Lens hiện tại và tự động gửi OCR'
      : 'Cắt ảnh theo khung Lens hiện tại thành bản nháp mới';
    btn.onclick = e => {
      e.stopPropagation();
      run(() => applyLensQuadCrop(verified));
    };
    bar.append(btn);
  };

  if (!hasLines) {
    const labelSpan = document.createElement('span');
    labelSpan.textContent = isCustom
      ? '✦ Khung Lens đã chỉnh'
      : '✦ Kéo 4 góc để chỉnh khung giấy';
    bar.append(labelSpan);
    addCropSendBtn(verified ? 'Cắt & Gửi' : 'Cắt khung');
    addResetBtn();
  } else if (lensSelectedLines.size === 0) {
    const labelSpan = document.createElement('span');
    labelSpan.textContent = `Chọn văn bản · ${lines.length} dòng`;
    const selAll = document.createElement('button');
    selAll.type = 'button';
    selAll.className = 'lens-pill-btn';
    selAll.textContent = 'Chọn tất cả';
    selAll.onclick = e => {
      e.stopPropagation();
      lines.forEach(l => lensSelectedLines.add(l.id));
      renderLensOverlay();
    };
    bar.append(labelSpan, selAll);
    if (isCustom) addCropSendBtn(verified ? 'Cắt & Gửi lại' : 'Cắt khung');
    addResetBtn();
  } else {
    const chosen = lines.filter(l => lensSelectedLines.has(l.id));
    const labelSpan = document.createElement('span');
    labelSpan.textContent = `Đã chọn ${chosen.length}/${lines.length} dòng`;
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'lens-pill-btn primary-lens';
    copyBtn.textContent = 'Sao chép';
    copyBtn.onclick = e => {
      e.stopPropagation();
      const text = chosen.map(l => l.text).join('\n');
      run(async () => {
        await navigator.clipboard.writeText(text);
        toast(`Đã sao chép ${chosen.length} dòng đã chọn`);
      });
    };
    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'lens-pill-btn';
    clearBtn.textContent = 'Bỏ chọn';
    clearBtn.onclick = e => {
      e.stopPropagation();
      lensSelectedLines.clear();
      renderLensOverlay();
    };
    bar.append(labelSpan, copyBtn, clearBtn);
    if (isCustom) addCropSendBtn(verified ? 'Cắt & Gửi lại' : 'Cắt khung');
    addResetBtn();
  }

  const stage = $('originalStage');
  const srcW = lensData.sourceWidth || $('originalImage').naturalWidth || 1;
  const srcH = lensData.sourceHeight || $('originalImage').naturalHeight || 1;
  let anchorX = rect.left + rect.width / 2;
  let anchorY = Math.max(8, rect.top + 8);
  if (Array.isArray(lensData.paperQuad) && lensData.paperQuad.length === 4) {
    const pb = polygonBounds(lensData.paperQuad);
    anchorX = rect.left + (pb.cx / srcW) * rect.width;
    const quadTop = rect.top + (pb.minY / srcH) * rect.height;
    anchorY = quadTop > 44 ? quadTop - 38 : Math.max(8, quadTop + 8);
  }
  anchorX = Math.max(120, Math.min(stage.clientWidth - 120, anchorX));
  anchorY = Math.max(6, Math.min(stage.clientHeight - 42, anchorY));
  bar.style.left = `${Math.round(anchorX)}px`;
  bar.style.top = `${Math.round(anchorY)}px`;
  bar.hidden = false;
}

function beginLensHandleDrag(e, { type, index, quad, srcW, srcH, draftId }) {
  e.stopPropagation();
  e.preventDefault();
  const svg = $('lensSvg');
  const svgRect = svg.getBoundingClientRect();
  if (svgRect.width < 10 || svgRect.height < 10) return;
  const ix = ((e.clientX - svgRect.left) / svgRect.width) * srcW;
  const iy = ((e.clientY - svgRect.top) / svgRect.height) * srcH;
  lensDragDidMove = true;
  lensHandleDrag = {
    type,
    index,
    pointerId: e.pointerId,
    startX: ix,
    startY: iy,
    startQuad: quad.map(([x, y]) => [x, y]),
    srcW,
    srcH,
    draftId,
  };
  renderLensOverlay();
}

function renderLensOverlay() {
  const d = drafts.find(x => x.id === selected);
  const svg = $('lensSvg');
  const stage = $('originalStage');
  const img = $('originalImage');
  $('lensToggleBtn').classList.toggle('active', lensEnabled);

  if (!d || !lensEnabled || imageViewMode !== 'original' || stage.hidden || !img.naturalWidth) {
    svg.style.display = 'none';
    svg.replaceChildren();
    $('lensFloatingBar').hidden = true;
    $('lensTooltip').hidden = true;
    return;
  }

  const lensData = getActiveLensData(d);
  const hasLines = Boolean(lensData?.lines?.length);
  const hasPaper = Boolean(lensData?.paperQuad?.length === 4);
  $('original').classList.toggle('lens-interactive', Boolean(lensEnabled && (hasLines || hasPaper)));

  if (!hasLines && !hasPaper) {
    svg.style.display = 'none';
    svg.replaceChildren();
    $('lensFloatingBar').hidden = true;
    $('lensTooltip').hidden = true;
    return;
  }

  const srcW = lensData.sourceWidth || img.naturalWidth;
  const srcH = lensData.sourceHeight || img.naturalHeight;
  const rect = computeContainedRect(stage.clientWidth, stage.clientHeight, img.naturalWidth, img.naturalHeight);
  if (rect.width < 10 || rect.height < 10) {
    svg.style.display = 'none';
    return;
  }

  positionOverlayBox(svg, rect);
  svg.setAttribute('viewBox', `0 0 ${srcW} ${srcH}`);
  svg.replaceChildren();

  const quad = hasPaper ? (orderQuad(lensData.paperQuad) || lensData.paperQuad) : null;
  const isCustom = Boolean(customPaperQuads.has(d.id));
  const isDraggingThis = Boolean(lensHandleDrag && lensHandleDrag.draftId === d.id);

  // 1) Outside-paper dark scrim (skipped on untouched default full-frame scan)
  if (quad && (lensData.paperDetected || hasLines || isCustom)) {
    const scrimD = quadScrimPath(srcW, srcH, quad);
    if (scrimD) svg.append(svgEl('path', { class: 'lens-scrim', d: scrimD }));
  }

  // 2) Frosted white/sky-blue highlight pills over every recognized text line
  if (hasLines) {
    const linePad = Math.max(2, Math.min(srcW, srcH) * 0.003);
    const strokeW = Math.max(1.2, Math.min(srcW, srcH) * 0.0018);
    for (const line of lensData.lines) {
      if (!Array.isArray(line.polygon) || line.polygon.length < 3) continue;
      const expanded = expandPolygon(line.polygon, linePad);
      const pts = expanded.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
      const isSel = lensSelectedLines.has(line.id);
      const isHov = lensHoveredLine === line.id;
      const poly = svgEl('polygon', {
        class: `lens-line${isSel ? ' selected' : ''}${isHov ? ' hovered' : ''}`,
        points: pts,
        'stroke-width': strokeW.toFixed(2),
        'data-line-id': line.id,
      });
      poly.addEventListener('pointerdown', e => {
        e.stopPropagation();
        lensDragging = true;
        lensDragDidMove = true;
        lensDragAction = lensSelectedLines.has(line.id) ? 'remove' : 'add';
        if (lensDragAction === 'add') lensSelectedLines.add(line.id);
        else lensSelectedLines.delete(line.id);
        highlightLineInTextarea(line.id);
        updateLensTooltip(line);
        renderLensOverlay();
      });
      poly.addEventListener('pointerenter', () => {
        lensHoveredLine = line.id;
        poly.classList.add('hovered');
        updateLensTooltip(line);
        if (lensDragging) {
          if (lensDragAction === 'add') lensSelectedLines.add(line.id);
          else lensSelectedLines.delete(line.id);
          renderLensOverlay();
        }
      });
      poly.addEventListener('pointerleave', () => {
        poly.classList.remove('hovered');
        if (lensHoveredLine === line.id) {
          lensHoveredLine = null;
          updateLensTooltip(null);
        }
      });
      svg.append(poly);
    }
  }

  // 3) Crisp white rounded Google Lens corner brackets + draggable corner & edge handles
  if (quad) {
    const pb = polygonBounds(quad);
    const minDim = Math.max(40, Math.min(pb.maxX - pb.minX, pb.maxY - pb.minY));
    const armLen = Math.min(minDim * 0.14, Math.min(srcW, srcH) * 0.095);
    const cornerR = Math.max(8, armLen * 0.42);
    const bracketW = Math.max(4, Math.min(srcW, srcH) * 0.011);

    if (isDraggingThis || isCustom) {
      svg.append(svgEl('polygon', {
        class: 'lens-quad-guide',
        points: quad.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '),
        'stroke-width': Math.max(1.8, bracketW * 0.25).toFixed(1),
      }));
    }

    for (const dPath of buildCornerBracketPaths(quad, armLen, cornerR)) {
      svg.append(svgEl('path', { class: 'lens-bracket', d: dPath, 'stroke-width': bracketW.toFixed(1) }));
    }

    // 4 edge-midpoint drag handles (drag an entire side of the Lens quad)
    const pillLen = Math.max(18, Math.min(srcW, srcH) * 0.042);
    const pillTh = Math.max(5, bracketW * 0.65);
    const edgeHitR = Math.max(18, Math.min(srcW, srcH) * 0.032);
    for (let i = 0; i < 4; i++) {
      const a = quad[i];
      const b = quad[(i + 1) % 4];
      const mx = (a[0] + b[0]) / 2;
      const my = (a[1] + b[1]) / 2;
      const angDeg = (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
      const grp = svgEl('g', {
        class: `lens-edge-group${isDraggingThis && lensHandleDrag.type === 'edge' && lensHandleDrag.index === i ? ' dragging' : ''}`,
        transform: `translate(${mx.toFixed(1)} ${my.toFixed(1)}) rotate(${angDeg.toFixed(1)})`,
      });
      const pill = svgEl('rect', {
        class: 'lens-edge-pill',
        x: (-pillLen / 2).toFixed(1),
        y: (-pillTh / 2).toFixed(1),
        width: pillLen.toFixed(1),
        height: pillTh.toFixed(1),
        rx: (pillTh / 2).toFixed(1),
        'stroke-width': Math.max(1.2, bracketW * 0.18).toFixed(1),
      });
      const hit = svgEl('rect', {
        class: 'lens-edge-hit',
        x: (-pillLen * 0.9).toFixed(1),
        y: (-edgeHitR).toFixed(1),
        width: (pillLen * 1.8).toFixed(1),
        height: (edgeHitR * 2).toFixed(1),
        'data-lens-edge': i,
      });
      hit.addEventListener('pointerdown', e => beginLensHandleDrag(e, { type: 'edge', index: i, quad, srcW, srcH, draftId: d.id }));
      grp.append(pill, hit);
      svg.append(grp);
    }

    // 4 corner drag handles (positioned right over the 4 rounded brackets)
    const dotR = Math.max(5.5, bracketW * 0.72);
    const hitR = Math.max(24, Math.min(srcW, srcH) * 0.045);
    for (let i = 0; i < 4; i++) {
      const [cx, cy] = quad[i];
      const grp = svgEl('g', {
        class: `lens-corner-group${isDraggingThis && lensHandleDrag.type === 'corner' && lensHandleDrag.index === i ? ' dragging' : ''}`,
      });
      const dot = svgEl('circle', {
        class: 'lens-corner-dot',
        cx: cx.toFixed(1),
        cy: cy.toFixed(1),
        r: dotR.toFixed(1),
        'stroke-width': Math.max(1.6, bracketW * 0.22).toFixed(1),
      });
      const hit = svgEl('circle', {
        class: 'lens-corner-hit',
        cx: cx.toFixed(1),
        cy: cy.toFixed(1),
        r: hitR.toFixed(1),
        'data-lens-corner': i,
      });
      hit.addEventListener('pointerdown', e => beginLensHandleDrag(e, { type: 'corner', index: i, quad, srcW, srcH, draftId: d.id }));
      grp.append(dot, hit);
      svg.append(grp);
    }
  }

  svg.style.display = 'block';
  renderLensFloatingBar(lensData, rect);
}

window.addEventListener('pointermove', e => {
  if (!lensHandleDrag) return;
  const svg = $('lensSvg');
  const svgRect = svg.getBoundingClientRect();
  if (svgRect.width < 10 || svgRect.height < 10) return;
  const { type, index, startX, startY, startQuad, srcW, srcH, draftId } = lensHandleDrag;
  const ix = Math.max(0, Math.min(srcW, ((e.clientX - svgRect.left) / svgRect.width) * srcW));
  const iy = Math.max(0, Math.min(srcH, ((e.clientY - svgRect.top) / svgRect.height) * srcH));
  const next = startQuad.map(([x, y]) => [x, y]);

  if (type === 'corner') {
    next[index] = [Math.round(ix * 10) / 10, Math.round(iy * 10) / 10];
  } else {
    const dx = ix - startX;
    const dy = iy - startY;
    const j = (index + 1) % 4;
    next[index] = [
      Math.round(Math.max(0, Math.min(srcW, startQuad[index][0] + dx)) * 10) / 10,
      Math.round(Math.max(0, Math.min(srcH, startQuad[index][1] + dy)) * 10) / 10,
    ];
    next[j] = [
      Math.round(Math.max(0, Math.min(srcW, startQuad[j][0] + dx)) * 10) / 10,
      Math.round(Math.max(0, Math.min(srcH, startQuad[j][1] + dy)) * 10) / 10,
    ];
  }

  const b = polygonBounds(next);
  if (b.maxX - b.minX < 40 || b.maxY - b.minY < 40) return;
  const ordered = orderQuad(next) || next;
  customPaperQuads.set(draftId, ordered);

  // Dynamically select text lines inside the adjusted Lens quad (like Google Lens partial box)
  const cur = drafts.find(x => x.id === draftId);
  if (cur?.lens?.lines?.length) {
    lensSelectedLines.clear();
    for (const line of linesInsideQuad(cur.lens.lines, ordered)) {
      lensSelectedLines.add(line.id);
    }
  }
  renderLensOverlay();
});

window.addEventListener('pointerup', () => {
  if (lensHandleDrag) {
    lensHandleDrag = null;
    persistCustomQuads();
    renderLensOverlay();
    setTimeout(() => { lensDragDidMove = false; }, 0);
  }
  if (lensDragging) {
    lensDragging = false;
    setTimeout(() => { lensDragDidMove = false; }, 0);
  }
});

const originalStageObserver = new ResizeObserver(() => {
  if (!$('originalStage').hidden) renderImageStage();
});
originalStageObserver.observe($('originalStage'));

/* ---------- Interactive 5-Stage Visual Pipeline Demo ---------- */
async function prefetchPipeline(d) {
  if (!d?.id || !d.jobId) return null;
  const cached = pipelineCache.get(d.id);
  if (cached && cached.jobId === d.jobId) return cached.data;
  try {
    const data = await invoke('draft_pipeline', { id: d.id });
    if (data && typeof data === 'object') {
      pipelineCache.set(d.id, { jobId: d.jobId, data });
      if (selected === d.id) renderPipelineMiniBar();
      return data;
    }
  } catch {
    /* server may be older or result expired; handled gracefully when user clicks open */
  }
  return null;
}

function renderPipelineMiniBar() {
  const bar = $('pipelineMiniBar');
  const stepsEl = $('pipelineMiniSteps');
  const cur = drafts.find(x => x.id === selected);
  if (!demoPipelineMode || !cur) {
    bar.hidden = true;
    document.body.classList.remove('has-pipeline-bar');
    return;
  }
  bar.hidden = false;
  document.body.classList.add('has-pipeline-bar');
  stepsEl.replaceChildren();
  const cached = pipelineCache.get(cur.id);
  const pipe = cached && cached.jobId === cur.jobId ? cached.data : null;
  const t = pipe?.timings;
  const lineCount = pipe?.lines?.length ?? cur.lens?.lines?.length ?? null;
  const chips = [
    { step: 0, label: '① Vùng giấy', meta: pipe ? (pipe.route === 'scanner' ? 'Scanner' : 'Legacy') : (cur.state === 'succeeded' ? 'Sẵn sàng' : 'Chờ gửi') },
    { step: 1, label: '② Tách mực', meta: t ? formatMs(t.preprocessMs) : 'Sauvola' },
    { step: 2, label: '③ Tách dòng', meta: lineCount != null ? `${lineCount} dòng · ${t ? formatMs(t.segmentMs) : ''}`.replace(/ · $/, '') : 'Native' },
    { step: 3, label: '④ V2c + ML_s44', meta: t ? formatMs(t.recognitionMs) : '64px' },
    { step: 4, label: '⑤ BARTpho', meta: pipe ? (pipe.corrected ? `${formatMs(t.correctionMs)}` : 'Tắt') : ($('correct')?.checked ? 'Bật' : 'Tắt') },
  ];
  chips.forEach((c, idx) => {
    if (idx > 0) {
      const arrow = document.createElement('span');
      arrow.className = 'pipe-mini-arrow';
      arrow.textContent = '→';
      stepsEl.append(arrow);
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pipe-mini-chip';
    const b = document.createElement('b');
    b.textContent = c.label;
    const sm = document.createElement('small');
    sm.textContent = c.meta;
    btn.append(b, sm);
    btn.disabled = cur.state !== 'succeeded';
    btn.onclick = () => run(() => openPipelineDialog(c.step, 'step'));
    stepsEl.append(btn);
  });
  $('openPipelineFromBar').disabled = cur.state !== 'succeeded';
}

function stopPipeAutoPlay() {
  if (pipeAutoTimer) {
    clearInterval(pipeAutoTimer);
    pipeAutoTimer = null;
  }
  $('pipeAutoPlay').textContent = '▶ Tự chạy';
}

function buildDiffFragment(raw, fixed) {
  const frag = document.createDocumentFragment();
  const segs = diffWords(raw, fixed);
  segs.forEach((seg, i) => {
    if (i > 0) frag.append(document.createTextNode(' '));
    if (seg.type === 'eq') {
      frag.append(document.createTextNode(seg.text));
    } else {
      const span = document.createElement('span');
      span.className = seg.type === 'del' ? 'diff-del' : 'diff-ins';
      span.textContent = seg.text;
      frag.append(span);
    }
  });
  return frag;
}

function buildStageCard(stepIdx, pipe, origUrl) {
  const card = document.createElement('section');
  card.className = 'pipe-stage-card';
  const t = pipe.timings || {};
  const lines = Array.isArray(pipe.lines) ? pipe.lines : [];

  const head = document.createElement('div');
  head.className = 'pipe-stage-head';
  const h3 = document.createElement('h3');
  const tag = document.createElement('span');
  tag.className = 'pipe-stage-tag';

  if (stepIdx === 0) {
    tag.textContent = 'KHÂU 1 / 5';
    h3.append(tag, document.createTextNode('Định vị vùng giấy & Phân loại nền (Paper Detection)'));
    const dur = document.createElement('span');
    dur.className = 'muted';
    dur.textContent = `Tiền xử lý: ${formatMs(t.preprocessMs)}`;
    head.append(h3, dur);
    card.append(head);

    const kpis = document.createElement('div');
    kpis.className = 'pipe-kpi-row';
    const items = [
      ['Nhánh xử lý', routeLabel(pipe.route)],
      ['Ảnh gốc', `${pipe.sourceWidth} × ${pipe.sourceHeight} px`],
      ['Ảnh làm việc', `${pipe.workWidth} × ${pipe.workHeight} px`],
      ['Vùng giấy', pipe.paperDetected ? 'Phát hiện tự động (Scanner)' : 'Toàn khung (Legacy)'],
    ];
    for (const [k, v] of items) {
      const el = document.createElement('span');
      el.className = 'pipe-kpi';
      el.innerHTML = `${k}:<b></b>`;
      el.querySelector('b').textContent = v;
      kpis.append(el);
    }
    card.append(kpis);

    if (Array.isArray(pipe.reasons) && pipe.reasons.length) {
      const p = document.createElement('p');
      p.className = 'muted';
      p.style.margin = '0';
      p.style.fontSize = '12px';
      p.textContent = `Lý do chọn nhánh: ${pipe.reasons.map(translateReason).join(' · ')}`;
      card.append(p);
    }

    const grid = document.createElement('div');
    grid.className = 'pipe-img-grid';
    const box1 = document.createElement('div');
    box1.className = 'pipe-img-box';
    box1.innerHTML = '<header><span>Ảnh đầu vào gốc</span><small class="muted">Sau định hướng EXIF</small></header>';
    const img1 = document.createElement('img');
    img1.src = origUrl || '';
    img1.alt = 'Ảnh gốc';
    box1.append(img1);

    const box2 = document.createElement('div');
    box2.className = 'pipe-img-box';
    box2.innerHTML = '<header><span>Bản đồ phân vùng giấy & lọc nền</span><small class="muted">Native Paper Mask</small></header>';
    const img2 = document.createElement('img');
    img2.src = pipe.previews?.paperOverlay || origUrl || '';
    img2.alt = 'Bản đồ nhận diện vùng giấy';
    const leg = document.createElement('div');
    leg.className = 'pipe-legend-dots';
    leg.innerHTML =
      '<span><i style="background:#72e68a"></i>Khung giấy giữ lại</span>' +
      '<span><i style="background:#eb4438"></i>Nền ngoài giấy bị loại</span>' +
      '<span><i style="background:#f5a82a"></i>Nhiễu / nét mờ bị lọc</span>';
    box2.append(img2, leg);
    grid.append(box1, box2);
    card.append(grid);
  } else if (stepIdx === 1) {
    tag.textContent = 'KHÂU 2 / 5';
    h3.append(tag, document.createTextNode('Khử bóng nền & Tách nét mực (Background Correction + Sauvola/Otsu)'));
    const dur = document.createElement('span');
    dur.className = 'muted';
    dur.textContent = `Thời gian tiền xử lý: ${formatMs(t.preprocessMs)}`;
    head.append(h3, dur);
    card.append(head);

    const grid = document.createElement('div');
    grid.className = 'pipe-img-grid';
    const box1 = document.createElement('div');
    box1.className = 'pipe-img-box';
    box1.innerHTML = '<header><span>Ảnh lọc nền giữ sắc độ mực (Ink Only)</span><small class="muted">Khử bóng đổ & vân bàn</small></header>';
    const img1 = document.createElement('img');
    img1.src = pipe.previews?.inkOnly || '';
    img1.alt = 'Ảnh lọc nền giữ mực';
    box1.append(img1);

    const box2 = document.createElement('div');
    box2.className = 'pipe-img-box';
    box2.innerHTML = '<header><span>Mặt nạ nét mực nhị phân (Ink Mask)</span><small class="muted">Đầu vào bộ phân đoạn dòng</small></header>';
    const img2 = document.createElement('img');
    img2.src = pipe.previews?.inkMask || '';
    img2.alt = 'Mặt nạ nét mực nhị phân';
    box2.append(img2);
    grid.append(box1, box2);
    card.append(grid);
  } else if (stepIdx === 2) {
    tag.textContent = 'KHÂU 3 / 5';
    h3.append(tag, document.createTextNode(`Phân đoạn dòng thích nghi (Native Adaptive Segmentation · ${lines.length} dòng)`));
    const dur = document.createElement('span');
    dur.className = 'muted';
    dur.textContent = `Tách dòng: ${formatMs(t.segmentMs)}`;
    head.append(h3, dur);
    card.append(head);

    const hint = document.createElement('p');
    hint.className = 'muted';
    hint.style.margin = '0';
    hint.style.fontSize = '12px';
    hint.textContent = 'Di chuột lên từng khung dòng trên ảnh để xem văn bản đã nhận dạng tương ứng.';
    card.append(hint);

    const stageWrap = document.createElement('div');
    stageWrap.className = 'pipe-seg-stage';
    const bgImg = document.createElement('img');
    bgImg.src = origUrl || '';
    bgImg.alt = 'Kết quả phân đoạn dòng';
    const segSvg = svgEl('svg', { class: 'pipe-seg-svg', viewBox: `0 0 ${pipe.sourceWidth} ${pipe.sourceHeight}` });
    stageWrap.append(bgImg, segSvg);
    card.append(stageWrap);

    const previewLine = document.createElement('div');
    previewLine.className = 'pipe-kpi';
    previewLine.textContent = lines.length
      ? `Dòng #1: ${lines[0].text}`
      : 'Không có dòng nào được phân đoạn.';
    card.append(previewLine);

    const syncSegSvg = () => {
      const r = computeContainedRect(stageWrap.clientWidth, stageWrap.clientHeight, bgImg.naturalWidth || pipe.sourceWidth, bgImg.naturalHeight || pipe.sourceHeight);
      segSvg.style.left = `${r.left}px`;
      segSvg.style.top = `${r.top}px`;
      segSvg.style.width = `${r.width}px`;
      segSvg.style.height = `${r.height}px`;
    };
    const strokeW = Math.max(2, Math.min(pipe.sourceWidth, pipe.sourceHeight) * 0.003);
    const fontSize = Math.max(14, Math.min(pipe.sourceWidth, pipe.sourceHeight) * 0.018);
    lines.forEach((l, idx) => {
      if (!Array.isArray(l.polygon) || l.polygon.length < 3) return;
      const color = LINE_COLORS[idx % LINE_COLORS.length];
      const pts = l.polygon.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
      const poly = svgEl('polygon', {
        class: 'pipe-seg-poly',
        points: pts,
        fill: color,
        stroke: color,
        'stroke-width': strokeW.toFixed(1),
      });
      poly.addEventListener('pointerenter', () => {
        previewLine.textContent = `Dòng #${l.id} (${formatMs(l.ms)}): ${l.text}`;
      });
      const b = polygonBounds(l.polygon);
      const txt = svgEl('text', {
        class: 'pipe-seg-label',
        x: (b.minX + 4).toFixed(1),
        y: Math.max(fontSize, b.minY + fontSize * 0.85).toFixed(1),
        fill: color,
        'font-size': fontSize.toFixed(1),
      });
      txt.textContent = `#${l.id}`;
      segSvg.append(poly, txt);
    });
    bgImg.onload = syncSegSvg;
    requestAnimationFrame(syncSegSvg);
    new ResizeObserver(syncSegSvg).observe(stageWrap);
  } else if (stepIdx === 3) {
    tag.textContent = 'KHÂU 4 / 5';
    h3.append(tag, document.createTextNode(`Chuẩn hóa V2c (64px) & Nhận dạng ${pipe.model || 'ML_s44'} (${pipe.device || 'GPU/CPU'})`));
    const dur = document.createElement('span');
    dur.className = 'muted';
    dur.textContent = `Tổng suy luận ML_s44: ${formatMs(t.recognitionMs)}`;
    head.append(h3, dur);
    card.append(head);

    const list = document.createElement('div');
    list.className = 'pipe-line-list';
    for (const l of lines) {
      const row = document.createElement('div');
      row.className = 'pipe-line-row';
      const idxEl = document.createElement('span');
      idxEl.className = 'pipe-line-idx';
      idxEl.textContent = `#${l.id}`;
      let stripEl;
      if (l.v2cThumb) {
        stripEl = document.createElement('img');
        stripEl.className = 'pipe-v2c-img';
        stripEl.src = l.v2cThumb;
        stripEl.alt = `Ảnh dòng #${l.id} chuẩn hóa V2c`;
      } else {
        stripEl = document.createElement('span');
        stripEl.className = 'muted';
        stripEl.style.fontSize = '11px';
        stripEl.textContent = '(Ẩn thumbnail > 40 dòng)';
      }
      const txtEl = document.createElement('span');
      txtEl.className = 'pipe-line-text';
      txtEl.textContent = l.rawText ?? l.text ?? '';
      const msEl = document.createElement('span');
      msEl.className = 'pipe-line-ms';
      msEl.textContent = formatMs(l.ms);
      row.append(idxEl, stripEl, txtEl, msEl);
      list.append(row);
    }
    card.append(list);
  } else {
    tag.textContent = 'KHÂU 5 / 5';
    h3.append(tag, document.createTextNode('Hậu xử lý Bartpho_v2_fp16 + Edit Guard v3 + Smart Continuation Context'));
    const dur = document.createElement('span');
    dur.className = 'muted';
    dur.textContent = pipe.corrected ? `Nội suy: ${formatMs(t.correctionMs)}` : 'Đã tắt (0 MiB VRAM thêm)';
    head.append(h3, dur);
    card.append(head);

    const changedCount = lines.filter(l => l.changed).length;
    const chunkCount = Array.isArray(pipe.chunks) ? pipe.chunks.length : 0;
    const kpis = document.createElement('div');
    kpis.className = 'pipe-kpi-row';
    const items = [
      ['Trạng thái BARTpho', pipe.corrected ? 'Đã áp dụng (FP16 + Edit Guard v3)' : 'Tắt (chỉ dùng ML_s44)'],
      ['Số dòng được sửa', `${changedCount} / ${lines.length} dòng`],
      ['Cụm ngữ cảnh nối tiếp', pipe.corrected ? `${chunkCount} cụm` : '—'],
      ['Thời gian hậu xử lý', pipe.corrected ? formatMs(t.correctionMs) : '0 ms'],
    ];
    for (const [k, v] of items) {
      const el = document.createElement('span');
      el.className = 'pipe-kpi';
      el.innerHTML = `${k}:<b></b>`;
      el.querySelector('b').textContent = v;
      kpis.append(el);
    }
    card.append(kpis);

    if (!pipe.corrected) {
      const note = document.createElement('p');
      note.className = 'muted';
      note.style.margin = '4px 0';
      note.textContent =
        'Lượt gửi này đang tắt "Nội suy sửa lỗi (BARTpho)" nên giữ nguyên 100% đầu ra ML_s44 (0 MiB VRAM cộng thêm). Hãy tích chọn "Nội suy sửa lỗi (BARTpho)" và gửi lại ảnh để xem so sánh từng từ trước & sau hậu xử lý.';
      card.append(note);
    }

    const diffList = document.createElement('div');
    diffList.className = 'pipe-diff-list';
    for (const l of lines) {
      const row = document.createElement('div');
      row.className = `pipe-diff-row${l.changed ? ' changed' : ''}`;
      const colIdx = document.createElement('div');
      const num = document.createElement('div');
      num.className = 'pipe-line-idx';
      num.style.textAlign = 'left';
      num.textContent = `Dòng #${l.id}`;
      colIdx.append(num);
      if (pipe.corrected && typeof l.chunkIndex === 'number') {
        const cb = document.createElement('span');
        cb.className = 'pipe-chunk-badge';
        cb.textContent = `Cụm #${l.chunkIndex + 1}`;
        colIdx.append(cb);
      }
      const colRaw = document.createElement('div');
      colRaw.className = 'muted';
      colRaw.textContent = l.rawText ?? l.text ?? '';
      const colFix = document.createElement('div');
      if (l.changed) colFix.append(buildDiffFragment(l.rawText, l.text));
      else colFix.textContent = l.text ?? '';
      row.append(colIdx, colRaw, colFix);
      diffList.append(row);
    }
    card.append(diffList);
  }
  return card;
}

function renderPipelineDialogContent() {
  const pipe = activePipelineData;
  const d = activePipelineDraft;
  const body = $('pipelineBody');
  const stepper = $('pipelineStepper');
  const tBar = $('pipelineTimingBar');
  const tLeg = $('pipelineTimingLegend');
  body.replaceChildren();
  stepper.replaceChildren();
  tBar.replaceChildren();
  tLeg.replaceChildren();

  $('pipeModeOverview').classList.toggle('active', pipeViewMode === 'overview');
  $('pipeModeStep').classList.toggle('active', pipeViewMode === 'step');
  $('pipePrev').hidden = pipeViewMode !== 'step';
  $('pipeNext').hidden = pipeViewMode !== 'step';

  if (!pipe) {
    $('pipelineTimingWrap').hidden = true;
    const empty = document.createElement('div');
    empty.className = 'pipe-empty';
    const msg = document.createElement('p');
    msg.textContent =
      'Ảnh này chưa có dữ liệu chi tiết 5 khâu trên Compute Server (có thể đã được gửi trước khi khởi động bản server mới hoặc đã hết hạn lưu tạm).';
    empty.append(msg);
    if (d && verified) {
      const resendBtn = document.createElement('button');
      resendBtn.type = 'button';
      resendBtn.className = 'primary';
      resendBtn.style.marginTop = '10px';
      resendBtn.textContent = '↻ Gửi lại ảnh này để tạo Pipeline & Lens';
      resendBtn.onclick = () => {
        pendingPipelineOpenDraftId = d.id;
        $('pipelineDialog').close();
        void enqueueAutoSend(d);
        toast('Đang gửi lại ảnh — hộp thoại Pipeline sẽ tự mở khi hoàn tất…');
      };
      empty.append(resendBtn);
    }
    body.append(empty);
    return;
  }

  $('pipelineTimingWrap').hidden = false;
  const t = pipe.timings || {};
  const shares = computeTimingShares(t);
  $('pipelineMeta').textContent =
    `${d?.name || 'Tài liệu'} · ${pipe.sourceWidth}×${pipe.sourceHeight} px · ${pipe.device || 'auto'} · Nhánh: ${pipe.route} · Tổng ${formatMs(t.totalMs)}`;

  const stepDefs = [
    { num: 'KHÂU 1', title: 'Định vị giấy', meta: pipe.paperDetected ? 'Scanner' : 'Legacy' },
    { num: 'KHÂU 2', title: 'Khử nền & Mực', meta: formatMs(t.preprocessMs) },
    { num: 'KHÂU 3', title: 'Tách dòng Native', meta: `${pipe.lines?.length ?? 0} dòng · ${formatMs(t.segmentMs)}` },
    { num: 'KHÂU 4', title: 'V2c + ML_s44', meta: formatMs(t.recognitionMs) },
    { num: 'KHÂU 5', title: 'BARTpho + Guard', meta: pipe.corrected ? formatMs(t.correctionMs) : 'Tắt' },
  ];
  stepDefs.forEach((s, idx) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `pipe-step-btn${pipeViewMode === 'step' && pipeActiveStep === idx ? ' active' : ''}`;
    btn.innerHTML = `<span class="step-num">${s.num}</span><strong>${s.title}</strong><small></small>`;
    btn.querySelector('small').textContent = s.meta;
    btn.onclick = () => {
      stopPipeAutoPlay();
      pipeActiveStep = idx;
      if (pipeViewMode === 'overview') {
        const target = body.children[idx];
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else {
        renderPipelineDialogContent();
      }
    };
    stepper.append(btn);
  });

  const timingSegs = [
    { cls: 'pipe-t-pre', color: '#72cfff', label: `Tiền xử lý & tách mực: ${formatMs(t.preprocessMs)} (${shares.preprocessPct}%)`, pct: shares.preprocessPct },
    { cls: 'pipe-t-segm', color: '#f7c873', label: `Phân đoạn dòng: ${formatMs(t.segmentMs)} (${shares.segmentPct}%)`, pct: shares.segmentPct },
    { cls: 'pipe-t-rec', color: '#a6e38a', label: `ML_s44: ${formatMs(t.recognitionMs)} (${shares.recognitionPct}%)`, pct: shares.recognitionPct },
    { cls: 'pipe-t-cor', color: '#c8a2ff', label: `BARTpho: ${pipe.corrected ? `${formatMs(t.correctionMs)} (${shares.correctionPct}%)` : 'Tắt'}`, pct: shares.correctionPct },
  ];
  for (const seg of timingSegs) {
    if (seg.pct > 0) {
      const div = document.createElement('div');
      div.className = `pipe-t-seg ${seg.cls}`;
      div.style.width = `${seg.pct}%`;
      tBar.append(div);
    }
    const leg = document.createElement('span');
    leg.innerHTML = `<i style="background:${seg.color}"></i>`;
    leg.append(document.createTextNode(seg.label));
    tLeg.append(leg);
  }

  const origUrl = d ? thumbCache.get(d.id) || $('originalImage').src : '';
  if (pipeViewMode === 'overview') {
    for (let i = 0; i < 5; i++) body.append(buildStageCard(i, pipe, origUrl));
    $('pipelineFootHint').textContent = 'Đang xem tổng quan toàn bộ 5 khâu · Chọn "Từng bước" hoặc "Tự chạy" để trình chiếu demo.';
  } else {
    body.append(buildStageCard(pipeActiveStep, pipe, origUrl));
    $('pipePrev').disabled = pipeActiveStep <= 0;
    $('pipeNext').disabled = pipeActiveStep >= 4;
    $('pipelineFootHint').textContent = `Khâu ${pipeActiveStep + 1} / 5 · Dùng nút Trước / Tiếp hoặc Tự chạy để trình bày từng bước.`;
  }
}

async function openPipelineDialog(initialStep = 0, initialMode = 'overview') {
  const d = drafts.find(x => x.id === selected);
  if (!d) return;
  stopPipeAutoPlay();
  pipeViewMode = initialMode;
  pipeActiveStep = Math.max(0, Math.min(4, initialStep));
  activePipelineDraft = d;
  activePipelineData = null;

  $('pipelineMeta').textContent = `Đang tải dữ liệu chi tiết 5 khâu xử lý cho ${d.name}…`;
  $('pipelineBody').innerHTML = '<div class="pipe-empty">Đang tải dữ liệu Pipeline từ Compute Server…</div>';
  $('pipelineTimingWrap').hidden = true;
  $('pipelineDialog').showModal();

  const cached = pipelineCache.get(d.id);
  if (cached && cached.jobId === d.jobId) {
    activePipelineData = cached.data;
    renderPipelineDialogContent();
    return;
  }
  try {
    const data = await invoke('draft_pipeline', { id: d.id });
    if (data && typeof data === 'object') {
      pipelineCache.set(d.id, { jobId: d.jobId, data });
      activePipelineData = data;
      renderPipelineMiniBar();
    }
  } catch (err) {
    activePipelineData = null;
    $('pipelineMeta').textContent = sanitizeError(err) || 'Chưa có dữ liệu Pipeline';
  }
  renderPipelineDialogContent();
}

$('pipelineBtn').onclick = e => {
  e.stopPropagation();
  run(() => openPipelineDialog(0, 'overview'));
};
$('openPipelineFromBar').onclick = () => run(() => openPipelineDialog(0, 'overview'));
$('pipeModeOverview').onclick = () => {
  stopPipeAutoPlay();
  pipeViewMode = 'overview';
  renderPipelineDialogContent();
};
$('pipeModeStep').onclick = () => {
  stopPipeAutoPlay();
  pipeViewMode = 'step';
  renderPipelineDialogContent();
};
$('pipePrev').onclick = () => {
  stopPipeAutoPlay();
  if (pipeActiveStep > 0) {
    pipeActiveStep--;
    renderPipelineDialogContent();
  }
};
$('pipeNext').onclick = () => {
  stopPipeAutoPlay();
  if (pipeActiveStep < 4) {
    pipeActiveStep++;
    renderPipelineDialogContent();
  }
};
$('pipeAutoPlay').onclick = () => {
  if (pipeAutoTimer) {
    stopPipeAutoPlay();
    return;
  }
  if (!activePipelineData) return;
  pipeViewMode = 'step';
  pipeActiveStep = 0;
  renderPipelineDialogContent();
  $('pipeAutoPlay').textContent = '■ Dừng';
  pipeAutoTimer = setInterval(() => {
    if (!$('pipelineDialog').open) {
      stopPipeAutoPlay();
      return;
    }
    pipeActiveStep = (pipeActiveStep + 1) % 5;
    renderPipelineDialogContent();
  }, 3500);
};
$('pipelineClose').onclick = () => {
  stopPipeAutoPlay();
  $('pipelineDialog').close();
};
$('pipelineDialog').addEventListener('close', stopPipeAutoPlay);

run(boot);
