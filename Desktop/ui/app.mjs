import {outline,bounds} from './editor.mjs';
const $=id=>document.getElementById(id);
const invoke=(name,args={})=>window.__TAURI__?.core.invoke(name,args)??Promise.reject(Error('Mở ứng dụng Tauri để sử dụng chức năng này.'));
const channel=handler=>{const c=new window.__TAURI__.core.Channel();c.onmessage=handler;return c;};
let drafts=[],selected=null,config=null,verified=false,busy=false,liveURL=null,reviewTimer=null,editorSource=null,points=[],drawing=false,textTimer=null,toastTimer=null,transferTimer=null,userId=null,accountEpoch=0;
const runningResults=new Map(),transferRows=new Map();
const label=state=>({draft:'Bản nháp · chưa gửi',awaiting_upload:'Chờ lượt gửi',upload_granted:'Được phép gửi',uploading:'Đang gửi',queued:'Đang chờ worker',running:'Đang đọc chữ',succeeded:'Hoàn tất',failed:'Không nhận diện được',cancelled:'Đã dừng',expired:'Đã hết hạn lưu kết quả'}[state]??state);
function toast(text){$('toast').textContent=String(text);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6000);}
function fail(e){const text=String(e);$('message').textContent=text;toast(text);invoke('record_log',{message:text}).catch(()=>{});}
async function run(action){try{return await action();}catch(e){fail(e);return null;}}
function patch(d){if(!userId||d.ownerId!==userId)return;const i=drafts.findIndex(x=>x.id===d.id);if(i<0)drafts.push(d);else drafts[i]=d;renderList();}
function renderList(){
  $('count').textContent=drafts.length;$('drafts').replaceChildren();
  for(const[d,i]of drafts.map((d,i)=>[d,i])){
    const row=document.createElement('div');row.className=`draft-row ${selected===d.id?'active':''}`;
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=d.included!==false;checkbox.disabled=busy;checkbox.setAttribute('aria-label',`Gửi ${d.name}`);checkbox.onchange=()=>run(async()=>{patch(await invoke('set_included',{id:d.id,included:checkbox.checked}));});
    const n=document.createElement('span');n.className='draft-number';n.textContent=String(i+1).padStart(2,'0');
    const block=document.createElement('button');block.className='draft-name';const title=document.createElement('strong');title.textContent=d.name;const hint=document.createElement('small');hint.textContent=label(d.state);block.append(title,hint);block.onclick=()=>run(()=>select(d.id));row.append(checkbox,n,block);$('drafts').append(row);
  }
  const current=drafts.find(x=>x.id===selected);$('jobState').textContent=current?label(current.state):'Chưa gửi';
  const sendable=drafts.filter(d=>d.included!==false&&['draft','awaiting_upload','upload_granted','uploading'].includes(d.state));
  $('send').disabled=busy||!verified||!sendable.length;$('send').textContent=`Gửi ${sendable.length} ảnh →`;
  for(const id of ['edit','download','remove'])$(id).disabled=!current;
  $('optimize').disabled=!current||busy;
  $('downloadAll').disabled=!drafts.length;
  $('historyButton').disabled=!verified;
  $('text').disabled=!!current&&['queued','running'].includes(current.state);
}
async function select(id){
  selected=id;renderList();const d=drafts.find(d=>d.id===id);
  $('text').value=d?.text??'';countText();
  if(!d){$('originalImage').hidden=true;$('emptyImage').hidden=false;return;}
  const url=await invoke('draft_image',{id});if(selected!==id)return;
  $('originalImage').src=url;$('originalImage').hidden=false;$('emptyImage').hidden=true;
  $('imageInfo').textContent=`${d.width&&d.height?`${d.width} × ${d.height} px · `:''}${(d.imageBytes/1024).toFixed(0)} KiB · ${d.mediaType.replace('image/','').toUpperCase()}`;
}
async function boot(){
  const data=await invoke('bootstrap');config=data.config;drafts=data.drafts;verified=!!data.verified;userId=data.session?.userId??null;
  $('email').textContent=data.session?.email??'Chưa đăng nhập Google';
  $('connection').textContent=verified?'Raspberry đã xác minh':data.session?'Offline · bản nháp được giữ':'Chưa xác minh Raspberry';
  $('connectionDot').classList.toggle('connected',verified);
  $('authGate').hidden=!!data.session&&!!(verified||data.workspaceAllowed);
  $('workspace').hidden=!$('authGate').hidden;
  $('authMessage').textContent=data.session&&!verified?'Chưa xác minh được với Pi. Kiểm tra địa chỉ gateway và migration database.':'';
  $('gateway').value=config.gateway;
  renderList();await select(drafts.some(d=>d.id===selected)?selected:drafts[0]?.id??null);
  for(const d of drafts)if(d.jobId&&!['succeeded','failed','cancelled','expired'].includes(d.state))pollResult(d.id);
}
$('theme').onclick=()=>{document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');};
document.body.classList.toggle('light',localStorage.getItem('theme')==='light');
function settings(){$('settings').showModal();}
$('settingsButton').onclick=settings;$('gateSettings').onclick=settings;
$('saveSettings').onclick=()=>run(async()=>{await invoke('configure',{gateway:$('gateway').value.trim().replace(/\/$/,'')});$('settings').close();await boot();});
$('login').onclick=()=>run(async()=>{$('login').disabled=true;$('authMessage').textContent='Hoàn tất đăng nhập trong trình duyệt…';try{await invoke('login');await boot();}finally{$('login').disabled=false;}});
$('logoutButton').onclick=()=>run(async()=>{accountEpoch++;userId=null;verified=false;closeCamera();await invoke('logout');drafts=[];selected=null;await boot();});
$('import').onclick=()=>run(async()=>{const items=await invoke('pick_import');items.forEach(patch);if(items.length)await select(items.at(-1).id);$('message').textContent='Đã thêm bản nháp. Chọn Gửi khi sẵn sàng.';});
$('original').onclick=()=>selected?run(openEditor):$('import').click();
$('edit').onclick=()=>run(openEditor);
$('download').onclick=()=>run(()=>invoke('export_images',{ids:[selected]}));
$('downloadAll').onclick=()=>run(()=>invoke('export_images',{ids:drafts.map(d=>d.id)}));
$('optimize').onclick=()=>run(async()=>{if(!selected||busy)return;const sourceId=selected;$('optimize').disabled=true;try{const d=await invoke('optimize_draft',{id:sourceId});if(!d){toast('Ảnh đã gọn hoặc có profile màu cần giữ. Tiếp tục dùng bản gốc.');return;}const source=drafts.find(x=>x.id===sourceId);if(source)source.included=false;patch(d);await select(d.id);toast(d.transferNote+' · bản gốc được giữ');}finally{renderList();}});
$('remove').onclick=()=>run(async()=>{await invoke('remove_draft',{id:selected});drafts=drafts.filter(d=>d.id!==selected);await select(drafts[0]?.id??null);});
$('copy').onclick=()=>run(()=>navigator.clipboard.writeText($('text').value));
$('exportText').onclick=()=>run(()=>invoke('export_text'));
function countText(){$('textCount').textContent=`${$('text').value.length.toLocaleString('vi')} ký tự`;}
$('text').oninput=()=>{countText();clearTimeout(textTimer);const id=selected,text=$('text').value;const d=drafts.find(d=>d.id===id);if(d)d.text=text;textTimer=setTimeout(()=>run(()=>invoke('save_text',{id,text})),400);};
function transfer(id,text,done=null,total=1){
  transferRows.set(id,{text,done,total});$('transfers').hidden=false;clearTimeout(transferTimer);$('transferRows').replaceChildren();
  for(const[key,row]of transferRows){const div=document.createElement('div');div.className='transfer-row';const d=drafts.find(x=>x.id===key);const title=document.createElement('div');title.textContent=d?.name??'Tài liệu';const p=document.createElement('progress');if(row.done!==null)p.value=row.done/row.total;const status=document.createElement('small');status.textContent=row.text;div.append(title,p,status);$('transferRows').append(div);}
  if([...transferRows.values()].every(row=>row.done===row.total)){$('transferTitle').textContent='Đã xử lý lượt gửi';transferTimer=setTimeout(()=>$('transfers').hidden=true,5000);}else{$('transferTitle').textContent='Tiến trình gửi & đọc';}
}
$('hideTransfers').onclick=()=>{$('transfers').hidden=true;};
async function pollResult(id){
  const epoch=accountEpoch;
  if(runningResults.get(id)===epoch)return;runningResults.set(id,epoch);
  let interruptions=0;
  try{
    while(drafts.some(d=>d.id===id)&&verified&&epoch===accountEpoch){
      let d;
      try{d=await invoke('read_result',{id});interruptions=0;}
      catch(e){if(epoch!==accountEpoch)return;if(/HTTP (401|403)|Đăng nhập Google/.test(String(e)))throw e;interruptions++;transfer(id,'Server giữ lượt gửi · đang kết nối lại để nhận kết quả');await new Promise(r=>setTimeout(r,Math.min(15000,1500*interruptions)+Math.random()*500));continue;}
      if(epoch!==accountEpoch)return;patch(d);transfer(id,label(d.state),['succeeded','failed','cancelled','expired','awaiting_upload','upload_granted','uploading'].includes(d.state)?1:null,1);
      if(selected===id&&document.activeElement!==$('text')){$('text').value=d.text;countText();}
      if(['succeeded','failed','cancelled','expired','awaiting_upload','upload_granted','uploading'].includes(d.state))break;
      await new Promise(r=>setTimeout(r,500));
    }
  }catch(e){transfer(id,`Kết quả đang lưu ở server · ${String(e)}`,1,1);$('message').textContent='Chưa nhận kết quả. Mở app lại để lấy tiếp.';}
  finally{if(runningResults.get(id)===epoch)runningResults.delete(id);}
}
$('historyButton').onclick=()=>run(async()=>{
  const epoch=accountEpoch,rows=await invoke('history');if(epoch!==accountEpoch)return;
  $('historyRows').replaceChildren();$('historyText').value='';$('historyState').textContent=rows.length?'Chọn một lượt để xem kết quả.':'Chưa có lượt gửi nào.';
  for(const item of rows){const button=document.createElement('button');button.textContent=`${new Date(item.created_at??item.createdAt).toLocaleString('vi-VN')} · ${label(item.state)}`;
    button.onclick=()=>run(async()=>{const data=await invoke('history_result',{id:item.id});if(epoch!==accountEpoch)return;$('historyText').value=data.text??data.error??'';$('historyState').textContent=label(data.state);});$('historyRows').append(button);}
  $('history').showModal();
});
$('historyCopy').onclick=()=>run(()=>navigator.clipboard.writeText($('historyText').value));
$('logsButton').onclick=()=>run(async()=>{$('logText').value=await invoke('read_logs');$('logs').showModal();});
$('reloadLogs').onclick=()=>run(async()=>{$('logText').value=await invoke('read_logs');});
$('copyLogs').onclick=()=>run(()=>navigator.clipboard.writeText($('logText').value));
$('send').onclick=()=>run(async()=>{
  if(busy||!verified)return;busy=true;renderList();const queue=drafts.filter(d=>d.included!==false&&['draft','awaiting_upload','upload_granted','uploading'].includes(d.state)),epoch=accountEpoch,layout=$('layout').value;
  async function worker(){let d;while(epoch===accountEpoch&&(d=queue.shift())){
    transfer(d.id,'Chờ lượt gửi');
    try{
      let result;const deadline=Date.now()+20*60000;
      while(true){if(epoch!==accountEpoch)return;try{result=await invoke('send_draft',{id:d.id,layout,progress:channel(p=>{if(epoch===accountEpoch)transfer(d.id,p.stage==='uploading'?`Đang gửi ${Math.round(p.done/p.total*100)}%`:p.stage,p.done,p.total);})});break;}
        catch(e){if(!/queue_wait|compute_queue_busy|uploads_busy|auth_capacity|database_capacity|compute_capacity|compute_unreachable|compute_unavailable|identity_database_unavailable|jwks_unavailable|server_not_ready|minute_quota|offset_mismatch|stale_lease/.test(String(e))||Date.now()>deadline)throw e;transfer(d.id,'Đang chờ công suất hoặc kết nối lại');await new Promise(r=>setTimeout(r,3000+Math.random()*1000));}}
      if(epoch!==accountEpoch)return;patch(result);pollResult(d.id);
    }catch(e){transfer(d.id,String(e),1,1);fail(e);}
  }}
  try{await Promise.all([worker(),worker()]);}finally{busy=false;renderList();}
});
const splitter=$('splitter');splitter.onpointerdown=e=>{splitter.setPointerCapture(e.pointerId);splitter.onpointermove=e=>$('sidebar').style.width=`${Math.max(250,Math.min(440,e.clientX))}px`;splitter.onpointerup=()=>{splitter.onpointermove=null;};};

let review=false,reviewMirrored=false,cameraGeneration=0;
function liveTransform(){$('live').style.transform=(!review&&$('mirror').checked)||(review&&$('mirror').checked!==reviewMirrored)?'scaleX(-1)':'';}
function closeCamera(){cameraGeneration++;clearInterval(reviewTimer);reviewTimer=null;review=false;$('camera').close();run(()=>invoke('camera_stop'));if(liveURL){URL.revokeObjectURL(liveURL);liveURL=null;}}
async function startCamera(){
  const generation=++cameraGeneration;review=false;clearInterval(reviewTimer);reviewTimer=null;$('skip').hidden=true;$('shoot').disabled=false;liveTransform();$('cameraStatus').textContent='Đang mở camera…';
  await invoke('camera_stop');const frames=channel(async buffer=>{
    try{if(generation===cameraGeneration&&!review&&$('camera').open){const next=URL.createObjectURL(new Blob([buffer],{type:'image/jpeg'}));const old=liveURL;liveURL=next;$('live').src=next;$('cameraStatus').textContent='Đang xem trực tiếp';if(old)URL.revokeObjectURL(old);}}
    finally{await invoke('camera_ack');}
  });
  invoke('camera_stream',{id:$('cameraSelect').value,frames}).then(()=>{if(generation===cameraGeneration&&$('camera').open&&!review)$('cameraStatus').textContent='Stream đã dừng. Chọn lại camera để nối lại.';}).catch(e=>{if(generation===cameraGeneration&&$('camera').open){$('cameraStatus').textContent=String(e);}});
}
$('cameraButton').onclick=()=>run(async()=>{const items=await invoke('cameras');$('cameraSelect').replaceChildren();for(const c of items){const option=document.createElement('option');option.value=c.id;option.textContent=c.name;$('cameraSelect').append(option);}if(!items.length)throw Error('Pi chưa có webcam được cấu hình.');$('camera').showModal();await startCamera();});
$('cameraSelect').onchange=()=>run(startCamera);$('cameraClose').onclick=closeCamera;$('camera').addEventListener('cancel',()=>closeCamera());
$('mirror').onchange=liveTransform;
function skip(){clearInterval(reviewTimer);reviewTimer=null;review=false;$('skip').hidden=true;$('shoot').disabled=false;$('reviewStatus').textContent='Ảnh đã lưu bản nháp · chưa gửi OCR';liveTransform();}
$('skip').onclick=skip;
$('shoot').onclick=()=>run(async()=>{
  $('shoot').disabled=true;const epoch=accountEpoch,generation=cameraGeneration,mirrored=$('mirror').checked;
  try{let d=await invoke('capture',{id:$('cameraSelect').value});if(epoch!==accountEpoch||generation!==cameraGeneration)return;patch(d);
    if(mirrored){const image=new Image();image.src=await invoke('draft_image',{id:d.id});await image.decode();const out=document.createElement('canvas');out.width=image.naturalWidth;out.height=image.naturalHeight;const c=out.getContext('2d');c.translate(out.width,0);c.scale(-1,1);c.drawImage(image,0,0);d=await saveCanvas(out,`Mirror-${Date.now()}.png`,d.id);}
    if(epoch!==accountEpoch||generation!==cameraGeneration)return;await select(d.id);review=true;reviewMirrored=mirrored;liveTransform();$('live').src=await invoke('draft_image',{id:d.id});
    let seconds=3;$('skip').hidden=false;$('reviewStatus').textContent=`Đã lưu bản nháp · xem lại ${seconds}s`;
    reviewTimer=setInterval(()=>{seconds--;if(seconds<=0)skip();else $('reviewStatus').textContent=`Đã lưu bản nháp · xem lại ${seconds}s`;},1000);
  }catch(e){$('shoot').disabled=false;throw e;}
});

const canvas=$('canvas'),ctx=canvas.getContext('2d');
async function openEditor(){
  if(!selected)return;const image=new Image();image.src=await invoke('draft_image',{id:selected});await image.decode();
  editorSource=image;canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;points=[];$('angle').value='0';$('zoom').value='75';$('editor').showModal();drawEditor();
}
function drawEditor(){
  if(!editorSource)return;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(editorSource,0,0);
  const polygon=outline(points,$('shape').value,Number($('angle').value));if(polygon.length){ctx.save();ctx.lineWidth=Math.max(2,canvas.width/700);ctx.strokeStyle='#72cfff';ctx.fillStyle='#72cfff22';ctx.beginPath();polygon.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();ctx.fill();ctx.stroke();ctx.restore();}
  canvas.style.width=`${canvas.width*Number($('zoom').value)/100}px`;canvas.style.height=`${canvas.height*Number($('zoom').value)/100}px`;
  $('editorInfo').textContent=`${canvas.width} × ${canvas.height} px · gốc được giữ nguyên`;
}
const point=e=>{const r=canvas.getBoundingClientRect();return[Math.max(0,Math.min(canvas.width,(e.clientX-r.left)*canvas.width/r.width)),Math.max(0,Math.min(canvas.height,(e.clientY-r.top)*canvas.height/r.height))];};
canvas.onpointerdown=e=>{drawing=true;canvas.setPointerCapture(e.pointerId);points=[point(e),point(e)];drawEditor();};
canvas.onpointermove=e=>{if(!drawing)return;if($('shape').value==='freehand'){if(points.length<4096)points.push(point(e));}else points[1]=point(e);drawEditor();};
canvas.onpointerup=()=>{drawing=false;drawEditor();};$('shape').onchange=()=>{points=[];drawEditor();};$('angle').oninput=drawEditor;$('zoom').oninput=drawEditor;
$('editorClose').onclick=()=>{$('editor').close();editorSource=null;};
async function saveCanvas(output,name,sourceId=selected){const d=await invoke('save_edit',{data:output.toDataURL('image/png'),name,sourceId});const original=drafts.find(x=>x.id===sourceId);if(original)original.included=false;patch(d);await select(d.id);toast('Đã chọn bản chỉnh sửa để gửi · bản gốc vẫn được giữ');return d;}
$('crop').onclick=()=>run(async()=>{
  const polygon=outline(points,$('shape').value,Number($('angle').value)),r=bounds(polygon,canvas.width,canvas.height),out=document.createElement('canvas');out.width=r.w;out.height=r.h;const c=out.getContext('2d');
  c.fillStyle='#fff';c.fillRect(0,0,r.w,r.h);c.save();c.beginPath();polygon.forEach(([x,y],i)=>i?c.lineTo(x-r.l,y-r.t):c.moveTo(x-r.l,y-r.t));c.closePath();c.clip();c.drawImage(editorSource,-r.l,-r.t);c.restore();
  await saveCanvas(out,`Crop-${Date.now()}.png`);$('editor').close();
});
$('rotate').onclick=()=>run(async()=>{const out=document.createElement('canvas');out.width=canvas.height;out.height=canvas.width;const c=out.getContext('2d');c.translate(out.width,0);c.rotate(Math.PI/2);c.drawImage(editorSource,0,0);await saveCanvas(out,`Rotate-${Date.now()}.png`);$('editor').close();});
$('bw').onclick=()=>run(async()=>{
  $('bw').disabled=true;try{const out=document.createElement('canvas');out.width=canvas.width;out.height=canvas.height;out.getContext('2d').drawImage(editorSource,0,0);const blob=await new Promise(r=>out.toBlob(r,'image/png'));
    const worker=new Worker('bw-worker.mjs',{type:'module'});const result=await new Promise((resolve,reject)=>{worker.onmessage=e=>e.data.error?reject(Error(e.data.error)):resolve(e.data.blob);worker.onerror=reject;worker.postMessage(blob);});worker.terminate();
    const data=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsDataURL(result);});const sourceId=selected,d=await invoke('save_edit',{data,name:`BW-${Date.now()}.png`,sourceId});const original=drafts.find(x=>x.id===sourceId);if(original)original.included=false;patch(d);await select(d.id);$('editor').close();toast('Đã chọn bản đen trắng để gửi · bản gốc vẫn được giữ');
  }finally{$('bw').disabled=false;}
});
run(boot);
