"use client";
import { useEffect, useState } from "react";
import { api, Client } from "@/lib/api";

type Action = (task: () => Promise<unknown>, message: string) => Promise<void>;
export function ClientControls({ clients, busy, action, reveal, error }: { clients: Client[]; busy: boolean; action: Action; reveal: (key: string) => void; error: string }) {
  const [editing, setEditing] = useState<Client | null>(null), [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  useEffect(() => { const close = (e: KeyboardEvent) => { if (e.key === "Escape") setEditing(null); };
    window.addEventListener("keydown", close); return () => window.removeEventListener("keydown", close); }, []);
  const visible = clients.filter(c => (kind === "all" || (kind === "users") === !!c.userId) &&
    `${c.name} ${c.email || ""} ${c.id}`.toLowerCase().includes(search.toLowerCase()));
  return <>
    <section className="panel control-create"><h2>Tài khoản & API key</h2><p>Tài khoản Google có mã OCR cố định. API key bên dưới dành cho tích hợp dịch vụ; không cần nhập key vào app.</p>
      <form className="control-form" onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget);
        void action(async () => { const v = await api<{ key: string }>("/clients", "POST", { name: f.get("name"), ratePerMinute: Number(f.get("rate")), dailyLimit: Number(f.get("daily")) }); reveal(v.key); }, "Đã tạo API key dịch vụ."); }}>
        <label>Tên dịch vụ<input name="name" required maxLength={80} placeholder="Tích hợp riêng của bạn"/></label>
        <label>Request / 60 giây<input name="rate" type="number" min={1} max={60} defaultValue={60} required/></label>
        <label>Ảnh / ngày<input name="daily" type="number" min={1} max={1000} defaultValue={1000} required/></label>
        <button className="primary" disabled={busy}>Tạo API key</button>
      </form>
    </section>
    <section className="panel"><div className="panel-heading"><div><h2>{visible.length} tài khoản / dịch vụ</h2><p>Sửa tên, hạn mức, khoá/mở; dữ liệu và định danh được giữ nguyên.</p></div></div>
      <div className="control-filter"><input aria-label="Tìm tài khoản" placeholder="Tìm tên, Gmail hoặc mã OCR…" value={search} onChange={e => setSearch(e.target.value)}/>
        <select aria-label="Loại tài khoản" value={kind} onChange={e => setKind(e.target.value)}><option value="all">Tất cả</option><option value="users">Tài khoản Google</option><option value="services">API dịch vụ</option></select></div>
      <div className="table-wrap"><table><thead><tr><th>Tài khoản</th><th>Định danh / Key</th><th>Hạn mức</th><th>Hôm nay</th><th>Trạng thái</th><th>Quản lý</th></tr></thead><tbody>{visible.map(c => <tr key={c.id}>
        <td><b>{c.name}</b><small>{c.email || "API dịch vụ"}</small></td><td><code title={c.ocrId || c.prefix}>{c.ocrId ? `${c.ocrId.slice(0, 17)}…` : `${c.prefix}…`}</code></td>
        <td>{c.ratePerMinute} / phút<small>{c.dailyLimit.toLocaleString("vi-VN")} / ngày</small></td><td>{c.usedToday || 0} / {c.dailyLimit}</td>
        <td><span className={`badge ${c.enabled ? "idle" : "stopped"}`}><i/>{c.enabled ? "Đang bật" : "Đã khoá"}</span></td>
        <td><button disabled={busy} onClick={() => setEditing(c)}>Chỉnh sửa</button></td></tr>)}</tbody></table>
        {!visible.length && <div className="table-empty">Chưa có tài khoản phù hợp. Người dùng sẽ xuất hiện khi đăng nhập Google lần đầu.</div>}</div>
    </section>
    {editing && <div className="modal-backdrop"><section className="modal control-modal" role="dialog" aria-modal="true" aria-labelledby="client-edit-title">
      <div className="panel-heading"><h2 id="client-edit-title">Cấu hình {editing.userId ? "tài khoản" : "API key"}</h2><button onClick={() => setEditing(null)} aria-label="Đóng cấu hình tài khoản">×</button></div>
      <p className="break-code">{editing.ocrId || editing.id}</p><p>Mã định danh không đổi khi sửa cấu hình. Hạn mức chung cho mọi thiết bị của cùng tài khoản.</p>
      {error && <div className="alert error" role="alert">{error}</div>}
      <form className="control-form edit-form" key={editing.id} onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget);
        void action(async () => { await api(`/clients/${editing.id}`, "PUT", { name: f.get("name"), ratePerMinute: Number(f.get("rate")), dailyLimit: Number(f.get("daily")), enabled: f.get("enabled") === "on" }); setEditing(null); }, "Đã lưu tài khoản; cấu hình có hiệu lực với request tiếp theo."); }}>
        <label>Tên hiển thị<input name="name" defaultValue={editing.name} required maxLength={80} autoFocus/></label>
        <label>Request / 60 giây<input name="rate" type="number" min={1} max={60} defaultValue={editing.ratePerMinute} required/></label>
        <label>Ảnh / ngày<input name="daily" type="number" min={1} max={1000} defaultValue={editing.dailyLimit} required/></label>
        <label className="check-control"><input name="enabled" type="checkbox" defaultChecked={editing.enabled}/> Cho phép gửi OCR</label>
        <button className="primary" disabled={busy}>Lưu thay đổi</button>
      </form>
      {!editing.userId && <div className="rotation-warning"><p>Cấp lại key sẽ vô hiệu key cũ ngay lập tức. Công việc và định danh dịch vụ vẫn được giữ.</p>
        <button disabled={busy} onClick={() => { if (!window.confirm("Cấp lại API key? Các tích hợp dùng key cũ cần cập nhật.")) return;
          void action(async () => { const v = await api<{ key: string }>(`/clients/${editing.id}/rotate`, "POST"); reveal(v.key); setEditing(null); }, "Đã cấp lại key. Sao chép key mới trước khi đóng."); }}>Cấp lại API key</button></div>}
    </section></div>}
  </>;
}

export type Settings = { acceptingRequests: boolean; dispatchPaused: boolean; queueCapacity: number; perClientPending: number;
  jobTimeoutSeconds: number; retentionHours: number; reserveRamMiB: number; reserveVramMiB: number; workerBudgetMiB: number;
  initialWorkers: number; maxUploadMiB: number; maxPixels: number; spoolMiB: number; defaultDailyLimit: number; defaultRatePerMinute: number };
const fields: { key: keyof Settings; label: string; min: number; max: number; hint: string }[] = [
  { key: "queueCapacity", label: "Tổng công việc chờ / chạy", min: 1, max: 100000, hint: "Từ chối request mới khi đầy, không xoá queue đang có." },
  { key: "perClientPending", label: "Công việc chờ / tài khoản", min: 1, max: 100000, hint: "Tránh một tài khoản chiếm hết hàng đợi." },
  { key: "jobTimeoutSeconds", label: "Timeout mỗi ảnh (giây)", min: 5, max: 600, hint: "Áp dụng khi worker bắt đầu ảnh tiếp theo." },
  { key: "retentionHours", label: "Lưu kết quả (giờ)", min: 1, max: 720, hint: "Chỉ dọn kết quả đã kết thúc, mỗi 10 phút." },
  { key: "reserveRamMiB", label: "RAM dự phòng (MiB)", min: 512, max: 65536, hint: "Không thêm worker nếu thiếu phần dự phòng này." },
  { key: "reserveVramMiB", label: "VRAM dự phòng (MiB)", min: 512, max: 65536, hint: "Kiểm tra cả trước và sau warm-up." },
  { key: "workerBudgetMiB", label: "Dự toán model (MiB)", min: 100, max: 16384, hint: "Luôn đối chiếu bộ nhớ thực, không dùng làm cam kết." },
  { key: "initialWorkers", label: "Worker khi khởi động", min: 0, max: 256, hint: "Lưu cho lần mở server tới; bị giới hạn bởi RAM/VRAM thực." },
  { key: "maxUploadMiB", label: "Ảnh tối đa (MiB)", min: 1, max: 64, hint: "Request ảnh mới; tối đa 64 MiB." },
  { key: "maxPixels", label: "Pixel tối đa / ảnh", min: 10000, max: 40000000, hint: "Worker hiện tại cần dừng rồi thêm lại để cập nhật." },
  { key: "spoolMiB", label: "Bộ nhớ ảnh đang chờ (MiB)", min: 1, max: 1048576, hint: "Dung lượng tạm trên máy host; ảnh gốc xoá sau xử lý." },
  { key: "defaultDailyLimit", label: "Ảnh / ngày cho tài khoản mới", min: 1, max: 1000, hint: "Tối đa 1.000; ngày đặt lại lúc 00:00 giờ Việt Nam." },
  { key: "defaultRatePerMinute", label: "Request / phút tài khoản mới", min: 1, max: 60, hint: "Cửa sổ trượt 60 giây; cùng hạn mức trên mọi thiết bị." },
];
export function SettingsControls({ busy, action }: { busy: boolean; action: Action }) {
  const [settings, setSettings] = useState<Settings | null>(null), [error, setError] = useState("");
  useEffect(() => { api<Settings>("/settings").then(setSettings).catch(e => setError(e.message)); }, []);
  if (!settings) return <section className="panel control-create"><p role="status">{error || "Đang đọc cấu hình từ Supabase…"}</p></section>;
  return <section className="panel control-create"><h2>Quyền điều hành server</h2><p>Cấu hình lưu vào Supabase và được khôi phục sau khi khởi động lại. Không cần sửa file cho các thông số bên dưới.</p>
    <form onSubmit={e => { e.preventDefault(); void action(async () => { const s = await api<Settings>("/settings", "PUT", settings); setSettings(s); }, "Đã lưu và áp dụng cấu hình vận hành."); }}>
      <div className="operation-switches"><label className="check-control"><input type="checkbox" checked={settings.acceptingRequests} onChange={e => setSettings({ ...settings, acceptingRequests: e.target.checked })}/> Nhận yêu cầu mới</label>
        <label className="check-control"><input type="checkbox" checked={settings.dispatchPaused} onChange={e => setSettings({ ...settings, dispatchPaused: e.target.checked })}/> Tạm dừng phân phối queue</label></div>
      <p className="fine">Tạm dừng queue giữ nguyên công việc đang chờ. Ảnh đang chạy được phép hoàn tất.</p>
      <div className="settings-grid">{fields.map(f => <label key={f.key}>{f.label}<input type="number" required min={f.min} max={f.max} value={Number(settings[f.key])}
        onChange={e => setSettings({ ...settings, [f.key]: Number(e.target.value) })}/><small>{f.hint}</small></label>)}</div>
      <div className="settings-save"><button className="primary" disabled={busy}>Lưu cấu hình server</button><span>Không thay đổi thông tin đăng nhập hay đường dẫn chương trình worker.</span></div>
    </form>
    <div className="rotation-warning"><h3>Dọn hàng đợi đang chờ</h3><p>Huỷ tất cả ảnh chưa bắt đầu xử lý. Ảnh đang chạy tiếp tục; hạn mức đã dùng không được hoàn lại.</p>
      <button className="danger-link" disabled={busy} onClick={() => { if (window.confirm("Huỷ toàn bộ công việc đang chờ của mọi tài khoản?")) void action(() => api("/queue/cancel-pending", "POST"), "Đã huỷ các công việc chưa bắt đầu."); }}>Huỷ công việc đang chờ</button></div>
    <div className="integration-links"><h3>Supabase & Google OAuth</h3><p>Project: <code>rrdxhztiikizgogxtlhu</code>. Khoá bí mật chỉ được đọc bởi API, không gửi cho web/app.</p>
      <a href="https://supabase.com/dashboard/project/rrdxhztiikizgogxtlhu/auth/providers" target="_blank" rel="noreferrer">Mở Google provider ↗</a>
      <a href="https://supabase.com/dashboard/project/rrdxhztiikizgogxtlhu/auth/url-configuration" target="_blank" rel="noreferrer">Cấu hình callback app ↗</a>
      <p className="fine">Redirect URLs cần thêm: <code>http://127.0.0.1:47821/auth/callback</code> và <code>vn.pbl4.vietocr://auth/callback</code>.</p></div>
  </section>;
}
type Audit = { id: number; actor: string; action: string; target: string | null; details: unknown; created_at: string };
export function AuditControls() {
  const [rows, setRows] = useState<Audit[]>([]), [error, setError] = useState("");
  useEffect(() => { let stopped = false; let timer: ReturnType<typeof setTimeout>;
    const load = async () => { if (!document.hidden) { try { const v = await api<Audit[]>("/audit"); if (!stopped) { setRows(v); setError(""); } } catch(e) { if (!stopped) setError((e as Error).message); } }
      if (!stopped) timer = setTimeout(load, 5000); }; void load(); return () => { stopped = true; clearTimeout(timer); }; }, []);
  return <section className="panel"><div className="panel-heading"><div><h2>Nhật ký quản trị</h2><p>200 thay đổi mới nhất · lưu 90 ngày · không ghi API key hoặc mật khẩu</p></div></div>{error && <p role="alert">{error}</p>}
    <div className="table-wrap"><table><thead><tr><th>Thời điểm</th><th>Quản trị viên</th><th>Thao tác</th><th>Đối tượng</th><th>Chi tiết</th></tr></thead><tbody>{rows.map(r => <tr key={r.id}>
      <td>{new Date(r.created_at).toLocaleString("vi-VN")}</td><td>{r.actor}</td><td><code>{r.action}</code></td><td><code>{r.target?.slice(0, 12) || "Server"}</code></td><td><details><summary>Xem</summary><pre>{JSON.stringify(r.details, null, 2)}</pre></details></td></tr>)}</tbody></table>{!rows.length && <div className="table-empty">Chưa có thay đổi quản trị.</div>}</div></section>;
}
