"use client";
import { Point, duration, time } from "@/lib/api";

export function Chart({ points, metric }: { points: Point[]; metric: "latency" | "queue" }) {
  const latency = metric === "latency";
  const a = points.map(p => latency ? p.p95Ms : p.queued);
  const b = points.map(p => latency ? p.p50Ms : p.running);
  const finite = [...a, ...b].filter((n): n is number => n != null);
  const max = Math.max(latency ? 1000 : 4, ...finite) * 1.1;
  const width = 680, height = 196, pad = 10;
  function line(data: (number | null)[]) {
    let started = false;
    return data.map((v, i) => { if (v == null) { started = false; return ""; }
      const part = `${started ? "L" : "M"}${pad + i * (width - 2 * pad) / Math.max(1, data.length - 1)},${height - pad - v / max * (height - 2 * pad)}`;
      started = true; return part; }).join(" ");
  }
  return <div className="chart" role="img" aria-label={latency ? "Độ trễ OCR p95 và p50 trong phiên theo dõi" : "Số công việc chờ và đang chạy trong phiên theo dõi"}>
    <div className="chart-scale"><span>{latency ? duration(max) : Math.ceil(max)}</span><span>{latency ? duration(max / 2) : Math.ceil(max / 2)}</span><span>0</span></div>
    <div className="chart-plot">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {[pad, height / 2, height - pad].map(y => <line key={y} x1="0" x2={width} y1={y} y2={y} className="grid-line"/>)}
        <path d={line(a)} fill="none" stroke="var(--accent)" strokeWidth="2.5" vectorEffect="non-scaling-stroke"/>
        <path d={line(b)} fill="none" stroke="var(--compare)" strokeWidth="2" strokeDasharray="5 4" vectorEffect="non-scaling-stroke"/>
      </svg>
      {(!finite.length || points.length < 2) && <div className="chart-empty">{latency ? "Chưa có đủ công việc hoàn tất" : "Đang thu thập số liệu"}</div>}
      <div className="chart-times"><span>{points[0] ? time(points[0].time) : "—"}</span><span>{points.at(-1) ? time(points.at(-1)!.time) : "Hiện tại"}</span></div>
    </div>
  </div>;
}
