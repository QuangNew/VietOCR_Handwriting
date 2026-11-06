"""Background tasks receive only data and queues, never Tk widgets or Application."""

import logging
import time
from pathlib import Path

from .domain import load_image
from .ocr_contract import RecognitionCancelled

logger = logging.getLogger("vietocr_desktop.tasks")


def warm_model(settings, service, events, stop):
    started = time.perf_counter()
    try:
        service.load(settings, cancel=stop)
    except RecognitionCancelled:
        return
    except Exception as error:
        logger.warning('Background model load failed: %s', error)
        events.put(('model_warmed', service, None, time.perf_counter()-started, str(error)))
    else:
        events.put(('model_warmed', service, getattr(service, 'device_info', None), time.perf_counter()-started, ''))


def import_images(paths, events, stop):
    errors = []
    for path in paths:
        if stop.is_set():
            return
        try:
            image = load_image(path)
            events.put(("import_item", path, image))
        except Exception as exc:
            logger.exception("Cannot read image %s", path)
            errors.append(f"{Path(path).name}: {exc}")
    events.put(("import_finished", errors))


def recognize_images(jobs, settings, cancel, service, events):
    successes = failures = 0
    try:
        service.load(settings, cancel=cancel)
        if cancel.is_set():
            raise RecognitionCancelled()
        events.put(("model_loaded",))
        events.put(("model_device", getattr(service, "device_info", None)))
        def recognize_one(entry):
            index,(item_id,image)=entry
            if cancel.is_set(): return 0,0
            events.put(("started",item_id,index,len(jobs)))
            started=time.perf_counter()
            try:
                if isinstance(image,(str,Path)) and not getattr(service,'accepts_image_paths',False):
                    image=load_image(image)
                result=service.recognize(image,settings,cancel,
                    lambda line,total:events.put(("line_progress",item_id,line,total)))
            except RecognitionCancelled:
                events.put(("cancelled",item_id));return 0,0
            except Exception as exc:
                logger.exception("Recognition failed for image %s",item_id)
                events.put(("result",item_id,"",str(exc)[:3000],time.perf_counter()-started));return 0,1
            else:
                events.put(("result",item_id,result,"",time.perf_counter()-started));return 1,0
            finally:events.put(("model_device",getattr(service,"device_info",None)))

        # A bounded number of requests gives the server enough queued work to
        # use several workers. Never submit the entire photo library at once.
        parallel=min(4,max(1,getattr(service,'parallelism',1)))
        if parallel==1:
            for entry in enumerate(jobs,1):
                if cancel.is_set():break
                good,bad=recognize_one(entry);successes+=good;failures+=bad
        else:
            from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
            remaining=iter(enumerate(jobs,1))
            with ThreadPoolExecutor(max_workers=parallel,thread_name_prefix='VietOCR-request') as pool:
                pending=set()
                def schedule():
                    if cancel.is_set():return
                    try:entry=next(remaining)
                    except StopIteration:return
                    pending.add(pool.submit(recognize_one,entry))
                for _ in range(parallel):schedule()
                while pending:
                    done,_=wait(pending,return_when=FIRST_COMPLETED)
                    for future in done:
                        pending.remove(future);good,bad=future.result();successes+=good;failures+=bad;schedule()
    except RecognitionCancelled:
        pass
    except Exception as exc:
        logger.exception("Model loading failed")
        events.put(("fatal", str(exc)[:3000]))
        failures += 1
    finally:
        events.put(("finished", successes, failures, cancel.is_set()))
