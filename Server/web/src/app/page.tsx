"use client";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, bytes, Client, duration, Job, resetSession, Snapshot, time } from "@/lib/api";
import { Icon } from "@/components/icons";
import { Chart } from "@/components/chart";
import { WorkerPicker } from "@/components/worker-picker";
import { ClientControls, SettingsControls, AuditControls } from "@/components/admin-controls";

const tabs = [
  { id: "overview", label: "Tổng quan", icon: "grid" }, { id: "workers", label: "WorkerSpace", icon: "cpu" },
  { id: "jobs", label: "Hàng đợi", icon: "queue" }, { id: "clients", label: "Tài khoản & API", icon: "key" },
  { id: "settings", label: "Cấu hình server", icon: "cpu" }, { id: "audit", label: "Nhật ký quản trị", icon: "queue" },
  { id: "docs", label: "Tích hợp API", icon: "code" },
] as const;
type Tab = typeof tabs[number]["id"];
const states: Record<string, string> = { queued: "Đang chờ", running: "Đang xử lý", succeeded: "Thành công", failed: "Thất bại", cancelled: "Đã huỷ", idle: "Sẵn sàng", busy: "Đang xử lý", starting: "Đang nạp", stopped: "Đã dừng" };
function Badge({ state }: { state: string }) { return <span className={`badge ${state}`}><i/>{states[state] || state}</span>; }
function uptime(n: number) { const h = Math.floor(n / 3600), m = Math.floor(n % 3600 / 60); return h ? `${h}h ${m}m` : `${m}m ${Math.floor(n % 60)}s`; }

export default function Home() {
  const [user, setUser] = useState<string | null>(null), [checking, setChecking] = useState(true);
  const [tab, setTab] = useState<Tab>("overview"), [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]), [clients, setClients] = useState<Client[]>([]);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false), [light, setLight] = useState(false);
  const [key, setKey] = useState(""), [selected, setSelected] = useState<Job | null>(null);
  const [passwordOpen,setPasswordOpen]=useState(false);
  const [filter, setFilter] = useState("all");
  useEffect(() => {
    const apply = () => { const value = new URLSearchParams(window.location.search).get("tab");
      setTab(tabs.some(t => t.id === value) ? value as Tab : "overview"); };
    apply(); window.addEventListener("popstate", apply);
    const theme = localStorage.getItem("vietocr.control.theme") === "light"; setLight(theme);
    document.documentElement.dataset.theme = theme ? "light" : "dark";
    api<{ username: string }>("/auth/me").then(u => setUser(u.username)).catch(e => { if (!(e instanceof ApiError && e.status === 401)) setError(e.message); }).finally(() => setChecking(false));
    return () => window.removeEventListener("popstate", apply);
  }, []);
  const refresh = useCallback(async () => {
    try {
      const s = await api<Snapshot>("/snapshot"); setSnapshot(s); setStale(false);
      const [j, c] = await Promise.all([api<Job[]>("/jobs"), api<Client[]>("/clients")]); setJobs(j); setClients(c);
    } catch (e) {
      setStale(true);
      if (e instanceof ApiError && e.status === 401) { setUser(null); resetSession(); }
      else setError(e instanceof Error ? e.message : "Mất kết nối server.");
    }
  }, []);
  useEffect(() => {
    if (!user) return;
    let disposed = false, timer: ReturnType<typeof setTimeout>;
    const tick = async () => { if (!document.hidden) await refresh(); if (!disposed) timer = setTimeout(tick, 3000); };
    void tick(); const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => { disposed = true; clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, [user, refresh]);
  useEffect(() => { if (notice) { const t = setTimeout(() => setNotice(""), 6000); return () => clearTimeout(t); } }, [notice]);
  function navigate(id: Tab) { setTab(id); window.history.pushState({}, "", `?tab=${id}`); }
  function selectJob(job: Job) {
    setSelected(job);
    void api<Job>(`/jobs/${job.id}`).then(value => setSelected(current => current?.id === value.id ? value : current))
      .catch(e => setError(e instanceof Error ? e.message : "Không đọc được kết quả."));
  }
  useEffect(() => {
    if(!selected && !passwordOpen) return;
    const previous=document.activeElement as HTMLElement | null;
    const close=(e:KeyboardEvent)=>{ if(e.key==="Escape") {setSelected(null);setPasswordOpen(false);}
      if(e.key==="Tab") {
        const elements=Array.from(document.querySelectorAll<HTMLElement>('.modal button:not(:disabled),.modal [tabindex="0"]'));
        const first=elements[0],last=elements.at(-1);
        if(e.shiftKey && document.activeElement===first){ e.preventDefault();last?.focus(); }
        else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first?.focus();}
      }
    };
    document.querySelector<HTMLElement>('.modal button')?.focus();document.addEventListener("keydown",close);
    return ()=>{document.removeEventListener("keydown",close);previous?.focus();};
  },[selected?.id,passwordOpen]);
  async function action(task: () => Promise<unknown>, message: string) {
    setBusy(true); setError("");
    try { await task(); setNotice(message); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Không thực hiện được."); }
    finally { setBusy(false); }
  }
  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); setBusy(true); setError("");
    try { const u = await api<{ username: string }>("/auth/login", "POST", { username: data.get("username"), password: data.get("password") }); resetSession(); setUser(u.username); }
    catch (e) { setError(e instanceof Error ? e.message : "Đăng nhập thất bại."); } finally { setBusy(false); }
  }
  function toggleTheme() { const next = !light; setLight(next); document.documentElement.dataset.theme = next ? "light" : "dark"; localStorage.setItem("vietocr.control.theme", next ? "light" : "dark"); }
  function exportMetrics() { if (!snapshot) return; const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "vietocr-metrics.json"; a.click(); URL.revokeObjectURL(url); }
  if (checking) return <main className="boot"><span className="brand-mark">V</span><p>Đang kết nối VietOCR Control…</p></main>;
  if (!user) return <main className="login-shell">
    <section className="login-story"><a className="brand" href="/"><span className="brand-mark">V</span><span>VietOCR <small>CONTROL</small></span></a>
      <div><span className="eyebrow">YOUR MODELS. YOUR MACHINE.</span><h1>Một nơi cho<br/>mọi yêu cầu OCR.</h1><p>Quan sát hệ thống. Phân phối công việc.<br/>Giữ quyền kiểm soát trên phần cứng của bạn.</p>
        <div className="pipeline-visual" aria-label="Client tới hàng đợi tới worker tới kết quả"><span>CLIENT</span><Icon name="arrow"/><span>QUEUE</span><Icon name="arrow"/><span>ML_s44</span></div></div>
      <footer>ASP.NET Core <b>·</b> Next.js <b>·</b> Supabase</footer></section>
    <section className="login-form"><span className="eyebrow">ADMIN WORKSPACE</span><h2>Chào mừng trở lại.</h2><p>Đăng nhập để vận hành server của bạn.</p>
      <form onSubmit={login}><label>Tên đăng nhập<input name="username" autoComplete="username" required maxLength={64} placeholder="admin"/></label>
        <label>Mật khẩu<input name="password" type="password" autoComplete="current-password" required maxLength={1024} placeholder="Nhập mật khẩu quản trị"/></label>
        {error && <div role="alert" className="alert error">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? "Đang xác thực…" : "Vào không gian quản trị"}<Icon name="arrow"/></button></form>
      <p className="fine">Chỉ dành cho quản trị viên. Tài khoản được tạo bằng<br/><code>Server/tools/New-Admin.ps1</code></p></section>
  </main>;
  const s = snapshot, g = s?.gpu;
  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="/"><span className="brand-mark">V</span><span>VietOCR <small>CONTROL</small></span></a>
      <div className="workspace-label">KHÔNG GIAN VẬN HÀNH</div><nav aria-label="Điều hướng chính">{tabs.map(t => <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => navigate(t.id)}><Icon name={t.icon}/><span>{t.label}</span>{t.id === "jobs" && !!s?.queued && <em>{s.queued}</em>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="local-host"><span className="status-dot"/><div>Self-hosted<span>Máy chủ của bạn</span></div><Icon name="cpu" size={17}/></div>
        <div className="admin-row"><span className="avatar">{user.slice(0, 1).toUpperCase()}</span><div><button className="account-button" onClick={()=>setPasswordOpen(true)} title="Đổi mật khẩu">{user}</button><small>Administrator</small></div><button aria-label="Đăng xuất" title="Đăng xuất" onClick={() => action(async () => { await api("/auth/logout", "POST"); resetSession(); setUser(null); }, "Đã đăng xuất")}><Icon name="logout" size={18}/></button></div></div>
    </aside>
    <main className="workspace"><header className="topbar"><div className="breadcrumb">Workspace <span>/</span> <b>{tabs.find(t => t.id === tab)?.label}</b></div><div className="top-actions"><span className={`live ${stale ? "stale" : ""}`}><i/>{stale ? "Mất kết nối" : s ? "Live · 3 giây" : "Đang kết nối"}</span><button className="icon-button" aria-label="Đổi giao diện sáng tối" onClick={toggleTheme}><Icon name="sun" size={18}/></button></div></header>
      <div className="content"><div className="page-heading"><div><span className="eyebrow">VIETOCR INFERENCE SERVER</span><h1>{tabs.find(t => t.id === tab)?.label}</h1><p>{tab === "overview" ? "Sức khoẻ hệ thống, trong tầm mắt." : tab === "workers" ? "Một model. Nhiều worker. Dựa trên khả năng phần cứng." : tab === "jobs" ? "Công việc được phân phối công bằng giữa các client." : tab === "clients" ? "Quyền truy cập riêng cho từng ứng dụng và thiết bị." : "Gửi ảnh. Theo dõi công việc. Nhận văn bản."}</p></div>
        <div className="heading-actions"><button onClick={refresh} disabled={busy}><Icon name="refresh" size={16}/>Làm mới</button><button onClick={exportMetrics} disabled={!s} className="icon-button" aria-label="Xuất số liệu JSON"><Icon name="download" size={18}/></button></div></div>
      {error && <div className="alert error" role="alert"><span>{error}{stale && s ? ` Số liệu gần nhất: ${time(s.timestamp)}.` : ""}</span><button aria-label="Ẩn thông báo" onClick={() => setError("")}><Icon name="close" size={16}/></button></div>}
      {notice && <div className="toast" role="status"><Icon name="check" size={17}/>{notice}<button aria-label="Đóng" onClick={() => setNotice("")}><Icon name="close" size={16}/></button></div>}
      {s && !s.acceptingRequests && <div className="alert warn">Chế độ bảo trì: server tạm ngừng nhận ảnh mới. Công việc đã nhận vẫn tiếp tục.</div>}
      {s?.dispatchPaused && <div className="alert warn">Hàng đợi đang tạm dừng phân phối. Ảnh đang chạy được hoàn tất; ảnh mới nhận sẽ chờ.</div>}
      {s?.error && <div className="alert warn">{s.error}</div>}
      {s?.latencySampled && <div className="alert warn">P50/P95 tính trên tối đa 20.000 công việc gần nhất. Tổng số và success rate vẫn tính trên toàn cửa sổ 15 phút.</div>}
      {!s && <div className="empty-panel"><Icon name="pulse" size={32}/><h2>Đang chờ số liệu server</h2><p>Kiểm tra kết nối Supabase và chạy Start-Server.ps1.</p><button onClick={refresh}>Thử kết nối lại</button></div>}
      {s && tab === "overview" && <>
        <div className="health-strip"><span className={`badge ${s.status === "healthy" ? "succeeded" : "failed"}`}><i/>{s.status === "healthy" ? "Hệ thống đang hoạt động" : "Hệ thống cần kiểm tra"}</span><span>Uptime <b>{uptime(s.uptimeSeconds)}</b></span><span>Supabase <b>{s.database === "connected" ? "Đã kết nối" : "Mất kết nối"}</b></span><span className="push">Cập nhật {time(s.timestamp)}</span></div>
        <div className="metric-grid"><Metric label="YÊU CẦU HOÀN TẤT" value={s.completed.toLocaleString("vi-VN")} detail={`${s.throughputPerMinute} ảnh / phút gần nhất`} icon="check"/>
          <Metric label="ĐỘ TRỄ P95" value={duration(s.p95Ms)} detail={`Trung vị ${duration(s.p50Ms)} · gồm thời gian chờ`} icon="pulse"/>
          <Metric label="TỶ LỆ THÀNH CÔNG" value={s.successRate == null ? "—" : `${s.successRate.toFixed(1)}%`} detail={`${s.failed} thất bại · ${s.cancelled} đã huỷ`} icon="grid"/>
          <Metric label="HÀNG ĐỢI HIỆN TẠI" value={String(s.queued)} detail={`${s.running} đang chạy · ${s.workers.length} worker`} icon="queue"/></div>
        <div className="overview-grid"><section className="panel chart-panel"><PanelTitle title="Độ trễ nhận diện" sub="Cửa sổ 15 phút · kể từ lúc server nhận ảnh"/><div className="chart-key"><span><i/>P95 <b>{duration(s.p95Ms)}</b></span><span className="compare"><i/>P50 <b>{duration(s.p50Ms)}</b></span></div><Chart points={s.history} metric="latency"/><div className="panel-foot">Inference TB <b>{duration(s.meanInferenceMs)}</b><span>Thời gian chờ TB <b>{duration(s.meanQueueMs)}</b></span></div></section>
          <section className="panel resource-panel"><PanelTitle title="Tài nguyên phần cứng" sub={g?.name || "GPU chưa khả dụng"}/><div className="resource-number">{bytes(g?.usedMiB)}<span> / {bytes(g?.totalMiB)} VRAM</span></div>
            <ResourceBar value={g ? g.usedMiB / g.totalMiB * 100 : 0}/><div className="resource-legend"><span><i/>Đang sử dụng</span><b>{g ? `${g.utilization}% GPU` : "—"}</b></div>
            <div className="resource-details"><div><span>Nhiệt độ GPU</span><b>{g ? `${g.temperature}°C` : "—"}</b></div><div><span>VRAM dự phòng</span><b>{bytes(s.capacity.reserveMiB)}</b></div><div><span>RAM hệ thống còn trống</span><b>{bytes(s.memory.availableMiB)}</b></div><div><span>RAM API / workers</span><b>{Math.round(s.memory.apiMiB)} / {Math.round(s.memory.workersMiB)} MB</b></div></div>
            {s.gpuError && <p className="fine">{s.gpuError}</p>}<button className="text-button" onClick={() => navigate("workers")}>Quản lý WorkerSpace<Icon name="arrow" size={16}/></button></section></div>
        <section className="panel"><div className="panel-heading"><PanelTitle title="Công việc gần đây" sub="100 công việc mới nhất · kết quả chỉ hiển thị khi mở chi tiết"/><button className="text-button" onClick={() => navigate("jobs")}>Xem hàng đợi<Icon name="arrow" size={16}/></button></div><JobTable jobs={jobs.slice(0, 6)} onSelect={selectJob}/></section>
      </>}
      {s && tab === "workers" && <><div className="capacity-banner"><div><span className="eyebrow">HARDWARE-AWARE WORKSPACE</span><h2>{s.workers.length} worker <span>trên {s.device}</span></h2><p>Mỗi worker giữ model đã warm-up. Queue phân phối luân phiên cho worker đang rảnh; CPU/GPU có thể chạy cùng lúc.</p></div><WorkerPicker busy={busy} canAdd={s.capacity.canAdd} action={action}/></div>
        <div className="capacity-grid"><div><span>DỰ TOÁN BAN ĐẦU</span><strong>{s.capacity.theoreticalWorkers ?? "—"}<small> worker</small></strong><p>(VRAM − 1 GB) / 300 MB · không phải giới hạn thực</p></div><div><span>BỘ NHỚ CHO WORKER TIẾP THEO</span><strong>{Math.round(s.capacity.measuredNextWorkerMiB)}<small> MB</small></strong><p>Warm-up + CUDA + biên dự phòng</p></div><div><span>CÒN CÓ THỂ THỬ THÊM</span><strong>{s.capacity.additionalWorkers ?? "—"}<small> worker</small></strong><p>Ước lượng; kiểm tra lại khi khởi tạo</p></div></div>
        <div className="worker-grid">{s.workers.map((w, i) => <section className="panel worker-card" key={w.id}><div className="worker-top"><span className="worker-icon"><Icon name="cpu" size={24}/></span><Badge state={w.draining ? "stopped" : w.state}/></div><h3>Worker {String(i + 1).padStart(2, "0")}</h3><code>{w.id}</code><div className="resource-details"><div><span>Device / PID</span><b>{w.device} / {w.pid ?? "—"}</b></div><div><span>VRAM reserved / peak</span><b>{Math.round(w.memory.reservedMiB)} / {Math.round(w.memory.peakMiB)} MB</b></div><div><span>RAM tiến trình</span><b>{Math.round(w.memory.ramMiB)} MB</b></div><div><span>Nạp model / warm-up</span><b>{duration(w.loadMs)}</b></div><div><span>Đã xử lý</span><b>{w.completed} ảnh</b></div></div><div className="worker-job">{w.jobId ? `Đang chạy #${w.jobId.slice(0, 8)}` : "Sẵn sàng nhận công việc tiếp theo"}</div><button disabled={busy || w.draining} onClick={() => action(() => api(`/workers/${w.id}`, "DELETE"), "Worker sẽ dừng sau công việc hiện tại.")}>Dừng worker</button></section>)}</div>
        {!s.workers.length && <div className="empty-panel"><h2>Chưa có worker sẵn sàng</h2><p>Thêm worker để bắt đầu xử lý hàng đợi.</p></div>}<p className="fine">Thêm nhiều worker có thể giảm tốc độ trên cùng GPU. Đo throughput và P95 trước khi tiếp tục tăng.</p></>}
      {s && tab === "jobs" && <><div className="queue-summary"><div><b>{s.queued}</b><span>Đang chờ</span></div><Icon name="arrow"/><div><b>{s.running}</b><span>Đang nhận diện</span></div><Icon name="arrow"/><div><b>{s.completed}</b><span>Hoàn tất / 15 phút</span></div><div className="queue-rule"><Icon name="queue"/><span>Round-robin theo client<br/><small>FIFO trong từng ứng dụng</small></span></div></div><section className="panel"><div className="panel-heading"><PanelTitle title="Danh sách công việc" sub={`Dung lượng hàng đợi tối đa ${s.capacity.queueCapacity} công việc`}/><select aria-label="Lọc trạng thái công việc" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">Tất cả trạng thái</option>{["queued", "running", "succeeded", "failed", "cancelled"].map(x => <option key={x} value={x}>{states[x]}</option>)}</select></div><JobTable jobs={jobs.filter(j => filter === "all" || j.state === filter)} onSelect={selectJob}/></section></>}
      {tab === "clients" && <>{key && <div className="alert key-reveal" role="status"><div><b>API key chỉ hiện một lần</b><p>Server lưu hash. Sao chép key trước khi đóng.</p><code>{key}</code></div><button onClick={() => { void navigator.clipboard.writeText(key).then(() => setNotice("Đã sao chép key.")).catch(() => setNotice("Chọn và sao chép key ở trên.")); }}>Sao chép</button><button aria-label="Ẩn API key" onClick={() => setKey("")}>×</button></div>}<ClientControls clients={clients} busy={busy} action={action} reveal={setKey} error={error}/></>}
      {tab === "settings" && <SettingsControls busy={busy} action={action}/>}
      {tab === "audit" && <AuditControls/>}
      {tab === "docs" && <section className="panel docs"><span className="eyebrow">ASYNC JOB API · V1</span><h2>Từ ảnh đến văn bản.</h2><p>App đăng nhập Google, dùng định danh OCR cố định và access token có thời hạn. Mỗi request gửi một ảnh; tối đa 500 ảnh/ngày và 30 request trong 60 giây, dùng chung mọi thiết bị. API key voc_… dành cho tích hợp dịch vụ do admin cấp.</p><ol><li><h3>Gửi ảnh và giữ lại mã công việc</h3><pre>{`POST /api/v1/jobs\nAuthorization: Bearer SUPABASE_ACCESS_TOKEN\nIdempotency-Key: unique-image-uuid\nContent-Type: multipart/form-data\n\nimage: <JPEG, PNG hoặc WEBP>\nlayout: auto | line\n\n→ 202 { "id": "...", "state": "queued" }`}</pre></li><li><h3>Theo dõi kết quả mỗi 1–3 giây</h3><pre>{`GET /api/v1/jobs/{id}\nAuthorization: Bearer SUPABASE_ACCESS_TOKEN\n\n→ { "state": "succeeded", "text": "Chúc giáng sinh vui vẻ",\n    "queueMs": 120, "inferenceMs": 840, "totalMs": 960 }`}</pre></li><li><h3>Huỷ khi không cần kết quả</h3><pre>{`DELETE /api/v1/jobs/{id}\nAuthorization: Bearer SUPABASE_ACCESS_TOKEN`}</pre></li></ol><div className="info-grid"><div><h3>Retry có kiểm soát</h3><p>429/503: chờ Retry-After. Mất kết nối khi upload: dùng lại Idempotency-Key với cùng ảnh và layout. Không tạo request mới liên tục.</p></div><div><h3>Truy cập từ điện thoại</h3><p>Dùng IP máy chủ trong LAN, không dùng localhost. Cấu hình HTTPS trước khi đưa ra Internet. App đăng nhập Google; phiên được lưu trong kho bảo mật của thiết bị.</p></div></div><p className="fine">SDK Python và Dart có tại Server/clients. Pipeline hiện nhận diện dòng/ảnh một cột; chưa phải bộ phân tích bố cục tài liệu tổng quát.</p></section>}
      {s && <div className="http-summary"><span>API HTTP · P95 <b>{duration(s.http.p95Ms)}</b></span><span>{s.http.requests} request · {s.http.errors} lỗi HTTP từ lúc khởi động</span><button className="text-button" onClick={()=>setPasswordOpen(true)}>Đổi mật khẩu</button><button className="text-button" onClick={()=>action(async()=>{await api('/auth/logout','POST');resetSession();setUser(null);},'Đã đăng xuất')}>Đăng xuất</button></div>}
      <footer className="workspace-footer"><span>VietOCR Control <b>v0.1</b></span><span>ML_s44 · Server inference</span></footer></div>
    </main>
    {passwordOpen && <div className="modal-backdrop"><section role="dialog" aria-modal="true" aria-labelledby="password-title" className="modal"><div className="panel-heading"><h2 id="password-title">Đổi mật khẩu quản trị</h2><button onClick={()=>setPasswordOpen(false)} aria-label="Đóng đổi mật khẩu"><Icon name="close"/></button></div><p>Đổi mật khẩu sẽ đăng xuất các phiên quản trị hiện tại.</p><form className="password-form" onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);void action(async()=>{await api('/auth/password','POST',{currentPassword:f.get('current'),newPassword:f.get('new')});resetSession();setPasswordOpen(false);setUser(null);},'Đã đổi mật khẩu. Đăng nhập lại để tiếp tục.');}}><label>Mật khẩu hiện tại<input name="current" type="password" autoComplete="current-password" required maxLength={1024}/></label><label>Mật khẩu mới<input name="new" type="password" autoComplete="new-password" required minLength={12} maxLength={1024}/></label>{error && <div className="alert error" role="alert">{error}</div>}<button className="primary" disabled={busy}>Đổi mật khẩu</button></form></section></div>}
    {selected && <div className="modal-backdrop" onClick={() => setSelected(null)}><section role="dialog" aria-modal="true" aria-labelledby="job-title" className="modal" onClick={e => e.stopPropagation()}><div className="panel-heading"><h2 id="job-title">Chi tiết công việc</h2><button aria-label="Đóng chi tiết" onClick={() => setSelected(null)}><Icon name="close"/></button></div><code>{selected.id}</code><div className="job-details"><Badge state={selected.state}/><span>{selected.clientName}</span><span>{duration(selected.totalMs)}</span></div><pre className="result-text">{selected.text || selected.error || "Công việc chưa hoàn tất. Đóng và mở lại để lấy trạng thái mới nhất."}</pre>{["queued", "running"].includes(selected.state) && <button className="danger-link" disabled={busy} onClick={() => action(async () => { await api(`/jobs/${selected.id}`, "DELETE"); setSelected(null); }, "Đã huỷ công việc.")}>Huỷ công việc</button>}<button className="modal-close" onClick={() => setSelected(null)}>Đóng</button></section></div>}
  </div>;
}
function Metric({ label, value, detail, icon }: { label: string; value: string; detail: string; icon: React.ComponentProps<typeof Icon>["name"] }) {
  return <section className="metric"><div><span>{label}</span><Icon name={icon} size={18}/></div><strong>{value}</strong><p>{detail}</p></section>;
}
function PanelTitle({ title, sub }: { title: string; sub: string }) { return <div className="panel-title"><h2>{title}</h2><p>{sub}</p></div>; }
function ResourceBar({ value }: { value: number }) { return <div className="resource-bar" role="meter" aria-label="VRAM đang sử dụng" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }}/></div>; }
function JobTable({ jobs, onSelect }: { jobs: Job[]; onSelect: (job: Job) => void }) { return <div className="table-wrap"><table><thead><tr><th>Công việc</th><th>Ứng dụng</th><th>Trạng thái</th><th>Độ trễ</th><th>Thời gian</th><th/></tr></thead><tbody>{jobs.map(j => <tr key={j.id}><td><code>#{j.id.slice(0, 8)}</code><small>{(j.imageBytes / 1024).toFixed(0)} KB · {j.layout}</small></td><td>{j.clientName}</td><td><Badge state={j.state}/></td><td className="tabular">{duration(j.totalMs)}</td><td className="muted tabular">{time(j.createdAt)}</td><td><button className="icon-button" aria-label={`Chi tiết ${j.id.slice(0, 8)}`} onClick={() => onSelect(j)}><Icon name="arrow" size={16}/></button></td></tr>)}</tbody></table>{!jobs.length && <div className="table-empty">Chưa có công việc trong danh sách này. Gửi ảnh từ client để bắt đầu.</div>}</div>; }
