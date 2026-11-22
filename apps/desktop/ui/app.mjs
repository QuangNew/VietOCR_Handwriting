import { outline, bounds, detectSelfClose, finalizeFreehand, dist } from './editor.mjs';

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
  invoke('record_log', { message: text }).catch(() => {});
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
    .catch(() => {})
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
  const sendable = drafts.filter(d => d.included !== false && sendableStates.includes(d.state));
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
  $('editHint').hidden = !current;
  $('text').disabled = !!current && ['queued', 'running', 'cancel_pending'].includes(current.state);
}

async function select(id) {
  selected = id;
  renderList();
  const d = drafts.find(x => x.id === id);
  $('text').value = d?.text ?? '';
  countText();
  if (!d) {
    $('originalImage').hidden = true;
    $('originalImage').removeAttribute('src');
    $('emptyImage').hidden = false;
    $('imageInfo').textContent = 'Bản nháp riêng';
    return;
  }
  const url = thumbCache.get(id) ?? (await invoke('draft_image', { id }));
  if (url) thumbCache.set(id, url);
  if (selected !== id) return;
  $('originalImage').src = url;
  $('originalImage').hidden = false;
  $('emptyImage').hidden = true;
  $('imageInfo').textContent = `${d.width && d.height ? `${d.width} × ${d.height} px · ` : ''}${(d.imageBytes / 1024).toFixed(0)} KiB · ${d.mediaType.replace('image/', '').toUpperCase()}`;
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

$('original').onclick = () => (selected ? run(openEditor) : $('import').click());
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
  for (const id of removedSet) thumbCache.delete(id);
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

$('send').onclick = () =>
  run(async () => {
    if (busy || !verified) return;
    busy = true;
    renderList();
    const selectedDrafts = drafts.filter(d => d.included !== false && sendableStates.includes(d.state));
    const epoch = accountEpoch;
    const layout = 'auto';
    const correct = Boolean($('correct')?.checked);

    async function worker(queue) {
      let item;
      while (epoch === accountEpoch && (item = queue.shift())) {
        const { d, op } = item;
        if (!activeOperation(d.id, op)) continue;
        try {
          let result;
          const deadline = Date.now() + 20 * 60000;
          while (activeOperation(d.id, op)) {
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
          if (!activeOperation(d.id, op) || !result) continue;
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

function liveTransform() {
  $('live').style.transform =
    (!review && $('mirror').checked) || (review && $('mirror').checked !== reviewMirrored) ? 'scaleX(-1)' : '';
}
function closeCamera() {
  cameraGeneration++;
  clearInterval(reviewTimer);
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
  clearInterval(reviewTimer);
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
  clearInterval(reviewTimer);
  reviewTimer = null;
  review = false;
  $('skip').hidden = true;
  $('shoot').disabled = false;
  $('reviewStatus').textContent = 'Ảnh đã lưu bản nháp · chưa gửi OCR';
  liveTransform();
}
$('skip').onclick = skip;
$('shoot').onclick = () =>
  run(async () => {
    $('shoot').disabled = true;
    const epoch = accountEpoch;
    const generation = cameraGeneration;
    const mirrored = $('mirror').checked;
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
      review = true;
      reviewMirrored = mirrored;
      liveTransform();
      $('live').src = await invoke('draft_image', { id: d.id });
      let seconds = 3;
      $('skip').hidden = false;
      $('reviewStatus').textContent = `Đã lưu bản nháp · xem lại ${seconds}s`;
      reviewTimer = setInterval(() => {
        seconds--;
        if (seconds <= 0) skip();
        else $('reviewStatus').textContent = `Đã lưu bản nháp · xem lại ${seconds}s`;
      }, 1000);
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

run(boot);
