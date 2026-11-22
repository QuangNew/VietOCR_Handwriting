"use client";
import { useEffect,useState } from "react";
import { api } from "@/lib/api";
type Device={id:string;name:string;kind:string;available:boolean;reason:string|null};
export function WorkerPicker({busy,canAdd,action}:{busy:boolean;canAdd:boolean;action:(work:()=>Promise<unknown>,message:string)=>Promise<void>}){
  const [devices,setDevices]=useState<Device[]>([]),[selected,setSelected]=useState("auto"),[error,setError]=useState("");
  useEffect(()=>{let stopped=false;api<Device[]>("/devices").then(d=>{if(!stopped)setDevices(d);}).catch(e=>{if(!stopped)setError(e.message);});return()=>{stopped=true;};},[]);
  return <div className="worker-picker"><label>Thiết bị cho worker<select aria-label="Thiết bị cho worker" value={selected} onChange={e=>setSelected(e.target.value)} disabled={busy}>
    <option value="auto">Tự động: GPU rời → GPU tích hợp → CPU</option>
    {devices.filter(d=>d.kind!=="cpu").map(d=><option key={d.id} value={d.id} disabled={!d.available}>{d.name} · {d.id}{!d.available?" (chưa sẵn sàng)":""}</option>)}
    <option value="cpu">CPU · PyTorch</option>
  </select></label><button className="primary" disabled={busy||!canAdd} onClick={()=>action(()=>api("/workers","POST",{device:selected}),"Đã thêm worker trên thiết bị đã chọn.")}>{busy?"Đang khởi tạo…":"Thêm worker"}</button>
  {error&&<small role="status">{error} Bạn vẫn có thể chọn CPU hoặc Tự động.</small>}</div>;
}
