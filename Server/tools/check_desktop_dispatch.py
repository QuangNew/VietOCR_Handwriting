"""Measure the real desktop server adapter's bounded batch concurrency."""
import argparse,hashlib,json,queue,secrets,sys,threading,time
from admin_session import AdminSession,ROOT
sys.path.insert(0,str(ROOT.parent/'VietHandOCR_API_Release'))
from desktop.ocr_contract import OCRSettings
from desktop.ocr_process import OCRProcessService
from desktop.tasks import recognize_images
from desktop.remote_transport import VietOcrClient


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--origin',default='http://127.0.0.1:5080');args=parser.parse_args()
    admin=AdminSession(args.origin)
    entry=admin('/clients','POST',{'name':'validation-desktop-dispatch-'+secrets.token_hex(4),'ratePerMinute':60})
    class Auth:
        def access_token(self):return entry['key']
    class SerialService(OCRProcessService):
        def load(self,*args,**kwargs):
            super().load(*args,**kwargs);self.parallelism=1
    report={'clientId':entry['client']['id'],'auth':'temporary service key; does not measure Google Auth HTTP','warmupImages':2,'runs':[]}
    fixtures=[ROOT.parent/'VietHandOCR_API_Release'/name for name in ('test.jpg','test2.jpg')]*2
    expected={r['image']:r['textHash'] for r in json.loads((ROOT/'validation/latency-before.json').read_text())['rows']}
    try:
        warm=VietOcrClient(args.origin,entry['key'])
        for fixture in fixtures[:2]:warm.recognize(fixture,layout='line')
        for service_type in (SerialService,OCRProcessService):
            service=service_type(auth=Auth());events=queue.Queue();start=time.perf_counter()
            try:recognize_images([(str(i),p) for i,p in enumerate(fixtures)],OCRSettings(server_url=args.origin),threading.Event(),service,events)
            finally:service.close()
            elapsed=(time.perf_counter()-start)*1000;values=list(events.queue)
            assert values[-1]==('finished',4,0,False),values[-1]
            for event in values:
                if event[0]=='result':
                    assert not event[3]
                    assert hashlib.sha256(event[2].encode()).hexdigest()==expected[fixtures[int(event[1])].name]
            report['runs'].append({'parallelism':service.parallelism,'images':4,'wallMs':elapsed})
            print(json.dumps(report['runs'][-1]),flush=True)
        assert report['runs'][1]['parallelism']>=2,'Need at least two ready workers for this measurement'
        report['speedup']=report['runs'][0]['wallMs']/report['runs'][1]['wallMs']
    finally:
        admin('/clients/'+entry['client']['id'],'DELETE')
        (ROOT/'validation/desktop-dispatch.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
