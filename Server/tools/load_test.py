"""Small local, real-model load test with hardware-gated scaling. No network downloads."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.cookiejar
import json
from pathlib import Path
import secrets
import sys
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'clients/python'))
from vietocr_remote import VietOcrClient


def run(args):
    jar=http.cookiejar.CookieJar()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
    token=None
    def admin(path,method='GET',body=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-CSRF-TOKEN']=token
        req=urllib.request.Request(args.origin+'/api/admin'+path,method=method,headers=headers,
            data=None if body is None else json.dumps(body).encode())
        with opener.open(req,timeout=100) as response:
            data=response.read();return json.loads(data) if data else None
    token=admin('/auth/csrf')['token']
    password=(ROOT/'runtime/admin-first-login.txt').read_text().split('Password: ',1)[1].strip()
    admin('/auth/login','POST',{'username':'admin','password':password})
    token=admin('/auth/csrf')['token']
    clients=[]; report={'scenarios':[]}; added=[]
    try:
        for name in ('desktop','android'):
            clients.append(admin('/clients','POST',{'name':'load-'+name+'-'+secrets.token_hex(3),'ratePerMinute':120}))
        transports=[VietOcrClient(args.origin,c['key']) for c in clients]
        for count in (1,2):
            snap=admin('/snapshot')
            if count==2:
                if not snap['capacity']['canAdd']:
                    report['secondWorker']={'admitted':False,'reason':'Hardware RAM/VRAM reserve',
                        'availableRamMiB':snap['memory']['availableMiB'],'capacity':snap['capacity']}
                    break
                try:
                    worker=admin('/workers','POST');added.append(worker['id'])
                    report['secondWorker']={'admitted':True}
                except urllib.error.HTTPError:
                    report['secondWorker']={'admitted':False,'reason':'Post-warmup hardware reserve'};break
            start=time.perf_counter()
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs=list(pool.map(lambda i:(i%2,transports[i%2].submit(args.image,'line')) , range(args.images)))
            results={}
            while len(results)<len(jobs) and time.perf_counter()-start<180:
                for client,j in jobs:
                    if j['id'] in results:continue
                    result=transports[client].get(j['id'])
                    if result['state'] in ('succeeded','failed','cancelled'):results[j['id']]=result
                time.sleep(.15)
            elapsed=time.perf_counter()-start
            assert len(results)==len(jobs) and all(j['state']=='succeeded' for j in results.values()),'Load test failed'
            ordered=sorted(results.values(),key=lambda j:j['startedAt'])
            scenario={'workers':len(admin('/workers')),'images':len(jobs),'wallSeconds':elapsed,
                'imagesPerSecond':len(jobs)/elapsed,'results':[{k:j[k] for k in ('state','clientName','queueMs','inferenceMs','totalMs','attempts')} for j in ordered],
                'workerMemory':[w['memory'] for w in admin('/workers')]}
            report['scenarios'].append(scenario)
            print(f"{count} worker: {len(jobs)} images, {elapsed:.2f}s, {len(jobs)/elapsed:.2f} images/s")
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    finally:
        for worker in added:
            try:admin('/workers/'+worker,'DELETE')
            except Exception:pass
        for c in clients:
            try:admin('/clients/'+c['client']['id'],'DELETE')
            except Exception:pass


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--origin',default='http://127.0.0.1:5080')
    p.add_argument('--image',type=Path,default=ROOT.parent/'VietHandOCR_API_Release/test.jpg')
    p.add_argument('--images',type=int,default=8);p.add_argument('--output',type=Path,default=ROOT/'validation/load-test.json')
    run(p.parse_args())
