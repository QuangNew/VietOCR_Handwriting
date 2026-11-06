import queue
import threading
import unittest
from unittest.mock import patch
from desktop.tasks import recognize_images
from desktop.ocr_contract import OCRSettings, RecognitionCancelled


class RemoteDispatchTests(unittest.TestCase):
    def run_batch(self, service, count=8):
        events=queue.Queue();cancel=threading.Event()
        thread=threading.Thread(target=recognize_images,
            args=([(str(i),'original.jpg') for i in range(count)],OCRSettings(),cancel,service,events))
        thread.start()
        self.addCleanup(thread.join,5)
        return thread,events,cancel

    def test_multiple_requests_run_concurrently_without_decoding_originals(self):
        class Service:
            accepts_image_paths=True
            parallelism=2
            lock=threading.Lock()
            barrier=threading.Barrier(2,timeout=4)
            active=peak=0
            def load(self,*_,**__):pass
            def recognize(self,path,*_):
                with self.lock:
                    self.active+=1;self.peak=max(self.peak,self.active)
                self.barrier.wait()
                with self.lock:self.active-=1
                return 'result'
        service=Service()
        with patch('desktop.tasks.load_image') as decode:
            thread,events,_=self.run_batch(service);thread.join(6)
            self.assertFalse(thread.is_alive());decode.assert_not_called()
        values=list(events.queue)
        self.assertEqual(service.peak,2)
        self.assertEqual(values[-1],('finished',8,0,False))
        self.assertEqual(len({v[1] for v in values if v[0]=='result'}),8)

    def test_cancel_does_not_submit_the_rest_of_a_large_library(self):
        entered=threading.Barrier(3,timeout=4);release=threading.Event()
        class Service:
            accepts_image_paths=True
            parallelism=2
            calls=0
            def load(self,*_,**__):pass
            def recognize(self,path,settings,cancel,*_):
                self.calls+=1;entered.wait();release.wait(4)
                if cancel.is_set():raise RecognitionCancelled()
                return 'unexpected'
        service=Service();thread,events,cancel=self.run_batch(service,count=1000)
        try:
            entered.wait();cancel.set()
        finally:release.set()
        thread.join(6)
        self.assertFalse(thread.is_alive());self.assertEqual(service.calls,2)
        self.assertEqual(list(events.queue)[-1],('finished',0,0,True))

    def test_failed_request_does_not_drop_other_workers_results(self):
        class Service:
            accepts_image_paths=True
            parallelism=2
            def load(self,*_,**__):pass
            def recognize(self,*_):raise RuntimeError('server unavailable')
        with self.assertLogs('vietocr_desktop.tasks',level='ERROR'):
            thread,events,_=self.run_batch(Service(),count=5);thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(list(events.queue)[-1],('finished',0,5,False))


if __name__=='__main__':unittest.main()
