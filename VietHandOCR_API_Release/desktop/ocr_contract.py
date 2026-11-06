"""Client-side OCR contract. No model/device code or ML dependencies."""
from dataclasses import dataclass

class RecognitionError(RuntimeError): pass
class RecognitionCancelled(Exception): pass

@dataclass(frozen=True)
class OCRSettings:
    server_url: str = 'http://127.0.0.1:5080'
    layout: str = 'auto'
    allow_insecure_lan: bool = False
