"""Webcam preview. Camera I/O lives on a worker; only Tk's thread draws frames."""

import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Callable

import cv2
from PIL import Image, ImageTk

from .domain import ImageBatch
from .theme import apply_titlebar
from .widgets import COLORS, label


def read_camera(index, stop, frames, errors):
    capture = None
    try:
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(index)
        if os.name == "nt" and not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(index)
        if not capture.isOpened():
            raise RuntimeError("Không mở được webcam. Kiểm tra quyền camera hoặc chọn camera khác trong Cài đặt model.")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        while not stop.is_set():
            ok, frame = capture.read()
            if stop.is_set():
                break
            if not ok:
                raise RuntimeError("Không đọc được hình từ camera. Hãy đóng app khác đang dùng webcam và thử lại.")
            rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            try:
                frames.put_nowait(rgb)
            except queue.Full:
                try:
                    frames.get_nowait()
                except queue.Empty:
                    pass
                frames.put_nowait(rgb)
    except Exception as exc:
        errors.put(str(exc))
    finally:
        if capture is not None:
            capture.release()


class CameraWindow(tk.Toplevel):
    def __init__(self, parent, batch: ImageBatch, on_capture: Callable[[Image.Image, str], None],
                 on_close: Callable[[], None], camera_index: int = 0):
        super().__init__(parent)
        self.title("VietOCR · Chụp ảnh")
        self.configure(bg=COLORS["bg"])
        self.geometry("820x680")
        self.minsize(640, 520)
        self.transient(parent)
        self.after_idle(lambda: apply_titlebar(self))
        self.batch, self.on_capture, self.on_close = batch, on_capture, on_close
        self.stop_event = threading.Event()
        self.frames: queue.Queue = queue.Queue(maxsize=2)
        self.errors: queue.Queue = queue.Queue()
        self.latest: Image.Image | None = None
        self._photo = None
        self._timer = None
        self._closed = False
        self.shots = 0

        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill="x", padx=24, pady=(22, 15))
        label(header, "Một khung hình, một trang giấy", size=18, bold=True).pack(anchor="w")
        label(header, "Đặt máy song song với giấy, giữ đủ sáng và chờ ảnh rõ nét.",
              color=COLORS["muted"]).pack(anchor="w", pady=(5, 0))
        self.preview = tk.Label(self, bg="#152820", fg="#DBE8DF", text="Đang mở camera…")
        self.preview.pack(fill="both", expand=True, padx=24)
        footer = tk.Frame(self, bg=COLORS["bg"])
        footer.pack(fill="x", padx=24, pady=18)
        self.status = label(footer, f"Còn {batch.remaining} chỗ trong lượt này", color=COLORS["muted"])
        self.status.pack(side="left")
        ttk.Button(footer, text="Hoàn tất", command=self.close).pack(side="right", padx=(10, 0))
        self.capture_button = ttk.Button(footer, text="●  Chụp ảnh  ·  Space", style="Primary.TButton",
                                         command=self.capture, state="disabled")
        self.capture_button.pack(side="right")
        self.bind("<space>", lambda _: self.capture())
        self.bind("<Escape>", lambda _: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grab_set()
        self._worker = threading.Thread(target=read_camera,
                                        args=(camera_index, self.stop_event, self.frames, self.errors),
                                        name="VietOCR-camera", daemon=True)
        self._worker.start()
        self._poll()


    def _poll(self) -> None:
        if self._closed:
            return
        try:
            error = self.errors.get_nowait()
        except queue.Empty:
            error = None
        if error:
            self.preview.configure(image="", text=error, wraplength=560)
            self.latest = None
            self.capture_button.configure(state="disabled")
            self.status.configure(text="Camera chưa sẵn sàng", fg=COLORS["error"])
            return
        try:
            while True:
                self.latest = self.frames.get_nowait()
        except queue.Empty:
            pass
        if self.latest is not None:
            thumb = self.latest.copy()
            thumb.thumbnail((max(1, self.preview.winfo_width()-8), max(1, self.preview.winfo_height()-8)),
                            Image.Resampling.LANCZOS)
            self._photo = ImageTk.PhotoImage(thumb, master=self)
            self.preview.configure(image=self._photo, text="")
            self.capture_button.configure(state="normal" if self.batch.remaining else "disabled")
        self._timer = self.after(50, self._poll)

    def capture(self) -> None:
        if self.latest is None or not self.batch.remaining or self._closed:
            return
        self.shots += 1
        name = f"Camera_{datetime.now():%H%M%S}_{self.shots}.jpg"
        self.on_capture(self.latest.copy(), name)
        self.status.configure(text=f"Đã chụp {self.shots} ảnh · Còn {self.batch.remaining} chỗ")
        if not self.batch.remaining:
            self.capture_button.configure(state="disabled")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop_event.set()
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None
        self.preview.configure(image="")
        self._photo = None  # Release ImageTk on the UI thread, before destroying Tcl.
        self.latest = None
        self.grab_release()
        self.destroy()
        self.on_close()
