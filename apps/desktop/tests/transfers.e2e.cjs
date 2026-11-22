// Browser-only IPC fixture: no Google users, API keys or live OCR jobs are created.
const {chromium}=require('../../../services/compute/web/node_modules/@playwright/test');
const http=require('node:http'),fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../ui');
 const server=http.createServer(async(req,res)=>{try{const file=path.resolve(root,'.'+new URL(req.url,'http://localhost').pathname.replace(/\/$/,'/index.html'));if(!file.startsWith(root+path.sep)){res.writeHead(404).end();return;}res.setHeader('Content-Type',file.endsWith('.mjs')?'application/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(await fs.readFile(file));}catch{res.writeHead(404).end();}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:path.join(process.env.LOCALAPPDATA,'ms-playwright/chromium-1243/chrome-win64/chrome.exe')});
 const errors=[];
 async function page(mode){
  const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1.5});page.on('pageerror',e=>errors.push(String(e)));
  await page.addInitScript(({mode})=>{
   const owner='aaaaaaaa-1111-4444-8888-aaaaaaaaaaaa';
   const drafts=Array.from({length:mode==='restore'?1:3},(_,i)=>({id:'draft-'+i,ownerId:owner,name:'Ảnh gốc có tên rất dài để kiểm tra xuống dòng '+i+'.png',state:mode==='restore'?'cancel_pending':'draft',included:true,mediaType:'image/png',imageBytes:40000,text:'',jobId:mode==='restore'?'job-0':null}));
   const pending=new Map(),stops=new Map();window.calls=[];window.progress=[];window.activeStops=0;window.peakStops=0;
   window.__TAURI__={core:{Channel:class{onmessage=()=>{};},invoke:async(name,args={})=>{
    window.calls.push({name,args});const d=drafts.find(d=>d.id===args.id);
    if(name==='bootstrap')return{config:{gateway:'https://pi.example.invalid'},session:{userId:owner,email:'fixture@example.invalid'},verified:{},drafts:structuredClone(drafts)};
    if(name==='draft_image')return 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>';
    if(name==='prepare_send')return drafts.filter(d=>args.ids.includes(d.id)).map(d=>({...d,state:'draft'}));
    if(name==='send_draft'){window.progress.push(args.progress);args.progress.onmessage({stage:'optimizing',done:0,total:0});return new Promise(resolve=>pending.set(args.id,resolve));}
    if(name==='stop_draft'){
      window.activeStops++;window.peakStops=Math.max(window.peakStops,window.activeStops);await new Promise(r=>setTimeout(r,30));window.activeStops--;
      const attempt=(stops.get(d.id)||0)+1;stops.set(d.id,attempt);
      if(mode==='restore'){
        if(attempt===1)return{...d,state:'cancel_pending',error:'Đã dừng trên máy · chưa xác nhận server'};
        d.state='succeeded';d.text='Kết quả đã hoàn tất trước yêu cầu dừng';return{...d};
      }
      d.state='cancelled';setTimeout(()=>pending.get(d.id)?.({...d,state:'queued',jobId:'late-job'}),25);return{...d};
    }
    if(name==='read_result')throw Error('Unexpected result poll after Stop');
    return null;
   }}};
  },{mode});
  await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('#workspace').waitFor({state:'visible'});return page;
 }
 try{
  const p=await page('batch');await p.click('#send');await p.waitForFunction(()=>calls.filter(c=>c.name==='send_draft').length===2);
  const box=await p.locator('#transfers').boundingBox();assert.ok(box.y>=8&&box.y+box.height<=720-50,'panel stays above bottom screen edge');
  await p.click('#hideTransfers');await p.locator('#showTransfers').waitFor({state:'visible'});
  await p.evaluate(()=>progress[0].onmessage({stage:'uploading',done:50,total:100}));assert.equal(await p.locator('#transfers').isHidden(),true,'updates must not reopen a collapsed panel');
  await p.click('#showTransfers');await p.click('[data-stop-id="draft-0"]');
  await p.waitForFunction(()=>calls.filter(c=>c.name==='send_draft').length===3);
  await p.click('#stopAllTransfers');await p.waitForFunction(()=>document.querySelectorAll('.draft-name small').length===3&&[...document.querySelectorAll('.draft-name small')].every(e=>e.textContent==='Đã dừng'));
  await p.waitForTimeout(150);assert.equal(await p.evaluate(()=>calls.filter(c=>c.name==='read_result').length),0,'late send completion cannot restart polling');
  assert.equal(await p.evaluate(()=>calls.filter(c=>c.name==='stop_draft').length),3);
  await p.setViewportSize({width:980,height:480});const small=await p.locator('#transfers').boundingBox();assert.ok(small.y>=8&&small.y+small.height<=480-50);
  await fs.mkdir(path.resolve(__dirname,'../../../.toolchain/refactor/ui'),{recursive:true});await p.screenshot({path:path.resolve(__dirname,'../../../.toolchain/refactor/ui/desktop-stop-compact.png')});
  const bulk=await page('bulk');await bulk.click('#send');await bulk.waitForFunction(()=>calls.filter(c=>c.name==='send_draft').length===2);await bulk.click('#stopAllTransfers');
  await bulk.waitForFunction(()=>[...document.querySelectorAll('.draft-name small')].every(e=>e.textContent==='Đã dừng'));
  assert.ok(await bulk.evaluate(()=>peakStops<=2),'Stop all must bound remote cancellations');
  assert.equal(await bulk.evaluate(()=>calls.filter(c=>c.name==='send_draft').length),2,'an unsent queued image cannot begin upload after Stop all');
  const restored=await page('restore');await restored.locator('[data-stop-id="draft-0"]').waitFor();assert.equal(await restored.locator('#send').isDisabled(),true);
  await restored.click('[data-stop-id="draft-0"]');await restored.waitForFunction(()=>document.querySelector('.stop-transfer[data-stop-id]')?.textContent==='Thử dừng lại');
  await restored.click('[data-stop-id="draft-0"]');await restored.waitForFunction(()=>document.querySelector('#jobState').textContent==='Hoàn tất');
  assert.equal(await restored.inputValue('#text'),'Kết quả đã hoàn tất trước yêu cầu dừng');
  assert.equal(await restored.evaluate(()=>calls.filter(c=>c.name==='send_draft').length),0);
  assert.deepEqual(errors,[]);console.log('Desktop transfers PASS: in-flight Stop / Stop all, late-result guard, retry pending Stop, completed-result retention, collapse/reopen, and short-screen bounds.');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
