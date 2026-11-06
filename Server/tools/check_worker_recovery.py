"""Intentionally kill only this server's known Python model process mid-job.

Uses local admin credentials, verifies the command line before terminating the
child, and checks the same durable job succeeds with a replacement worker.
"""
import http.cookiejar
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'clients/python'))
from vietocr_remote import VietOcrClient


def run():
    origin='http://127.0.0.1:5080'
    jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
    token=None;entry=None
    def admin(path,method='GET',data=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-CSRF-TOKEN']=token
        with opener.open(urllib.request.Request(origin+'/api/admin'+path,method=method,headers=headers,
            data=None if data is None else json.dumps(data).encode()),timeout=100) as response:
            payload=response.read();return json.loads(payload) if payload else None
    try:
        token=admin('/auth/csrf')['token']
        password=(ROOT/'runtime/admin-first-login.txt').read_text().split('Password: ',1)[1].strip()
        admin('/auth/login','POST',{'username':'admin','password':password});token=admin('/auth/csrf')['token']
        workers=admin('/workers');assert len(workers)==1 and workers[0]['pid']
        old=workers[0];pid=int(old['pid'])
        entry=admin('/clients','POST',{'name':'worker-recovery-'+secrets.token_hex(3),'ratePerMinute':120})
        client=VietOcrClient(origin,entry['key']);job=client.submit(ROOT.parent/'VietHandOCR_API_Release/test2.jpg','line')
        for _ in range(100):
            if client.get(job['id'])['state']=='running':break
            time.sleep(.02)
        else:raise RuntimeError('Could not observe a running job')
        # PID is integer-only and must be an owned server worker. Never kill a
        # random process from a remote URL or an unverified pasted PID.
        command=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if($p.CommandLine -like '*Server*worker/main.py*'){{ Stop-Process -Id {pid};exit 0 }};exit 2"
        subprocess.run(['powershell.exe','-NoProfile','-Command',command],check=True,capture_output=True)
        for _ in range(400):
            result=client.get(job['id'])
            if result['state'] in ('succeeded','failed'):break
            time.sleep(.1)
        assert result['state']=='succeeded' and result['attempts']==2,'Worker recovery did not complete'
        replacement=admin('/workers');assert replacement and replacement[0]['id']!=old['id']
        assert any(ord(c)>=0x100 for c in result['text']),'UTF-8 Vietnamese text was lost'
        report={'api_survived':True,'same_job_recovered':True,'attempts':result['attempts'],
            'new_worker':replacement[0]['id'],'totalMs':result['totalMs'],'utf8_vietnamese_verified':True}
        (ROOT/'validation/worker-recovery.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('PASS native child termination: API stayed alive, same job recovered, attempts=2, Vietnamese UTF-8 intact')
    finally:
        if entry:
            try:admin('/clients/'+entry['client']['id'],'DELETE')
            except Exception:pass


if __name__=='__main__':run()
