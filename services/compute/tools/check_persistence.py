"""Real MySQL restart/backpressure test. Stop the normal API instance first.

Uses the normal model-independent API with zero workers and a 2-job queue.
Only its own jobs/keys/processes are touched; no schema/database is dropped.
"""
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'clients/python'))
from vietocr_remote import VietOcrClient,ServerError


def run():
    env={**os.environ,'Server__InitialWorkers':'0','Server__QueueCapacity':'2','Server__PerClientPending':'2'}
    process=None;log=None;key=None;token=None
    jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
    origin='http://127.0.0.1:5081'
    def admin(path,method='GET',data=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-CSRF-TOKEN']=token
        with opener.open(urllib.request.Request(origin+'/api/admin'+path,method=method,
            data=None if data is None else json.dumps(data).encode(),headers=headers),timeout=10) as response:
            body=response.read();return json.loads(body) if body else None
    def start():
        nonlocal process,log
        log=open(ROOT/'runtime/persistence-test.log','a',encoding='utf-8')
        process=subprocess.Popen(['dotnet',str(ROOT/'backend/VietOcr.Server/bin/Release/net10.0/VietOcr.Server.dll'),
            '--urls',origin],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                with urllib.request.urlopen(origin+'/api/health/live',timeout=1):break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Test server did not start; ensure normal coordinator is stopped')
    def stop():
        nonlocal process,log
        if process and process.poll() is None:process.terminate();process.wait(timeout=15)
        process=None
        if log:log.close();log=None
    checks=[];jobs=[]
    try:
        start();token=admin('/auth/csrf')['token']
        password=(ROOT/'runtime/admin-first-login.txt').read_text().split('Password: ',1)[1].strip()
        admin('/auth/login','POST',{'username':'admin','password':password});token=admin('/auth/csrf')['token']
        entry=admin('/clients','POST',{'name':'persistence-'+secrets.token_hex(3),'ratePerMinute':120});key=entry['client']['id']
        client=VietOcrClient(origin,entry['key']);image=ROOT.parents[1]/'shared/contracts/fixtures/images/test.jpg'
        for _ in range(2):jobs.append(client.submit(image,'line',secrets.token_hex(16)))
        try:client.submit(image,'line');raise AssertionError('Queue capacity was exceeded')
        except ServerError as error:assert getattr(error,'retry_after',None) is not None
        checks.append('bounded queue returns 429 with Retry-After')
        assert all(client.get(j['id'])['state']=='queued' for j in jobs)
        stop();start();time.sleep(.5)
        assert all(client.get(j['id'])['state']=='queued' for j in jobs)
        checks.append('MySQL jobs and image spool survive coordinator restart')
        for j in jobs:client.cancel(j['id'])
        assert all(client.get(j['id'])['state']=='cancelled' for j in jobs)
        assert not any((ROOT/f"runtime/images/{j['id']}.image").exists() for j in jobs)
        checks.append('recovered queue can be cancelled and input images removed')
        report={'checks':checks,'count':len(checks),'database':'XAMPP MariaDB 10.4.32'}
        (ROOT/'validation/persistence-checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('\n'.join('PASS '+item for item in checks))
    finally:
        if key:
            try:token=admin('/auth/csrf')['token'];admin('/clients/'+key,'DELETE')
            except Exception:pass
        stop()


if __name__=='__main__':run()
