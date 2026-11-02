"""Bounded VOJ1 preview reassembly; packet loss drops video, never a still."""
import math
import socket
import struct
import time
import zlib

HEADER=struct.Struct('<4sIIIIIHHHH')
PAYLOAD=1200-HEADER.size
MAX_BYTES=2*1024*1024

class Reassembler:
    def __init__(self,stream):
        self.stream=stream
        self.pending={}
        self.completed=0
        self.corrupt=0

    def feed(self,data):
        if len(data)<HEADER.size or len(data)>1200: return None
        magic,stream,sequence,total,offset,crc,width,height,count,reserved=HEADER.unpack_from(data)
        if (magic!=b'VOJ1' or stream!=self.stream or not sequence or sequence<=self.completed or
            not 4<=total<=MAX_BYTES or offset>=total or offset%PAYLOAD or reserved or
            count!=min(PAYLOAD,total-offset) or len(data)!=HEADER.size+count or
            not 160<=width<=2592 or width*3!=height*4): return None
        if sequence not in self.pending:
            if len(self.pending)>=2:
                oldest=min(self.pending)
                if sequence<oldest: return None
                del self.pending[oldest]
            self.pending[sequence]=(bytearray(total),bytearray(math.ceil(total/PAYLOAD)),0,crc,width,height)
        frame,seen,received,expected,w,h=self.pending[sequence]
        if len(frame)!=total or (crc,width,height)!=(expected,w,h): return None
        index=offset//PAYLOAD
        if seen[index]: return None
        frame[offset:offset+count]=data[HEADER.size:];seen[index]=1;received+=count
        self.pending[sequence]=(frame,seen,received,expected,w,h)
        if received!=total: return None
        del self.pending[sequence]
        if zlib.crc32(frame)!=crc or not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9'):
            self.corrupt+=1;return None
        self.completed=sequence
        self.pending={key:value for key,value in self.pending.items() if key>sequence}
        return bytes(frame)

def frames(sock,ip,stream,renew=None):
    decoder=Reassembler(stream)
    sock.settimeout(15)
    # Open the matching return flow in the local firewall/NAT. Firmware uses
    # source UDP port 82; no firewall rule or global network change is needed.
    time.sleep(.1)
    sock.sendto(b'VOJ1',(ip,82))
    renewed=time.monotonic()
    while True:
        if renew and time.monotonic()-renewed>=20:
            decoder=Reassembler(renew());renewed=time.monotonic()
            sock.sendto(b'VOJ1',(ip,82))
        data,peer=sock.recvfrom(2048)
        if peer!=(ip,82): continue
        frame=decoder.feed(data)
        if frame is not None: yield frame
