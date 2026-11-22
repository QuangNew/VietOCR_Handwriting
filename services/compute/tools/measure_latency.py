"""Compare client wall time and server timings on the same small local fixture set."""
import argparse, hashlib, http.cookiejar, json, pathlib, secrets, sys, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'clients/python'))
from vietocr_remote import VietOcrClient

def main():
    p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--origin',default='http://127.0.0.1:5080');a=p.parse_args()
    assert a.label in ('before','after')
    jar=http.cookiejar.CookieJar();op=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar));csrf=None
    def admin(path,method='GET',data=None):
        req=urllib.request.Request(a.origin+'/api/admin'+path,method=method,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json',**({'X-CSRF-TOKEN':csrf} if csrf else {})})
        with op.open(req,timeout=100) as r:
            raw=r.read();return json.loads(raw) if raw else None
    csrf=admin('/auth/csrf')['token'];password=(ROOT/'runtime/admin-first-login.txt').read_text().split('Password: ',1)[1].strip()
    admin('/auth/login','POST',{'username':'admin','password':password});csrf=admin('/auth/csrf')['token']
    entry=admin('/clients','POST',{'name':'validation-latency-'+secrets.token_hex(4),'ratePerMinute':60})
    class Trace(VietOcrClient):
        def _request(self,method,path,*args,**kwargs):
            t=time.perf_counter();value=super()._request(method,path,*args,**kwargs)
            self.calls.append({'method':method,'route':path.split('?')[0].rsplit('/',1)[0] if '/jobs/' in path else path,'ms':round((time.perf_counter()-t)*1000,2)})
            if isinstance(value,dict) and value.get('state')=='succeeded':self.result=value
            return value
    client=Trace(a.origin,entry['key']);rows=[]
    try:
        fixtures=[ROOT.parents[1]/'shared/contracts/fixtures/images'/n for n in ['test.jpg','test2.jpg']]*2
        for source in fixtures:
            client.calls=[];start=time.perf_counter();text=client.recognize(source,layout='line');wall=(time.perf_counter()-start)*1000
            j=client.result
            row={'image':source.name,'bytes':source.stat().st_size,'wallMs':round(wall,2),'queueMs':j['queueMs'],'inferenceMs':j['inferenceMs'],'serverTotalMs':j['totalMs'],'http':client.calls,'textHash':hashlib.sha256(text.encode()).hexdigest()}
            rows.append(row);print(json.dumps({k:row[k] for k in ('image','wallMs','inferenceMs','serverTotalMs')}),flush=True)
        report={'label':a.label,'clientId':entry['client']['id'],'fixtures':'two packaged text-line images repeated twice; not a production throughput benchmark','auth':'admin-issued service key; does not include Google Auth HTTP','rows':rows,'meanWallMs':sum(r['wallMs'] for r in rows)/len(rows)}
        out=ROOT/'validation'/('latency-'+a.label+'.json');out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    finally:admin('/clients/'+entry['client']['id'],'DELETE')

if __name__=='__main__':main()
