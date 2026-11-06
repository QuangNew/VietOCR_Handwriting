"""Local validation helper. Credentials stay in memory and are never printed."""
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


class AdminSession:
    def __init__(self, origin='http://127.0.0.1:5080'):
        self.origin=origin
        self.csrf=None
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf=self('/auth/csrf')['token']
        password=(ROOT/'runtime/admin-first-login.txt').read_text().split('Password: ',1)[1].strip()
        self('/auth/login','POST',{'username':'admin','password':password})
        self.csrf=self('/auth/csrf')['token']

    def __call__(self,path,method='GET',data=None,expected=None):
        headers={'Content-Type':'application/json'}
        if self.csrf:headers['X-CSRF-TOKEN']=self.csrf
        request=urllib.request.Request(self.origin+'/api/admin'+path,method=method,
            data=None if data is None else json.dumps(data).encode(),headers=headers)
        try:response=self.http.open(request,timeout=100)
        except urllib.error.HTTPError as error:
            if error.code!=expected:raise
            response=error
        with response:
            if expected is not None:assert response.status==expected
            raw=response.read()
            return json.loads(raw) if raw else None
