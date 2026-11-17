// Opt-in smoke against our already running Windows EXE, never a mock bridge.
// Start a diagnostic instance with WebView2 CDP on loopback9226. No OCR upload.
const {chromium}=require('../../Server/web/node_modules/@playwright/test');
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
(async()=>{
 const browser=await chromium.connectOverCDP('http://127.0.0.1:9226');
 const page=browser.contexts().flatMap(c=>c.pages()).find(p=>/^https?:\/\/tauri\.localhost\//.test(p.url()));
 if(!page)throw Error('Expected own Tauri local document. Do not attach to a normal browser.');
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 const call=(name,args={})=>page.evaluate(({name,args})=>window.__TAURI__.core.invoke(name,args),{name,args});
 const before=await call('bootstrap'),known=new Set(before.drafts.map(d=>d.id)),created=[];
 assert.ok(before.verified,'real Pi verification required');
 assert.deepEqual(Object.keys(before.config),['gateway'],'Supabase configuration is not a user-facing setting');
 assert.equal(await page.locator('#supabase, #publicKey').count(),0);
 try{
  await page.click('#cameraButton');await page.locator('#camera').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('#cameraStatus').textContent==='Đang xem trực tiếp'&&document.querySelector('#live').naturalWidth>0,{},{timeout:25000});
  await page.evaluate(()=>{window.nativeFrameCount=0;document.querySelector('#live').addEventListener('load',()=>window.nativeFrameCount++);});
  const start=Date.now();await page.waitForTimeout(5000);const frames=await page.evaluate(()=>window.nativeFrameCount),elapsed=(Date.now()-start)/1000;
  const dimensions=await page.locator('#live').evaluate(e=>({width:e.naturalWidth,height:e.naturalHeight}));
  assert.ok(frames>=10,'real binary IPC frames must continue without an unbounded queue');
  await page.click('#shoot');await page.locator('#skip').waitFor({state:'visible',timeout:25000});
  const after=await call('bootstrap');created.push(...after.drafts.filter(d=>!known.has(d.id)).map(d=>d.id));
  assert.equal(created.length,1);const captured=after.drafts.find(d=>d.id===created[0]);
  assert.equal(captured.state,'draft');assert.equal(captured.jobId,null);
  assert.equal(captured.width,dimensions.width);assert.equal(captured.height,dimensions.height);
  const countBefore=before.verified.account.usedToday,countAfter=after.verified.account.usedToday;
  assert.equal(countAfter,countBefore,'capture alone must not charge OCR');
  await page.waitForTimeout(3300);assert.equal(await page.locator('#camera').evaluate(e=>e.open),true);
  // Mirror is saved as a full-size lossless derivative. The untouched camera
  // JPEG remains available and is unchecked to avoid sending the same photo twice.
  await page.check('#mirror');await page.click('#shoot');
  await page.locator('#skip').waitFor({state:'visible',timeout:25000});
  const mirroredState=await call('bootstrap');
  for(const d of mirroredState.drafts)if(!known.has(d.id)&&!created.includes(d.id))created.push(d.id);
  const mirrored=mirroredState.drafts.find(d=>created.includes(d.id)&&d.mediaType==='image/png');
  assert.ok(mirrored,'saved mirror derivative required');assert.equal(mirrored.included,true);
  assert.equal(mirrored.width,dimensions.width);assert.equal(mirrored.height,dimensions.height);
  assert.ok(mirroredState.drafts.some(d=>created.includes(d.id)&&d.mediaType==='image/jpeg'&&d.included===false));
  assert.equal(mirroredState.verified.account.usedToday,countBefore);
  await fs.mkdir(path.resolve(__dirname,'../../.toolchain/refactor/ui'),{recursive:true});
  await page.screenshot({path:path.resolve(__dirname,'../../.toolchain/refactor/ui/native-camera-private.png')});
  await page.click('#cameraClose');assert.deepEqual(errors,[]);
  const sample='data:image/jpeg;base64,'+(await fs.readFile(path.resolve(__dirname,'../../Mobile/assets/samples/test.jpg'))).toString('base64');
  const png=await page.evaluate(async source=>{const im=new Image();im.src=source;await im.decode();const canvas=document.createElement('canvas');canvas.width=im.naturalWidth;canvas.height=im.naturalHeight;canvas.getContext('2d').drawImage(im,0,0);return canvas.toDataURL('image/png');},sample);
  const source=await call('save_edit',{data:png,name:'Native-Smoke-Sample.png',sourceId:null});created.push(source.id);
  const optimizeStart=Date.now();const optimized=await call('optimize_draft',{id:source.id});const optimizeMs=Date.now()-optimizeStart;
  if(!created.includes(optimized.id))created.push(optimized.id);
  assert.equal(optimized.width,source.width);assert.equal(optimized.height,source.height);
  assert.ok(optimized.imageBytes<source.imageBytes,'full-size derivative must save bytes');
  const final=await call('bootstrap');assert.equal(final.drafts.find(d=>d.id===source.id).included,false);
  assert.equal(final.verified.account.usedToday,countBefore);
  const report={scope:'actual Windows Tauri EXE, current-user DPAPI session, real Pi camera through encrypted SSH forward; no public DNS bypass claim',piSessionVerified:true,width:dimensions.width,height:dimensions.height,renderedFrames:frames,seconds:elapsed,renderedFps:frames/elapsed,captureStayedDraft:true,reviewAutoReturnedWithoutClosingCamera:true,captureQuotaUnchanged:true,savedMirrorFullResolution:true,originalDeselectedAfterEdit:true,optionalOptimization:{milliseconds:optimizeMs,sourceBytes:source.imageBytes,optimizedBytes:optimized.imageBytes,width:source.width,height:source.height},javascriptErrors:errors.length,ocrRequests:0};
  await fs.writeFile(path.resolve(__dirname,'../../.toolchain/refactor/native-camera-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{
  for(const id of created)await call('remove_draft',{id});
  await page.evaluate(()=>{document.querySelector('#camera').close();return window.__TAURI__.core.invoke('camera_stop');});
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
