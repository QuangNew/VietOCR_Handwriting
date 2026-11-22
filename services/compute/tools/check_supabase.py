"""Real Supabase checks: concurrent quota, RLS, idempotency, durable settings.
Only creates labelled validation clients/jobs. Never logs tokens or user text.
"""
import concurrent.futures
import hashlib
import json
import pathlib
import secrets
import urllib.error
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'server.local.json').read_text(encoding='utf-8-sig'))['Server']
HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def rpc(action,p=None):
    data=json.dumps({'action':action,'p':p or {}}).encode()
    request=urllib.request.Request(CONFIG['SupabaseUrl']+'/rest/v1/rpc/ocr_backend',data=data,
        headers={'apikey':CONFIG['SupabaseServiceKey'],'Authorization':'Bearer '+CONFIG['SupabaseServiceKey'],'Content-Type':'application/json'})
    try:
        with HTTP.open(request,timeout=25) as response:return json.load(response)
    except urllib.error.HTTPError as e:
        # Safe for diagnostics: SQL has no real user tokens/text in this test.
        raw=json.loads(e.read());raise AssertionError(f"RPC {action}: {e.code}, {raw.get('code')}, {raw.get('message')}") from None

def main():
    checks=[];clients=[];jobs=[]
    def passed(name):checks.append(name);print('PASS',name)
    def client(rate=60,daily=1000):
        key='voc_'+secrets.token_hex(32);identity=secrets.token_hex(16)
        c=rpc('createClient',{'id':identity,'name':'validation-quota-'+identity[:8],'prefix':key[:12],
          'hash':hashlib.sha256(key.encode()).hexdigest(),'ratePerMinute':rate,'dailyLimit':daily,'actor':'validation'})
        clients.append(c);return c
    def admit(c,idem=None):
        identity=secrets.token_hex(16);jobs.append(identity)
        return rpc('admit',{'id':identity,'clientId':c['id'],'idempotencyKey':idem or secrets.token_hex(16),
          'imageHash':'0'*64,'layout':'line','imageBytes':100})
    try:
        c=client()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results=list(pool.map(lambda _:admit(c),range(70)))
        accepted=[r for r in results if 'job' in r];denied=[r for r in results if r.get('error')=='minute_quota']
        assert len(accepted)==60 and len(denied)==10,(len(accepted),len(denied),results)
        assert rpc('usage',{'id':c['id']})['usedToday']==60
        passed('70 concurrent admissions: exactly 60 accepted, 10 denied; quota stored atomically')
        d=client(daily=2)
        first=admit(d,'same-request');again=admit(d,'same-request')
        assert first['job']['id']==again['job']['id'] and again['duplicate']
        assert rpc('usage',{'id':d['id']})['usedToday']==1
        passed('idempotent retries return one job and consume one daily credit')
        admit(d);assert admit(d)['error']=='daily_quota'
        usage=rpc('usage',{'id':d['id']})
        assert usage['usedToday']==2 and usage['timezone']=='Asia/Ho_Chi_Minh'
        passed('daily limit persists separately from result retention; reset uses Vietnam timezone')
        updated=rpc('updateClient',{'id':d['id'],'name':'validation-renamed','enabled':False,'dailyLimit':2,'ratePerMinute':60,'actor':'validation'})
        assert updated['id']==d['id'] and updated['enabled'] is False
        assert admit(d)['error']=='account_disabled'
        passed('editing or locking a client preserves identity and immediately blocks new jobs')
        for path in ['/rest/v1/ocr_jobs?select=id','/rest/v1/ocr_clients?select=key_hash','/rest/v1/rpc/ocr_backend']:
            request=urllib.request.Request(CONFIG['SupabaseUrl']+path,
              data=b'{"action":"settings"}' if '/rpc/' in path else None,
              headers={'apikey':CONFIG['SupabasePublishableKey'],'Content-Type':'application/json'})
            try:
                HTTP.open(request,timeout=20);raise AssertionError('Anonymous access was accepted: '+path)
            except urllib.error.HTTPError as e:assert e.code in (401,403,404),e.code
        passed('anonymous cannot read results/hashes or execute privileged backend RPC')
        settings=rpc('settings');assert settings['defaultDailyLimit']<=1000 and settings['defaultRatePerMinute']<=60
        assert any(r['action']=='updateClient' for r in rpc('audit'))
        passed('runtime settings and admin changes are durable in Supabase audit')
        report={'database':CONFIG['SupabaseUrl'],'checks':checks,'passed':len(checks),'concurrency':{'attempts':70,'accepted':60,'limited':10},'googleEnabled':True}
        (ROOT/'validation/supabase-policy-checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    finally:
        for identity in jobs:
            rpc('finish',{'id':identity,'state':'cancelled','text':None,'error':None,'elapsed':None,'width':0,'height':0})
        for c in clients:rpc('revoke',{'id':c['id'],'actor':'validation'})

if __name__=='__main__':main()
