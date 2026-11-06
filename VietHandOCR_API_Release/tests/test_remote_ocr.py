import os
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch, Mock
from PIL import Image
from desktop.ocr_contract import OCRSettings, RecognitionCancelled, RecognitionError
from desktop.ocr_process import OCRProcessService
from desktop.credential_store import protect_api_key, _crypt
import base64

class RemoteTests(unittest.TestCase):
    def test_load_uses_google_session_and_never_spawns_model(self):
        auth=Mock();auth.access_token.return_value='test-session'
        service=OCRProcessService(auth=auth)
        with patch('desktop.ocr_process.VietOcrClient') as client:
            service.load(OCRSettings())
            self.assertEqual(client.call_args.args[1],auth.access_token)
            client.return_value.check.assert_called_once()
            self.assertFalse(hasattr(service,'_process'))
            self.assertFalse(hasattr(service,'_start_worker'))
        service.close()

    def test_server_failure_cannot_fall_back_to_local(self):
        from desktop.remote_transport import ServerError
        service=OCRProcessService(auth=Mock())
        with patch('desktop.ocr_process.VietOcrClient') as client:
            client.return_value.check.side_effect=ServerError('offline')
            with self.assertRaisesRegex(RecognitionError,'offline'): service.load(OCRSettings())
        self.assertFalse(hasattr(service,'_process'));service.close()

    def test_cancelled_remote_never_connects(self):
        cancel=threading.Event();cancel.set();service=OCRProcessService(auth=Mock())
        with patch('desktop.ocr_process.VietOcrClient') as client:
            with self.assertRaises(RecognitionCancelled): service.load(OCRSettings(),cancel)
            client.assert_not_called()
        service.close()

    def test_settings_have_no_weights_devices_or_secrets(self):
        settings=OCRSettings()
        self.assertFalse(hasattr(settings,'weights'));self.assertFalse(hasattr(settings,'device'))
        self.assertFalse(hasattr(settings,'api_key'))
        self.assertEqual(replace(settings,layout='line').layout,'line')

    def test_image_upload_is_temporary_and_deleted_after_failure(self):
        from pathlib import Path
        from desktop.remote_transport import ServerError
        service=OCRProcessService(auth=Mock());service._remote=Mock()
        paths=[]
        def fail(path,**_): paths.append(path);self.assertTrue(Path(path).is_file());raise ServerError('timeout')
        service._remote.recognize.side_effect=fail
        with self.assertRaisesRegex(RecognitionError,'timeout'):
            service.recognize(Image.new('RGB',(20,20)),OCRSettings(),threading.Event())
        self.assertTrue(paths);self.assertFalse(paths[0].exists());service.close()

    def test_original_jpeg_is_uploaded_without_reencoding_or_deleting_it(self):
        import tempfile
        from pathlib import Path
        service=OCRProcessService(auth=Mock());service._remote=Mock()
        service._remote.recognize.return_value='Tiếng Việt'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'original.jpg'
            Image.new('RGB',(40,30),'white').save(path,'JPEG')
            original=path.read_bytes()
            with patch('desktop.ocr_process.tempfile.NamedTemporaryFile') as temporary:
                self.assertEqual(service.recognize(path,OCRSettings(),threading.Event()),'Tiếng Việt')
                temporary.assert_not_called()
            self.assertEqual(service._remote.recognize.call_args.args[0],path)
            self.assertEqual(path.read_bytes(),original)
        service.close()

    def test_request_parallelism_follows_ready_workers_with_bounded_connections(self):
        for count,expected in [(0,1),(1,1),(2,2),(30,4)]:
            service=OCRProcessService(auth=Mock())
            with patch('desktop.ocr_process.VietOcrClient') as client:
                client.return_value.check.return_value={'readyWorkers':count}
                service.load(OCRSettings())
                self.assertEqual(service.parallelism,expected)
            service.close()

    @unittest.skipUnless(os.name=='nt','DPAPI is Windows-specific')
    def test_oauth_session_is_encrypted_for_current_user(self):
        raw='{"refresh_token":"private-refresh-token"}'
        encrypted=protect_api_key(raw)
        self.assertNotIn('private-refresh-token',encrypted)
        self.assertEqual(_crypt(base64.b64decode(encrypted),True).decode(),raw)

    def test_transport_refuses_credential_redirect_and_untrusted_http(self):
        from desktop.remote_transport import VietOcrClient, NoRedirect
        from urllib.error import HTTPError
        with self.assertRaises(ValueError):VietOcrClient('http://example.com','x')
        with self.assertRaises(ValueError):VietOcrClient('http://127.0.0.1/path','x')
        with self.assertRaises(HTTPError):NoRedirect().redirect_request(Mock(full_url='https://one'),None,302,'',{},'https://other')
        VietOcrClient('http://192.168.1.2:5080','x',allow_insecure_lan=True)

if __name__=='__main__':unittest.main()
