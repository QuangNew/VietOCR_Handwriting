import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import unittest
from unittest.mock import patch
from desktop.wifi_camera import WifiEndpoint, fetch_jpeg


class PhotoDownloadTests(unittest.TestCase):
    def test_download_resumes_exact_photo_after_tcp_disconnect(self):
        photo=b'\xff\xd8'+bytes(range(256))*2000+b'\xff\xd9'
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                self.assert_token = self.headers['Authorization']
                start,end=map(int,self.headers['Range'][6:].split('-'))
                end=min(end,len(photo)-1)
                requests.append((self.path,start,self.headers.get('If-Range'),self.assert_token))
                self.send_response(206)
                self.send_header('Content-Type','image/jpeg')
                self.send_header('Content-Length',str(end-start+1))
                self.send_header('Content-Range',f'bytes {start}-{end}/{len(photo)}')
                self.send_header('ETag','"photo-42-crc"')
                self.end_headers()
                if len(requests)==1:
                    self.wfile.write(photo[:30000]);self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close()
                else: self.wfile.write(photo[start:end+1])
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        class Endpoint:
            ip=f'127.0.0.1:{server.server_port}'
            token='a'*32
        progress=[]
        try:
            actual=fetch_jpeg(Endpoint(),'/image?id=42',lambda *v:progress.append(v))
        finally:
            server.shutdown();server.server_close();worker.join()
        self.assertEqual(actual,photo)
        self.assertEqual(requests[1][1],30000)
        self.assertTrue(all(row[0]=='/image?id=42' for row in requests))
        self.assertTrue(all(row[2]=='"photo-42-crc"' for row in requests[1:]))
        self.assertTrue(all(row[3]=='Bearer '+'a'*32 for row in requests))
        self.assertEqual(progress[-1],(len(photo),len(photo)))
        self.assertEqual(sorted(p[0] for p in progress),[p[0] for p in progress])

    def test_changed_photo_etag_is_rejected_before_appending(self):
        from test_wifi_camera import Response
        one=Response(b'\xff\xd8ab');one.status=206
        one.headers['Content-Range']='bytes 0-3/8';one.headers['ETag']='"first"'
        two=Response(b'cd\xff\xd9');two.status=206
        two.headers['Content-Range']='bytes 4-7/8';two.headers['ETag']='"different"'
        from types import SimpleNamespace
        responses=iter([one,two])
        with patch('desktop.wifi_camera.build_opener',return_value=SimpleNamespace(open=lambda *a,**k:next(responses))):
            with self.assertRaisesRegex(ValueError,'thay đổi'):
                fetch_jpeg(WifiEndpoint('192.168.1.2','a'*32),'/image?id=42')
