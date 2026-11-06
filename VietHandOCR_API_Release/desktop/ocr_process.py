"""Server-only OCR adapter. Never imports torch/ONNX or spawns a model process."""
import tempfile
import threading
from pathlib import Path
from .ocr_contract import OCRSettings, RecognitionError, RecognitionCancelled
from .remote_transport import VietOcrClient, RemoteCancelled, ServerError

class OCRProcessService:
    accepts_image_paths = True
    def __init__(self, *, auth=None, recognition_timeout=180, **_):
        self.auth = auth
        self.recognition_timeout = recognition_timeout
        self.device_info = None
        self.closed = threading.Event()
        self._remote = None
        self.parallelism = 1
        self._closing = threading.Event()

    def load(self, settings: OCRSettings, cancel=None):
        if self._closing.is_set() or (cancel and cancel.is_set()): raise RecognitionCancelled()
        if self.auth is None: raise RecognitionError('Đăng nhập Google trong OCR Server trước khi nhận diện.')
        try:
            self._remote = VietOcrClient(settings.server_url, self.auth.access_token,
                timeout=self.recognition_timeout, allow_insecure_lan=settings.allow_insecure_lan)
            status=self._remote.check()
            count=status.get('readyWorkers',1) if isinstance(status,dict) else 1
            self.parallelism=min(4,max(1,int(count)))
            self.device_info = {'name': 'OCR Server', 'id': settings.server_url}
        except (ServerError, RuntimeError, ValueError) as error:
            raise RecognitionError(str(error)) from None

    def recognize(self, image, settings, cancel, on_progress=None):
        if self._closing.is_set() or cancel.is_set(): raise RecognitionCancelled()
        if self._remote is None: self.load(settings, cancel)
        remote=self._remote
        if self.parallelism>1:
            remote=VietOcrClient(settings.server_url,self.auth.access_token,
                timeout=self.recognition_timeout,allow_insecure_lan=settings.allow_insecure_lan)
        temporary = not isinstance(image, (str, Path))
        if temporary:
            handle = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            path = Path(handle.name); handle.close()
        else:
            path = Path(image)
        try:
            if temporary: image.save(path, format='PNG')
            result = remote.recognize(path, layout=settings.layout, cancel=cancel)
            if on_progress: on_progress(1, 1)
            return result
        except RemoteCancelled: raise RecognitionCancelled() from None
        except (ServerError, TimeoutError, RuntimeError) as error: raise RecognitionError(str(error)) from None
        finally:
            if temporary: path.unlink(missing_ok=True)

    def close(self):
        self._closing.set(); self.closed.set()
