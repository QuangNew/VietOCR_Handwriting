"""Verify the actual desktop routing adapter and the production Dart transport.

The temporary validation keys are sent to Dart via stdin, never command-line
arguments, and revoked afterwards. Reports contain hashes/flags only.
"""
import hashlib
import http.cookiejar
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def run():
    jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
    token=None;entries=[]
    def admin(path,method='GET',body=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-CSRF-TOKEN']=token
        with opener.open(urllib.request.Request('http://127.0.0.1:5080/api/admin'+path,method=method,headers=headers,
            data=None if body is None else json.dumps(body).encode()),timeout=30) as response:
            data=response.read();return json.loads(data) if data else None
    try:
        token=admin('/auth/csrf')['token']
        password=(ROOT/'runtime/admin-first-login.txt').read_text().split('Password: ',1)[1].strip()
        admin('/auth/login','POST',{'username':'admin','password':password});token=admin('/auth/csrf')['token']
        for name in ('desktop-adapter','dart-transport'):
            entries.append(admin('/clients','POST',{'name':name+'-'+secrets.token_hex(3),'ratePerMinute':60}))
        sys.path.insert(0,str(ROOT.parent/'VietHandOCR_API_Release'))
        from desktop.ocr_process import OCRProcessService
        from desktop.ocr_contract import OCRSettings
        from types import SimpleNamespace
        from PIL import Image
        image=ROOT.parent/'VietHandOCR_API_Release/test.jpg'
        service=OCRProcessService(auth=SimpleNamespace(access_token=lambda:entries[0]['key']))
        try:
            settings=OCRSettings(layout='line',server_url='http://127.0.0.1:5080')
            with Image.open(image) as photo: desktop=service.recognize(photo,settings,threading.Event())
            assert not hasattr(service,'_process') and 'torch' not in sys.modules,'Desktop loaded a local model'
        finally:service.close();service.closed.wait(3)
        dart=Path('C:/Services/Flutter/flutter/bin/cache/dart-sdk/bin/dart.exe')
        result=subprocess.run([str(dart),str(ROOT/'tools/check_dart_client.dart')],
            input=json.dumps({'origin':'http://127.0.0.1:5080','key':entries[1]['key'],'image':str(image)}),
            text=True,encoding='utf-8',capture_output=True,timeout=60)
        if result.returncode:raise RuntimeError('Dart transport failed: '+result.stderr[:500])
        mobile=json.loads(result.stdout)['text']
        assert mobile==desktop and any(ord(c)>0x100 for c in desktop)
        report={'desktop_no_torch_or_local_worker':True,'dart_real_http_multipart_and_poll':True,
            'identical_vietnamese_result':True,'text_sha256':hashlib.sha256(desktop.encode()).hexdigest()}
        (ROOT/'validation/supabase-app-transports.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('PASS desktop adapter and Dart client use real C# API, identical Vietnamese text, no local desktop model')
    finally:
        for entry in entries:
            try:admin('/clients/'+entry['client']['id'],'DELETE')
            except Exception:pass


if __name__=='__main__':run()
