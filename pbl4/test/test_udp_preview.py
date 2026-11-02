import sys
from pathlib import Path
import unittest
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from udp_preview import HEADER,PAYLOAD,MAX_BYTES,Reassembler

def packets(frame,sequence=10):
    return [HEADER.pack(b'VOJ1',42,sequence,len(frame),at,zlib.crc32(frame),640,480,min(PAYLOAD,len(frame)-at),0)+frame[at:at+PAYLOAD]
            for at in range(0,len(frame),PAYLOAD)]
class ReassemblyTests(unittest.TestCase):
    def test_reordered_duplicate_and_stale_packets(self):
        frame=b'\xff\xd8'+b'a'*10007+b'\xff\xd9';parts=packets(frame)
        decode=Reassembler(42)
        self.assertIsNone(decode.feed(parts[-1]));self.assertIsNone(decode.feed(parts[-1]))
        for part in parts[1:-1]: self.assertIsNone(decode.feed(part))
        self.assertEqual(decode.feed(parts[0]),frame)
        for part in parts: self.assertIsNone(decode.feed(part))
    def test_memory_is_bounded_missing_parts_do_not_emit_corrupt_frames(self):
        decode=Reassembler(42);frame=b'\xff\xd8'+b'a'*4000+b'\xff\xd9'
        for seq in range(100):
            decode.feed(packets(frame,seq+1)[0]);self.assertLessEqual(len(decode.pending),2)
        self.assertEqual(decode.completed,0)
        for data in (b'',b'0'*1300,HEADER.pack(b'VOJ1',42,200,MAX_BYTES+1,0,0,640,480,1,0)+b'a'):
            self.assertIsNone(decode.feed(data))
        parts=packets(frame,200);bad=bytearray(parts[-1]);bad[-1]^=1;parts[-1]=bytes(bad)
        for data in parts: self.assertIsNone(decode.feed(data))
        self.assertEqual(decode.corrupt,1)
if __name__=='__main__': unittest.main()
