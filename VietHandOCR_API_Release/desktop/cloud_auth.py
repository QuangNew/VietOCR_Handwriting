"""Google OAuth PKCE in the system browser; current-user DPAPI session storage.

The fixed OCR identity is public. Only short-lived, server-verified Supabase JWTs
authenticate requests. Refresh tokens never appear in logs or command arguments.
"""
import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from .credential_store import protect_api_key, _crypt
from .preferences import read_preferences, update_preferences
from .remote_transport import NoRedirect

REDIRECT = 'http://127.0.0.1:47821/auth/callback'

class CloudAuth:
    def __init__(self, preferences_path):
        self.path = preferences_path
        self.config = json.loads(Path(__file__).with_name('cloud_config.json').read_text(encoding='utf-8-sig'))
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self._lock = threading.RLock()
        self.session = {}
        try:
            raw = read_preferences(self.path).get('google_session_dpapi', '')
            if raw:
                self.session = json.loads(_crypt(base64.b64decode(raw), True))
        except (ValueError, OSError, RuntimeError):
            self.session = {}

    @property
    def email(self):
        return self.session.get('user', {}).get('email', '')

    def _request(self, path, body=None, token=None):
        req = urllib.request.Request(self.config['url'] + '/auth/v1/' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'apikey': self.config['publishableKey'], 'Content-Type': 'application/json',
                     **({'Authorization': 'Bearer ' + token} if token else {})})
        try:
            with self.http.open(req, timeout=15) as response:
                payload=response.read(131072)
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError('Không xác thực được Google. Kiểm tra Google provider và callback trong Supabase; thử đăng nhập lại.') from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('Không kết nối được Supabase Auth. Kiểm tra Internet.') from None

    def _save(self, session):
        if session:
            session['expires_at'] = time.time() + session.get('expires_in', 3600)
            # Google provider tokens are not needed for OCR; never retain them.
            session.pop('provider_token', None)
            session.pop('provider_refresh_token', None)
        update_preferences(self.path, google_session_dpapi=protect_api_key(json.dumps(session)) if session else '',
                           ocr_server_key_dpapi='', ocr_server_enabled=True)
        self.session = session

    def access_token(self):
        with self._lock:
            if not self.session.get('refresh_token'):
                raise RuntimeError('Mở OCR Server và đăng nhập Google trước khi nhận diện.')
            if self.session.get('expires_at', 0) < time.time() + 90:
                try:
                    self._save(self._request('token?grant_type=refresh_token', {'refresh_token': self.session['refresh_token']}))
                except RuntimeError:
                    # Keep the refresh token on network errors; never fall back to a local model.
                    raise
            return self.session['access_token']

    def login(self, cancel=None):
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        result = {}
        class Callback(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != '/auth/callback':
                    self.send_error(404); return
                query = urllib.parse.parse_qs(parsed.query)
                if query.get('code'): result['code'] = query['code'][0]
                elif query.get('error'): result['error'] = True
                else:
                    self.send_error(400); return
                data = 'Đã trở về VietOCR. Bạn có thể đóng tab này.'.encode('utf-8')
                self.send_response(200); self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        try:
            listener = http.server.HTTPServer(('127.0.0.1', 47821), Callback)
        except OSError:
            raise RuntimeError('Cổng đăng nhập 47821 đang bận. Đóng cửa sổ đăng nhập VietOCR khác rồi thử lại.') from None
        listener.timeout = .4
        try:
            url = self.config['url'] + '/auth/v1/authorize?' + urllib.parse.urlencode({
                'provider': 'google', 'redirect_to': REDIRECT, 'code_challenge': challenge,
                'code_challenge_method': 's256', 'prompt': 'select_account'})
            webbrowser.open(url)
            deadline = time.monotonic() + 180
            while not result and time.monotonic() < deadline and not (cancel and cancel.is_set()):
                listener.handle_request()
            if not result.get('code'):
                raise RuntimeError('Đăng nhập đã huỷ hoặc quá hạn. Kiểm tra callback Supabase rồi thử lại.')
            with self._lock:
                self._save(self._request('token?grant_type=pkce', {'auth_code': result['code'], 'code_verifier': verifier}))
        finally:
            listener.server_close()

    def logout(self):
        with self._lock:
            try:
                if self.session.get('access_token'):
                    self._request('logout?scope=local', {}, self.session['access_token'])
            finally:
                self._save({})
