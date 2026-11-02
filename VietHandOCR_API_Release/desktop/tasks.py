"""Background tasks receive only data and queues, never Tk widgets or Application."""

import logging
import time
from pathlib import Path

from .domain import load_image
from .ocr_service import RecognitionCancelled

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
        for index, (item_id, image) in enumerate(jobs, 1):
            if cancel.is_set():
                break
            events.put(("started", item_id, index, len(jobs)))
            started = time.perf_counter()
            try:
                # Queue entries are paths; decode only the active image.
                if isinstance(image, (str, Path)):
                    image = load_image(image)
                result = service.recognize(image, settings, cancel,
                                           lambda line, total, job_id=item_id: events.put(("line_progress", job_id, line, total)))
            except RecognitionCancelled:
                events.put(("cancelled", item_id))
                break
            except Exception as exc:
                logger.exception("Recognition failed for image %s", item_id)
                failures += 1
                events.put(("result", item_id, "", str(exc)[:3000], time.perf_counter()-started))
            else:
                successes += 1
                events.put(("result", item_id, result, "", time.perf_counter()-started))
            finally:
                events.put(("model_device", getattr(service, "device_info", None)))
    except RecognitionCancelled:
        pass
    except Exception as exc:
        logger.exception("Model loading failed")
        events.put(("fatal", str(exc)[:3000]))
        failures += 1
    finally:
        events.put(("finished", successes, failures, cancel.is_set()))
