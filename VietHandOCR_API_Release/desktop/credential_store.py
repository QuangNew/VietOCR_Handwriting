"""Current-user Windows DPAPI, no plaintext API key in desktop preferences."""
import base64
import ctypes
import os
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(value, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("Dùng biến môi trường VIETOCR_API_KEY trên hệ điều hành này.")
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source = Blob(len(value), buffer)
    target = Blob()
    crypt = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not crypt(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [wintypes.HLOCAL]
        free.restype = wintypes.HLOCAL
        free(target.data)


def protect_api_key(value):
    return base64.b64encode(_crypt(value.encode("utf-8"))).decode("ascii") if value else ""


def read_api_key(preferences):
    if os.environ.get("VIETOCR_API_KEY"):
        return os.environ["VIETOCR_API_KEY"]
    try:
        stored = preferences.get("ocr_server_key_dpapi", "")
        return _crypt(base64.b64decode(stored), True).decode("utf-8") if stored else ""
    except (OSError, ValueError, UnicodeError, RuntimeError):
        return ""
