import { test as base, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Optional: exercise the production HTML/JS/CSS with a real API without opening
// another listener or changing a web server which the owner is currently using.
export const test=base.extend<{productionAssets:void}>({
  productionAssets:[async({context,baseURL},use)=>{
    const directory=process.env.VIETOCR_TEST_STATIC_BUILD;
    const backend=process.env.VIETOCR_TEST_API_ORIGIN;
    if(directory){
      if(!/^\.next-[a-z0-9-]+$/.test(directory) || !backend || !/^http:\/\/127\.0\.0\.1:\d+$/.test(backend))throw new Error("Use a local test build and loopback API.");
      const root=path.resolve(directory),origin=new URL(baseURL!).origin;
      await context.route("**/*",async route=>{
        const request=route.request(),url=new URL(request.url());
        if(url.origin!==origin){await route.fallback();return;}
        if(url.pathname.startsWith("/api/")){
          const response=await route.fetch({url:backend+url.pathname+url.search});
          await route.fulfill({response});return;
        }
        let file:string|undefined;
        if(url.pathname==="/")file=path.join(root,"server/app",request.headers().rsc==="1"?"index.rsc":"index.html");
        else if(url.pathname.startsWith("/_next/static/"))file=path.resolve(root,decodeURIComponent(url.pathname.slice(7)));
        if(file && file.startsWith(root+path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()){
          const ext=path.extname(file),mime:Record<string,string>={".html":"text/html; charset=utf-8",".js":"application/javascript",".css":"text/css",".rsc":"text/x-component",".woff2":"font/woff2"};
          await route.fulfill({status:200,body:fs.readFileSync(file),contentType:mime[ext]||"application/octet-stream"});return;
        }
        await route.fallback();
      });
    }
    try{await use();}finally{if(directory)await context.unrouteAll({behavior:"ignoreErrors"});}
  },{auto:true}],
});
export {expect};
