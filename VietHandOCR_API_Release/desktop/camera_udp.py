"""OV5640 UDP preview: bounded reassembly, latest frame only, cancellable I/O."""
import json
import logging
import queue
import socket
import struct
import threading
import time
import zlib
from urllib.request import Request, ProxyHandler, build_opener
from urllib.parse import urlsplit

LOGGER = logging.getLogger('vietocr_desktop.camera')
HEADER = struct.Struct('<4sIIIIIHHHH')
PAYLOAD = 1200 - HEADER.size
MAX_BYTES = 2 * 1024 * 1024
_CONTROL_LOCK = threading.Lock()


class UdpReassembler:
    def __init__(self, stream):
        self.stream = stream
        self.pending = {}
        self.completed = 0
        self.corrupt = 0

    def feed(self, packet):
        if not HEADER.size <= len(packet) <= 1200:
            return None
        magic,stream,seq,total,offset,crc,width,height,count,reserved = HEADER.unpack_from(packet)
        if (magic != b'VOJ1' or stream != self.stream or not seq or seq <= self.completed or
                not 4 <= total <= MAX_BYTES or offset >= total or offset % PAYLOAD or reserved or
                count != min(PAYLOAD,total-offset) or len(packet) != HEADER.size+count or
                not 160 <= width <= 2592 or width*3 != height*4):
            return None
        if seq not in self.pending:
            if len(self.pending) >= 2:
                oldest = min(self.pending)
                if seq < oldest: return None
                del self.pending[oldest]
            self.pending[seq] = (bytearray(total),bytearray((total+PAYLOAD-1)//PAYLOAD),0,crc,width,height)
        frame,seen,received,expected,w,h = self.pending[seq]
        if len(frame) != total or (crc,width,height) != (expected,w,h): return None
        index = offset//PAYLOAD
        if seen[index]: return None
        frame[offset:offset+count] = packet[HEADER.size:]
        seen[index] = 1; received += count
        self.pending[seq] = (frame,seen,received,expected,w,h)
        if received != total: return None
        del self.pending[seq]
        if zlib.crc32(frame) != crc or not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9'):
            self.corrupt += 1; return None
        self.completed = seq
        self.pending = {key:value for key,value in self.pending.items() if key > seq}
        return bytes(frame)


def control_preview(endpoint, port):
    from .wifi_camera import _NoRedirect, http_error
    request = Request(f'http://{endpoint.ip}/stream/udp', data=json.dumps({'port':port}).encode(),
                      headers={'Authorization':f'Bearer {endpoint.token}','Content-Type':'application/json'})
    try:
        with build_opener(ProxyHandler({}),_NoRedirect()).open(request,timeout=4) as response:
            data = response.read(1025)
            if len(data)>1024: raise ValueError('Phản hồi UDP quá lớn.')
            state = json.loads(data)
            if (not isinstance(state,dict) or state.get('active') is not True or
                    type(state.get('stream')) is not int or not 1<=state['stream']<=0xffffffff or
                    state.get('header_bytes')!=32 or state.get('datagram_bytes')!=1200 or
                    state.get('lease_seconds')!=60):
                raise ValueError('Nạp firmware OV5640 3.0.0 trở lên để xem preview UDP.')
            return state['stream']
    except (OSError,ValueError) as error:
        if isinstance(error,ValueError): raise
        raise http_error(endpoint,error) from None


class UdpCameraStream:
    def __init__(self, endpoint, *, source_port=82, first_timeout=16, idle_timeout=6, renew_seconds=20):
        self.endpoint=endpoint; self.source_port=source_port
        self.first_timeout=first_timeout; self.idle_timeout=idle_timeout; self.renew_seconds=renew_seconds
        self.frames=queue.Queue(maxsize=1); self.errors=queue.Queue(maxsize=1)
        self.stopped=threading.Event(); self._socket=None
        self.stage='mở preview UDP'; self.thread=threading.Thread(target=self._run,name='VietOCR-UDP',daemon=True)

    def start(self): self.thread.start(); return self
    def stop(self):
        self.stopped.set()
        if self._socket is not None:
            try: self._socket.close()
            except OSError: pass
        # CAM CLOSE / SHOT / disconnect stops the firmware. Never send a late
        # unscoped port=0 here: it could revoke the next preview's new lease.

    def latest(self):
        try: return self.frames.get_nowait()
        except queue.Empty: return None
    def error(self):
        try: return self.errors.get_nowait()
        except queue.Empty: return None

    def _activate(self, port):
        # Preserve ordering across stop/reopen while a previous HTTP renewal
        # is finishing. A stopped reader cannot redirect the new reader's feed.
        with _CONTROL_LOCK:
            if self.stopped.is_set(): return None
            return control_preview(self.endpoint,port)

    def _run(self):
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); self._socket=sock
        count=0; started=time.monotonic()
        try:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024*1024)
            sock.bind(('0.0.0.0',0)); sock.settimeout(.1)
            ip=urlsplit('//'+self.endpoint.ip).hostname
            stream=self._activate(sock.getsockname()[1])
            if stream is None or self.stopped.is_set(): return
            decoder=UdpReassembler(stream)
            # Firmware sends from :82. Open the matching local return flow.
            sock.sendto(b'VOJ1',(ip,self.source_port))
            renewed=last_frame=time.monotonic(); self.stage='đợi JPEG UDP đầu tiên'
            while not self.stopped.is_set():
                now=time.monotonic()
                if now-last_frame>(self.idle_timeout if count else self.first_timeout):
                    raise TimeoutError('Không nhận được JPEG UDP hợp lệ. Kiểm tra cùng Wi-Fi và cổng UDP 82.')
                if now-renewed>=self.renew_seconds:
                    stream=self._activate(sock.getsockname()[1])
                    if stream is None: return
                    decoder=UdpReassembler(stream);renewed=time.monotonic()
                    sock.sendto(b'VOJ1',(ip,self.source_port))
                try: packet,peer=sock.recvfrom(2048)
                except socket.timeout: continue
                if peer!=(ip,self.source_port): continue
                frame=decoder.feed(packet)
                if frame is None: continue
                last_frame=time.monotonic();count+=1
                try: self.frames.get_nowait()
                except queue.Empty: pass
                self.frames.put_nowait(frame)
                self.stage=f'UDP · {count} frame · CRC32 hợp lệ'
                if count==1: LOGGER.info('UDP first frame bytes=%d seconds=%.3f',len(frame),last_frame-started)
        except (OSError,ValueError) as error:
            if not self.stopped.is_set():
                self.errors.put_nowait(str(error));LOGGER.warning('UDP preview stopped: %s',error)
        finally:
            sock.close();self._socket=None
            LOGGER.info('UDP preview closed frames=%d seconds=%.3f',count,time.monotonic()-started)
