import json
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch
from desktop.cloud_auth import CloudAuth

class CloudAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'prefs.json'
        self.auth=CloudAuth(self.path)
    def tearDown(self):self.temp.cleanup()

    def test_pkce_callback_exchange_persists_encrypted_session_and_releases_port(self):
        def browser(url):
            args=urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            self.assertEqual(args['code_challenge_method'],['s256'])
            self.assertNotIn('code_verifier',args)
            with urllib.request.urlopen('http://127.0.0.1:47821/auth/callback?code=test-one-use-code',timeout=3) as response:
                self.assertEqual(response.status,200)
        def open_browser(url):
            thread=threading.Thread(target=browser,args=(url,),daemon=True);thread.start();return True
        session={'access_token':'test-access','refresh_token':'private-refresh','expires_in':3600,
                 'user':{'email':'test@example.invalid'},'provider_token':'unneeded-google-token'}
        with patch('desktop.cloud_auth.webbrowser.open',open_browser),patch.object(self.auth,'_request',return_value=session) as exchange:
            self.auth.login()
            self.assertEqual(exchange.call_args.args[0],'token?grant_type=pkce')
            self.assertEqual(exchange.call_args.args[1]['auth_code'],'test-one-use-code')
            self.assertGreaterEqual(len(exchange.call_args.args[1]['code_verifier']),43)
        encoded=self.path.read_text()
        self.assertNotIn('private-refresh',encoded);self.assertNotIn('test-access',encoded)
        restored=CloudAuth(self.path)
        self.assertEqual(restored.access_token(),'test-access')
        self.assertNotIn('provider_token',restored.session)
        import socket
        with socket.socket() as listener:listener.bind(('127.0.0.1',47821))

    def test_expired_session_refresh_does_not_overwrite_saved_identity_on_network_failure(self):
        self.auth._save({'access_token':'expired','refresh_token':'refresh','expires_in':-10,'user':{'email':'old@example.invalid'}})
        with patch.object(self.auth,'_request',side_effect=RuntimeError('no network')):
            with self.assertRaisesRegex(RuntimeError,'no network'):self.auth.access_token()
        self.assertEqual(self.auth.session['refresh_token'],'refresh')
        self.assertEqual(self.auth.email,'old@example.invalid')

    def test_cancelled_login_closes_listener_without_saving_a_session(self):
        cancel=threading.Event();cancel.set()
        with patch('desktop.cloud_auth.webbrowser.open'):
            with self.assertRaises(RuntimeError):self.auth.login(cancel)
        self.assertFalse(self.auth.session)
        import socket
        with socket.socket() as listener:listener.bind(('127.0.0.1',47821))

if __name__=='__main__':unittest.main()
