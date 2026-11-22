"""Real model/device and scheduling checks. Run only on an idle local server.

--hardware temporarily drains existing workers to test CPU/DirectML one at a
time, then restores their devices. Never weakens memory guards or user quotas.
Records IDs/hashes/timings, never credentials, images or recognized text.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,secrets,sys,time
from admin_session import AdminSession,ROOT
sys.path.insert(0,str(ROOT/'clients/python'))
from vietocr_remote import VietOcrClient


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capture-before',action='store_true')
    parser.add_argument('--origin',default='http://127.0.0.1:5080')
    parser.add_argument('--hardware',action='store_true');args=parser.parse_args()
    admin=AdminSession(args.origin);snapshot=admin('/snapshot');original=admin('/workers')
    restore_devices=[w['device'] for w in original]
    if args.capture_before:
        record={'devices':[w['device'] for w in original],
            'queued':snapshot['queued'],'running':snapshot['running']}
        (ROOT/'validation/dispatch-before.json').write_text(json.dumps(record,indent=2))
        print(json.dumps(record));return
    assert snapshot['queued']==snapshot['running']==0,'Server must be idle for this check'
    previous=json.loads((ROOT/'validation/dispatch-before.json').read_text())['devices']
    # A stopped/unavailable old coordinator may already have released its pool.
    desired=previous or ['cuda:0','cuda:0']
    devices=admin('/devices');report={'devices':devices,'checks':[],'hardware':[]}
    admin('/workers','POST',{'device':'invalid-device'},expected=400)
    entry=admin('/clients','POST',{'name':'validation-dispatch-'+secrets.token_hex(4),'ratePerMinute':60})
    report['clientId']=entry['client']['id']
    source=ROOT.parents[1]/'shared/contracts/fixtures/images/test.jpg'
    expected=json.loads((ROOT/'validation/latency-before.json').read_text())['rows'][0]['textHash']

    def read_one():
        remote=VietOcrClient(admin.origin,entry['key']);job=remote.submit(source,layout='line')
        while job['state'] in ('queued','running'):job=remote.get(job['id'],wait=2)
        assert job['state']=='succeeded',job.get('error')
        assert hashlib.sha256(job['text'].encode()).hexdigest()==expected,'Model output differs from baseline'
        return {k:job[k] for k in ('id','workerId','inferenceMs','queueMs','totalMs')}

    def drain():
        assert admin('/snapshot')['queued']==0,'New work arrived; do not interrupt it'
        for worker in admin('/workers'):admin('/workers/'+worker['id'],'DELETE')
        deadline=time.monotonic()+140
        while admin('/workers'):
            assert time.monotonic()<deadline,'Worker drain timed out'
            time.sleep(.3)

    failed=False
    try:
        if args.hardware:
            candidates=['cpu']+[d['id'] for d in devices if d['kind']=='integrated' and d['available']][:1]
            for device in candidates:
                drain();worker=admin('/workers','POST',{'device':device})
                assert worker['device']==device
                result=read_one()
                report['hardware'].append({'device':device,'loadMs':worker['loadMs'],**result})
                print('PASS real model',device,round(result['inferenceMs']),flush=True)
            drain()
        active=admin('/workers')
        for index,device in enumerate(desired[len(active):]):
            # Old admin builds send an empty POST; it still selects auto.
            created=admin('/workers','POST',None if index==0 and device=='cuda:0' else {'device':device})
            assert created['device']==device
        active=admin('/workers');assert len(active)>=2,'Two workers are required for distribution measurement'
        report['checks'].append('invalid device rejected; CPU/DirectML are selected explicitly')
        sequential=[read_one() for _ in range(len(active)*2)]
        counts=Counter(row['workerId'] for row in sequential)
        assert len(counts)==len(active) and max(counts.values())-min(counts.values())<=1
        report['sequential']=sequential;report['sequentialByWorker']=dict(counts)
        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(active)) as pool:
            concurrent=list(pool.map(lambda _:read_one(),range(len(active)*2)))
        report['concurrent']=concurrent;report['concurrentWallMs']=(time.perf_counter()-started)*1000
        assert len({row['workerId'] for row in concurrent})==len(active)
        report['checks']+=['serial arrivals rotate across all idle workers','concurrent clients use all ready workers','CPU/GPU text matches original model baseline']
        print('PASS distribution',json.dumps(dict(Counter(row['workerId'] for row in concurrent))),flush=True)
    except Exception as error:
        failed=True;report['error']=str(error);raise
    finally:
        restoration_error=None
        try:
            admin('/clients/'+entry['client']['id'],'DELETE')
            current=admin('/workers')
            if [w['device'] for w in current]!=restore_devices:
                drain()
                for device in restore_devices:admin('/workers','POST',{'device':device})
        except Exception as error:
            restoration_error=error;report['restorationError']=str(error)
        finally:
            name='dispatch-failed.json' if failed or restoration_error else 'dispatch-after.json'
            (ROOT/'validation'/name).write_text(json.dumps(report,indent=2),encoding='utf-8')
        if restoration_error and not failed:raise RuntimeError('Unable to restore worker pool within current resource limits') from restoration_error


if __name__=='__main__':main()
