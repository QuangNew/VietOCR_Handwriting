// UI fixture only. This mock is never shipped in the Tauri frontend.
const {chromium}=require('../../../services/compute/web/node_modules/@playwright/test');
const http=require('node:http'),fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../ui');
const mime={'.html':'text/html','.css':'text/css','.mjs':'application/javascript'};
(async()=>{
 const server=http.createServer(async(req,res)=>{try{const name=new URL(req.url,'http://127.0.0.1').pathname;const file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)){res.writeHead(404).end();return;}res.setHeader('Content-Type',mime[path.extname(file)]||'text/plain');res.end(await fs.readFile(file));}catch{res.writeHead(404).end();}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:path.join(process.env.LOCALAPPDATA,'ms-playwright/chromium-1243/chrome-win64/chrome.exe')});
 try{
  const page=await browser.newPage({viewport:{width:1360,height:900}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const jpeg='data:image/jpeg;base64,'+(await fs.readFile(path.resolve(__dirname,'../../../shared/contracts/fixtures/images/test.jpg'))).toString('base64');
  await page.addInitScript(({jpeg})=>{
   const draft={id:'10000000-0000-4000-8000-000000000001',ownerId:'aaaaaaaa-1111-4444-8888-aaaaaaaaaaaa',name:'Trang ghi chú.jpg',state:'draft',imageBytes:204800,mediaType:'image/jpeg',text:'',jobId:null};window.nativeCalls=[];
   window.__TAURI__={core:{Channel:class{onmessage=()=>{};},invoke:async(name,args)=>{
    window.nativeCalls.push({name,args});
    if(name==='bootstrap')return{config:{gateway:'https://pi.example.invalid'},session:{email:'fixture@example.invalid',userId:draft.ownerId},verified:{},workspaceAllowed:true,drafts:[]};
    if(name==='pick_import')return[draft];if(name==='draft_image')return jpeg;
    if(name==='set_included')return{...draft,included:args.included};
    if(name==='prepare_send')return[draft];
    if(name==='send_draft'){
      const attempt=window.nativeCalls.filter(c=>c.name==='send_draft').length;
      if(attempt===1)throw Error('HTTP 503: server_not_ready');
      if(attempt===2)throw Error('HTTP 429: minute_quota');
      return{...draft,state:'queued',jobId:'20000000-0000-4000-8000-000000000001'};
    }
    if(name==='read_result')return{...draft,state:'succeeded',text:'Văn bản kiểm thử'};
    return null;
   }}};
  },{jpeg});
  await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('#workspace').waitFor({state:'visible'});
  await page.click('#settingsButton');assert.equal(await page.locator('#supabase, #publicKey').count(),0);
  await page.click('#saveSettings');await page.waitForFunction(()=>!document.querySelector('#settings').open);
  assert.deepEqual(await page.evaluate(()=>nativeCalls.find(c=>c.name==='configure').args),{gateway:'https://pi.example.invalid'});
  await page.click('#original');await page.waitForFunction(()=>document.querySelectorAll('.draft-row').length===1);
  assert.equal(await page.evaluate(()=>nativeCalls.filter(c=>c.name==='send_draft').length),0,'import must never upload');
  await page.uncheck('.draft-row input[type=checkbox]');await page.waitForFunction(()=>document.querySelector('#send').disabled);assert.equal(await page.locator('#send').isDisabled(),true);
  await page.check('.draft-row input[type=checkbox]');await page.waitForFunction(()=>!document.querySelector('#send').disabled);
  const before=await page.locator('h1').boundingBox();await page.click('#theme');assert.deepEqual(await page.locator('h1').boundingBox(),before);
  await page.click('#edit');await page.locator('#editor').waitFor({state:'visible'});assert.equal(await page.locator('#editor').evaluate(e=>e.scrollWidth<=e.clientWidth),true);
  await page.click('#editorClose');await page.click('#send');await page.waitForFunction(()=>document.querySelector('#jobState').textContent==='Hoàn tất');
  assert.equal(await page.inputValue('#text'),'Văn bản kiểm thử');
  assert.equal(await page.evaluate(()=>nativeCalls.filter(c=>c.name==='send_draft').length),3,'warm-up and rolling-minute deferrals must resume the same explicit send');
  assert.equal(new Set(await page.evaluate(()=>nativeCalls.filter(c=>c.name==='send_draft').map(c=>c.args.id))).size,1);
  await fs.mkdir(path.resolve(__dirname,'../../../.toolchain/refactor/ui'),{recursive:true});
  await page.screenshot({path:path.resolve(__dirname,'../../../.toolchain/refactor/ui/desktop-dark-fixture.png')});
  await page.setViewportSize({width:980,height:700});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:path.resolve(__dirname,'../../../.toolchain/refactor/ui/desktop-compact-fixture.png')});
  assert.deepEqual(errors,[]);console.log('Desktop UI: import/click upload, explicit send, theme geometry, crop dialog and 980px layout PASS (fixture transport).');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
