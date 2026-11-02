import io
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import socket
import threading
import time
import unittest
import zlib
from PIL import Image
from desktop.camera_udp import UdpReassembler,UdpCameraStream,HEADER,PAYLOAD,MAX_BYTES
from desktop.wifi_camera import WifiEndpoint

def fragments(frame,sequence=10,stream=42):
    return [HEADER.pack(b'VOJ1',stream,sequence,len(frame),at,zlib.crc32(frame),640,480,min(PAYLOAD,len(frame)-at),0)+frame[at:at+PAYLOAD]
            for at in range(0,len(frame),PAYLOAD)]

class UdpTests(unittest.TestCase):
    def test_reorder_duplicates_corruption_old_session_and_memory_bounds(self):
        frame=b'\xff\xd8'+b'x'*10007+b'\xff\xd9';parts=fragments(frame);decoder=UdpReassembler(42)
        self.assertIsNone(decoder.feed(parts[-1]));self.assertIsNone(decoder.feed(parts[-1]))
        for part in parts[1:-1]:self.assertIsNone(decoder.feed(part))
        self.assertEqual(decoder.feed(parts[0]),frame)
        for part in parts:self.assertIsNone(decoder.feed(part))
        for seq in range(11,100):
            decoder.feed(fragments(frame,seq)[0]);self.assertLessEqual(len(decoder.pending),2)
        for data in (b'',b'a'*1201,HEADER.pack(b'VOJ1',42,500,MAX_BYTES+1,0,0,640,480,1,0)+b'a',fragments(frame,501,99)[0]):
            self.assertIsNone(decoder.feed(data))
        parts=fragments(frame,500);bad=bytearray(parts[-1]);bad[-1]^=1;parts[-1]=bytes(bad)
        for part in parts:self.assertIsNone(decoder.feed(part))
        self.assertEqual(decoder.corrupt,1)

    def test_real_http_and_udp_renew_stop_reopen_without_revoking_new_reader(self):
        picture=io.BytesIO();Image.new('RGB',(640,480),'green').save(picture,'JPEG');jpeg=picture.getvalue()
        stopped=threading.Event();lock=threading.Lock();destination=[None,0];posts=[]
        udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0))
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.test.assertEqual(self.path,'/stream/udp')
                self.server.test.assertEqual(self.headers.get('Authorization'),'Bearer '+'a'*32)
                self.server.test.assertNotEqual(body['port'],0)
                with lock:
                    destination[0]=(self.client_address[0],body['port']);destination[1]+=1
                    stream=destination[1];posts.append(body['port'])
                raw=json.dumps(dict(active=True,stream=stream,header_bytes=32,datagram_bytes=1200,lease_seconds=60)).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.test=self
        listener=threading.Thread(target=server.serve_forever,daemon=True);listener.start()
        def produce():
            sequence=0
            while not stopped.wait(.025):
                with lock:peer,stream=destination
                if peer:
                    sequence+=1
                    for packet in reversed(fragments(jpeg,sequence,stream)):udp.sendto(packet,peer)
        sender=threading.Thread(target=produce,daemon=True);sender.start()
        endpoint=WifiEndpoint(f'127.0.0.1:{server.server_port}','a'*32)
        active=[]
        def wait(predicate):
            deadline=time.monotonic()+3
            while not predicate():
                if time.monotonic()>deadline:self.fail('UDP operation timed out')
                time.sleep(.01)
        try:
            first=UdpCameraStream(endpoint,source_port=udp.getsockname()[1],renew_seconds=.15).start();active.append(first)
            wait(lambda:first.latest()==jpeg)
            wait(lambda:len(posts)>=2)
            first.stop();first.thread.join(1);self.assertFalse(first.thread.is_alive())
            second=UdpCameraStream(endpoint,source_port=udp.getsockname()[1],renew_seconds=.15).start();active.append(second)
            wait(lambda:second.latest()==jpeg)
            first.stop() # repeated close must not send port=0 against the new stream
            wait(lambda:second.latest()==jpeg)
            self.assertIsNone(second.error())
        finally:
            for reader in active:reader.stop();reader.thread.join(2)
            stopped.set();sender.join(2);udp.close();server.shutdown();server.server_close();listener.join(2)
        self.assertTrue(posts)

if __name__=='__main__':unittest.main()
