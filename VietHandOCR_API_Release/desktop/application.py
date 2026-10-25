"""Vietnamese desktop workflow: collect images, recognize, edit, and export."""

import asyncio
import logging
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .bluetooth_transport import RobotDevice, scan_robots, validate_address
from .bluetooth_process import ProcessBLEProtocol, scan_robots_isolated
from .bluetooth_coordinator import radio_access
from .bluetooth_radio import begin_bluetooth_access, enable_bluetooth, open_bluetooth_settings
from .camera import CameraWindow
from .domain import AssistantState, BatchFullError, ImageBatch, MAX_IMAGES
from .diagnostics import LOG_DIRECTORY
from .ocr_process import OCRProcessService
from .ocr_service import OCRSettings
from .preferences import read_preferences, update_preferences
from .robot_connection import RobotClient
from .tasks import import_images, recognize_images
from .theme import (PREFERENCES_PATH, apply_titlebar, atomic_repaint, load_theme,
                    recolor_canvas, recolor_widgets, save_theme, set_palette)
from .widgets import COLORS as C, RobotFace, ScrollableFrame, card, configure_styles, label

STATUS_LABELS = {
    "ready": "Chờ nhận diện", "processing": "Đang nhận diện", "done": "Hoàn tất",
    "error": "Cần thử lại", "cancelled": "Đã dừng",
}
logger = logging.getLogger("vietocr_desktop.ui")


def _scan_robot_devices(events, token, cancel, isolated=True, radio_lock=None):
    # Only plain data crosses the worker/UI boundary; no Tk objects in this thread.
    try:
        scanner = scan_robots_isolated if isolated else scan_robots
        logger.info("Starting Bluetooth scan (isolated=%s)", isolated)
        async def run():
            async with radio_access(radio_lock, cancel):
                return await scanner(cancel=cancel)
        devices = asyncio.run(run())
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.exception("Bluetooth scan failed")
        events.put(("robot_scan", token, [], str(exc)))
    else:
        events.put(("robot_scan", token, devices, ""))


async def _complete_radio_access(operation, promise):
    try:
        result = await operation
    except Exception as exc:
        if not promise.done():
            promise.set_exception(exc)
    else:
        if not promise.done():
            promise.set_result(result)


def _enable_robot_radio(events, token, cancel, radio_lock=None):
    async def run():
        async def request_access():
            loop = asyncio.get_running_loop()
            promise = loop.create_future()
            events.put(("robot_radio_permission", token, loop, promise))
            return await promise

        operation = asyncio.create_task(enable_bluetooth(request_access=request_access))
        try:
            while not operation.done():
                if cancel.is_set():
                    raise asyncio.CancelledError
                await asyncio.wait([operation], timeout=0.1)
            return await operation
        finally:
            if not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def gated():
        async with radio_access(radio_lock, cancel):
            return await run()

    try:
        result = asyncio.run(gated())
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Bluetooth radio operation failed")
        from .bluetooth_radio import RadioResult
        result = RadioResult(False, "Không bật được Bluetooth. Mở Cài đặt Windows để bật lại.", True)
    events.put(("robot_radio", token, result))


class Application:
    def __init__(self, root: tk.Tk, weights: str, device: str = "cpu", camera_index: int = 0,
                 preferences_path: Path | None = None, *, isolate_bluetooth: bool = True):
        self.root = root
        self.isolate_bluetooth = isolate_bluetooth
        self.preferences_path = preferences_path if preferences_path is not None else PREFERENCES_PATH
        self.theme = load_theme(self.preferences_path)
        set_palette(self.theme)
        self.settings = OCRSettings(weights, device)
        self.camera_index = camera_index
        self.batch = ImageBatch()
        self.service = OCRProcessService()
        self.events: queue.Queue = queue.Queue()
        self._shutdown = threading.Event()
        self._jobs = []
        self._error_dialog_pending = False
        self.robot_link: RobotClient | None = None
        self._robot_links: list[RobotClient] = []
        self._robot_progress: int | None = None
        self.robot_address = ""
        self.robot_name = ""
        self._robot_dialog = None
        self._robot_scan_token = 0
        self._robot_radio_token = 0
        self._robot_scan_cancel = threading.Event()
        self._robot_radio_cancel = threading.Event()
        self._robot_radio_lock = threading.Lock()
        self.assistant_state = AssistantState.AWAKE
        self.robot_connection_var = tk.StringVar(value="ESP32 chưa kết nối")
        self.cancel_event = threading.Event()
        self.selected_id: str | None = None
        self.running = False
        self.importing = False
        self.closing = False
        self.camera: CameraWindow | None = None
        self._camera_workers = []
        self._camera_release_timer = None
        self._preview_photo = None
        self._thumbs = []
        self._preview_timer = None
        self._poll_timer = None
        self._rendering_text = False
        self._result_id: str | None = None
        self._run_total = 0
        self._run_index = 0
        self.root.title("VietOCR Handwriting · Trợ lý đọc chữ Việt")
        self.root.configure(bg=C["bg"])
        screen_width, screen_height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width, height = min(1380, screen_width-32), min(900, screen_height-72)
        self.compact = screen_height < 850
        self.root.geometry(f"{width}x{height}+16+16")
        self.root.minsize(min(1180, width), min(760, height))
        configure_styles(root)
        self._build_ui()
        self.root.after_idle(lambda: apply_titlebar(self.root))
        self._sync_controls()
        self._render_queue()
        self._render_result()
        self._set_assistant(AssistantState.AWAKE, "Chào bạn, mình đã thức!", "Thêm ảnh để mình giúp bạn đọc chữ nhé.")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.report_callback_exception
        self.root.bind("<Control-o>", lambda _: self.import_files())
        self.root.bind("<Control-Return>", lambda _: self.start_recognition())
        self.root.bind("<Control-s>", lambda _: self.save_results())
        self.root.bind("<Escape>", lambda _: self.cancel_recognition())
        self._poll_events()
        preferences = read_preferences(self.preferences_path)
        saved_address = preferences.get("robot_ble_address")
        if isinstance(saved_address, str) and saved_address:
            try:
                saved_name = preferences.get("robot_ble_name")
                self.connect_robot(saved_address, name=saved_name if isinstance(saved_name, str) else "VietOCR-Assistant", save=False)
            except ValueError:
                self.robot_connection_var.set("Quét Bluetooth để chọn lại ESP32")

    def _build_ui(self):
        shell = tk.Frame(self.root, bg=C["bg"])
        shell.pack(fill="both", expand=True, padx=28, pady=20)
        header = tk.Frame(shell, bg=C["bg"])
        header.pack(fill="x")
        self.brand_mark = tk.Canvas(header, width=43, height=43, bg=C["bg"], highlightthickness=0)
        self._draw_brand()
        self.brand_mark.pack(side="left", padx=(0, 11))
        brand = tk.Frame(header, bg=C["bg"])
        brand.pack(side="left")
        label(brand, "VietOCR", size=20, bold=True).pack(anchor="w")
        label(brand, "HANDWRITING  /  PBL4", size=8, color=C["muted"]).pack(anchor="w")
        self.settings_button = ttk.Button(header, text="Cài đặt model", command=self.open_settings)
        self.settings_button.pack(side="right")
        self.robot_button = ttk.Button(header, text="Kết nối ESP32", command=self.open_robot_settings)
        self.robot_button.pack(side="right", padx=(10, 10))
        self.theme_button = ttk.Button(header, text=self._theme_button_text(), width=18, command=self.toggle_theme)
        self.theme_button.pack(side="right", padx=(0, 10))
        label(header, "●  Xử lý trên máy", size=9, color=C["green"]).pack(side="right", padx=20)

        hero = tk.Frame(shell, bg=C["bg"])
        hero.pack(fill="x", pady=(16 if self.compact else 24, 16 if self.compact else 20))
        intro = tk.Frame(hero, bg=C["bg"])
        intro.pack(side="left", fill="both", expand=True)
        label(intro, "TỪ NÉT BÚT ĐẾN VĂN BẢN", size=9, bold=True, color=C["green"]).pack(anchor="w")
        label(intro, "Để chữ viết tay\nđược lắng nghe.", size=23 if self.compact else 27, bold=True, justify="left").pack(anchor="w", pady=(6, 5))
        label(intro, "Chụp hoặc tải ảnh. Nhận diện tiếng Việt. Chỉnh sửa và lưu lại.",
              size=10, color=C["muted"]).pack(anchor="w")
        assistant_card = tk.Frame(hero, bg=C["pale"], padx=15, pady=10)
        assistant_card.pack(side="right", padx=(20, 0))
        self.robot = RobotFace(assistant_card, size=124 if self.compact else 142)
        self.robot.pack(side="left")
        speech = tk.Frame(assistant_card, bg=C["pale"], width=263)
        speech.pack(side="left", padx=(10, 10), fill="y")
        label(speech, "BẠN ĐỒNG HÀNH CỦA BẠN", size=8, color=C["green"], bold=True).pack(anchor="w", pady=(16, 8))
        self.assistant_title = label(speech, size=13, bold=True, anchor="w", justify="left", wraplength=265)
        self.assistant_title.pack(anchor="w")
        self.assistant_detail = label(speech, size=9, color=C["muted"], anchor="w", justify="left", wraplength=265)
        self.assistant_detail.pack(anchor="w", pady=(5, 6))
        self.assistant_badge = label(speech, size=8, color=C["green"], bold=True)
        self.assistant_badge.pack(anchor="w")
        self.robot_connection_label = label(speech, "ESP32 chưa kết nối",
                                            size=8, color=C["muted"], wraplength=265, justify="left")
        self.robot_connection_label.pack(anchor="w", pady=(6, 0))

        workspace_header = tk.Frame(shell, bg=C["bg"])
        workspace_header.pack(fill="x", pady=(0, 13))
        label(workspace_header, "Không gian làm việc", size=15, bold=True).pack(side="left")
        self.upload_button = ttk.Button(workspace_header, text="＋  Tải ảnh lên", style="Primary.TButton", command=self.import_files)
        self.upload_button.pack(side="right")
        self.camera_button = ttk.Button(workspace_header, text="◎  Chụp ảnh", command=self.open_camera)
        self.camera_button.pack(side="right", padx=(10, 10))
        label(workspace_header, "Tối đa 10 ảnh / lượt", size=9, color=C["muted"]).pack(side="right", padx=(0, 8))

        workspace = tk.Frame(shell, bg=C["bg"])
        workspace.pack(fill="both", expand=True)
        workspace.columnconfigure(0, minsize=214)
        workspace.columnconfigure(1, weight=5, minsize=310)
        workspace.columnconfigure(2, weight=5, minsize=350)
        workspace.rowconfigure(0, weight=1)

        queue_card = card(workspace, width=214)
        queue_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        queue_header = tk.Frame(queue_card, bg=C["white"])
        queue_header.pack(fill="x", padx=14, pady=(17, 14))
        label(queue_header, "01  Ảnh của bạn", size=10, bold=True).pack(side="left")
        self.queue_count = label(queue_header, "0 / 10", size=9, color=C["green"])
        self.queue_count.pack(side="right")
        self.queue_list = ScrollableFrame(queue_card)
        self.queue_list.pack(fill="both", expand=True, padx=7)
        self.clear_button = ttk.Button(queue_card, text="Dọn danh sách", style="Small.TButton", command=self.clear_batch)
        self.clear_button.pack(fill="x", padx=14, pady=14)

        preview_card = card(workspace)
        preview_card.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        preview_header = tk.Frame(preview_card, bg=C["white"])
        preview_header.pack(fill="x", padx=18, pady=(17, 12))
        label(preview_header, "02  Ảnh gốc", bold=True).pack(side="left")
        self.preview_index = label(preview_header, "", size=9, color=C["muted"])
        self.preview_index.pack(side="right")
        self.preview = tk.Canvas(preview_card, bg=C["preview"], highlightthickness=0, cursor="", width=1, height=1)
        self.preview.pack(fill="both", expand=True, padx=14)
        self.preview.bind("<Configure>", self._schedule_preview)
        self.preview.bind("<Button-1>", lambda _: self.import_files() if not self.batch.items else None)
        self.image_info = label(preview_card, "PNG, JPG, WEBP, BMP, TIFF", size=8, color=C["muted"])
        self.image_info.pack(padx=16, pady=(9, 0))
        preview_tools = tk.Frame(preview_card, bg=C["white"])
        preview_tools.pack(fill="x", padx=14, pady=12)
        self.rotate_button = ttk.Button(preview_tools, text="↶  Xoay trái", style="Small.TButton", command=self.rotate_selected)
        self.rotate_button.pack(side="left")
        self.remove_button = ttk.Button(preview_tools, text="Xóa ảnh", style="Small.TButton", command=self.remove_selected)
        self.remove_button.pack(side="right")

        result_card = card(workspace)
        result_card.grid(row=0, column=2, sticky="nsew")
        result_header = tk.Frame(result_card, bg=C["white"])
        result_header.pack(fill="x", padx=18, pady=(17, 7))
        label(result_header, "03  Văn bản", bold=True).pack(side="left")
        self.retry_button = ttk.Button(result_header, text="Nhận diện lại", style="Small.TButton", command=self.retry_selected)
        self.retry_button.pack(side="right")
        self.result_hint = label(result_card, "Kết quả có thể chỉnh sửa trực tiếp ở đây.", size=8,
                                 color=C["muted"], anchor="w")
        self.result_hint.pack(fill="x", padx=18, pady=(0, 12))
        text_frame = tk.Frame(result_card, bg=C["white"])
        text_frame.pack(fill="both", expand=True, padx=8)
        self.result_text = tk.Text(text_frame, bg=C["white"], fg=C["ink"], font=("Segoe UI", 11),
                                   wrap="word", relief="flat", borderwidth=0, padx=10, pady=10,
                                   insertbackground=C["green"], selectbackground=C["selection"], selectforeground=C["ink"], undo=True,
                                   width=26, height=4, highlightthickness=0, spacing1=3, spacing3=4)
        result_scroll = ttk.Scrollbar(text_frame, command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=result_scroll.set)
        self.result_text.pack(side="left", fill="both", expand=True)
        result_scroll.pack(side="right", fill="y")
        self.result_text.bind("<<Modified>>", self._on_text_modified)
        self.empty_result = tk.Frame(text_frame, bg=C["white"])
        self.empty_result.place(relx=0.5, rely=0.4, anchor="center", relwidth=0.88)
        self.empty_result_title = label(self.empty_result, "Chưa có văn bản", size=14, bold=True)
        self.empty_result_title.pack()
        self.empty_result_detail = label(self.empty_result, "Thêm ảnh rồi nhấn Nhận diện.\nMình sẽ đọc từng dòng cho bạn.",
                                          size=10, color=C["muted"], justify="center", wraplength=300)
        self.empty_result_detail.pack(pady=(9, 0))
        result_bottom = tk.Frame(result_card, bg=C["white"])
        result_bottom.pack(fill="x", padx=18, pady=(9, 14))
        self.text_stats = label(result_bottom, "0 ký tự", size=8, color=C["muted"])
        self.text_stats.pack(side="left")
        self.copy_button = ttk.Button(result_bottom, text="Sao chép", style="Small.TButton", command=self.copy_selected)
        self.copy_button.pack(side="right")

        actions = tk.Frame(shell, bg=C["bg"])
        actions.pack(fill="x", pady=(15, 11))
        label(actions, "Cách đọc:", size=9, color=C["muted"]).pack(side="left", padx=(0, 8))
        self.layout_var = tk.StringVar(value="Tự tách dòng")
        self.layout_combo = ttk.Combobox(actions, textvariable=self.layout_var, state="readonly", width=16,
                                          values=("Tự tách dòng", "Một dòng"))
        self.layout_combo.pack(side="left")
        self.recognize_button = ttk.Button(actions, text="Nhận diện ảnh", style="Primary.TButton", command=self.start_recognition)
        self.recognize_button.pack(side="left", padx=(12, 8))
        self.cancel_button = ttk.Button(actions, text="Dừng", command=self.cancel_recognition, state="disabled")
        self.cancel_button.pack(side="left")
        self.save_button = ttk.Button(actions, text="Lưu văn bản .txt", command=self.save_results)
        self.save_button.pack(side="right")
        self.copy_all_button = ttk.Button(actions, text="Sao chép tất cả", command=self.copy_all)
        self.copy_all_button.pack(side="right", padx=(10, 10))
        self.progress = ttk.Progressbar(shell, style="Green.Horizontal.TProgressbar", maximum=100)
        self.progress.pack(fill="x")
        status_bar = tk.Frame(shell, bg=C["bg"])
        status_bar.pack(fill="x", pady=(10, 0))
        self.operation_var = tk.StringVar(value="Sẵn sàng · Ctrl+O thêm ảnh · Ctrl+Enter nhận diện")
        label(status_bar, textvariable=self.operation_var, size=8, color=C["muted"]).pack(side="left")
        self.model_label = label(status_bar, f"VietHandOCR  ·  {self.settings.device.upper()}", size=8, color=C["muted"])
        self.model_label.pack(side="right")

    def _draw_brand(self):
        self.brand_mark.delete("all")
        self.brand_mark.create_oval(1, 1, 42, 42, fill=C["green"], outline="")
        self.brand_mark.create_text(22, 21, text="V", fill=C["on_accent"], font=("Segoe UI", 21, "bold"))

    def _theme_button_text(self) -> str:
        return "☀  Chế độ sáng" if self.theme == "dark" else "☾  Chế độ tối"

    def toggle_theme(self):
        if self.closing:
            return
        self._save_editor()
        with atomic_repaint(self.root):
            self.theme = "light" if self.theme == "dark" else "dark"
            previous = set_palette(self.theme)
            configure_styles(self.root)
            recolor_widgets(self.root, previous)
            self.theme_button.configure(text=self._theme_button_text())
            recolor_canvas(self.brand_mark, previous)
            recolor_canvas(self.preview, previous)
            self.robot._draw()
        logger.info("Theme changed to %s", self.theme)
        if self.robot_link is not None:
            self.robot_link.set_theme(self.theme)
        try:
            save_theme(self.preferences_path, self.theme)
        except OSError:
            self.operation_var.set("Đã đổi giao diện · Không ghi được lựa chọn cho lần mở sau")

    def _set_assistant(self, state: AssistantState, title: str, detail: str = ""):
        if state != self.assistant_state:
            self._robot_progress = None
        self.assistant_state = state
        badges = {AssistantState.AWAKE: "●  Sẵn sàng", AssistantState.RECEIVED: "●  Đã nhận ảnh",
                  AssistantState.PROCESSING: "●  Đang làm việc", AssistantState.DONE: "●  Hoàn tất",
                  AssistantState.ERROR: "●  Cần bạn giúp một chút", AssistantState.SLEEP: "●  Đang ngủ"}
        self.robot.set_state(state)
        self.assistant_title.configure(text=title)
        self.assistant_detail.configure(text=detail)
        self.assistant_badge.configure(text=badges[state], fg=C["error"] if state == AssistantState.ERROR else C["green"])
        self._publish_robot_state()

    def _publish_robot_state(self):
        if self.robot_link is not None:
            self.robot_link.set_state(self.assistant_state, len(self.batch.items))
            if self._robot_progress is not None:
                self.robot_link.set_progress(self._robot_progress)

    def _publish_robot_progress(self):
        self._robot_progress = max(0, min(100, int(float(self.progress["value"]))))
        if self.robot_link is not None:
            self.robot_link.set_progress(self._robot_progress)

    def connect_robot(self, address: str, *, name: str = "VietOCR-Assistant", save: bool = True):
        address = validate_address(address)
        if (self.robot_link is not None and not self.robot_link.closed.is_set()
                and not self.robot_link.stopping and self.robot_link.address.casefold() == address.casefold()):
            logger.info("Reusing Bluetooth connection attempt: address=%s phase=%s", address, self.robot_link.status)
            self.robot_link.retry_now()
            self._sync_robot_dialog_controls()
            return
        self._robot_scan_cancel.set()
        self._robot_radio_cancel.set()
        if self._robot_dialog:
            self._robot_dialog["token"] = self._robot_dialog["radio_token"] = None
        if self.robot_link is not None:
            self.robot_link.stop()
        self.robot_address = address
        self.robot_name = name or "VietOCR-Assistant"
        events = self.events  # Worker callbacks keep no reference to Tk widgets.
        from .bluetooth_transport import BLEProtocol
        link = RobotClient(address, lambda status, detail: events.put(("robot_connection", link, status, detail)),
                           name=self.robot_name,
                           protocol_factory=ProcessBLEProtocol if self.isolate_bluetooth else BLEProtocol,
                           radio_lock=self._robot_radio_lock)
        link.set_theme(self.theme)
        self.robot_link = link
        self._robot_links = [old for old in self._robot_links if not old.closed.is_set()]
        self._robot_links.append(link)
        self._publish_robot_state()
        self.robot_connection_var.set(f"Đang kết nối Bluetooth · {self.robot_name}")
        self.robot_connection_label.configure(text="ESP32 · Đang kết nối…", fg=C["muted"])
        link.start()
        self._sync_robot_dialog_controls()
        if save:
            self._save_robot_address(address, self.robot_name)

    def disconnect_robot(self):
        self._robot_scan_cancel.set()
        self._robot_radio_cancel.set()
        if self._robot_dialog:
            self._robot_dialog["token"] = self._robot_dialog["radio_token"] = None
        if self.robot_link is not None:
            self.robot_link.stop()
            self.robot_link = None
        self.robot_address = ""
        self.robot_name = ""
        self.robot_connection_var.set("ESP32 chưa kết nối")
        self.robot_connection_label.configure(text="ESP32 chưa kết nối", fg=C["muted"])
        self._save_robot_address("")
        self._sync_robot_dialog_controls()

    def _pause_robot_connection(self):
        if self.robot_link is not None:
            self.robot_link.stop()
            self.robot_link = None
        self.robot_connection_var.set("Đang tìm trợ lý Bluetooth…")
        self.robot_connection_label.configure(text="ESP32 · Chưa kết nối", fg=C["muted"])

    def _sync_robot_dialog_controls(self):
        dialog = self._robot_dialog
        if not dialog or not dialog["window"].winfo_exists() or "connect_button" not in dialog:
            return
        link = self.robot_link
        active = link is not None and not link.closed.is_set() and not link.stopping
        connected = active and link.connected.is_set()
        connecting = active and link.status in ("connecting", "waiting")
        scanning, radio = dialog["token"] is not None, dialog["radio_token"] is not None
        dialog["connect_button"].configure(state="disabled" if connected or connecting or scanning or radio or not dialog["devices"] else "normal")
        dialog["scan_button"].configure(state="disabled" if scanning or radio else "normal")
        dialog["enable_button"].configure(state="disabled" if radio else "normal")
        dialog["beep_button"].configure(state="normal" if connected else "disabled")

    def _save_robot_address(self, address: str, name: str = ""):
        try:
            update_preferences(self.preferences_path, robot_ble_address=address, robot_ble_name=name)
        except OSError:
            self.operation_var.set("Đã cập nhật kết nối · Không lưu được thiết bị cho lần mở sau")

    def open_robot_settings(self):
        logger.info("Opening Bluetooth dialog")
        if self.closing:
            return
        if self._robot_dialog and self._robot_dialog["window"].winfo_exists():
            self._robot_dialog["window"].lift()
            return
        window = tk.Toplevel(self.root)
        window.title("VietOCR · Bluetooth ESP32")
        window.configure(bg=C["white"])
        window.geometry("620x440")
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        apply_titlebar(window)
        body = tk.Frame(window, bg=C["white"], padx=24, pady=22)
        body.pack(fill="both", expand=True)
        label(body, "Trợ lý trên bàn của bạn", size=18, bold=True).pack(anchor="w")
        label(body, "Bật Bluetooth trên máy tính và cấp nguồn ESP32.\nChọn VietOCR-Assistant trong danh sách bên dưới.",
              size=10, color=C["muted"], justify="left").pack(anchor="w", pady=(8, 16))
        devices = [RobotDevice(self.robot_address, self.robot_name)] if self.robot_address else []
        row = tk.Frame(body, bg=C["white"])
        row.pack(fill="x")
        label(row, "Thiết bị Bluetooth BLE", bold=True).pack(side="left")
        scan_button = ttk.Button(row, text="Quét Bluetooth")
        scan_button.pack(side="right")
        enable_button = ttk.Button(row, text="Bật Bluetooth")
        enable_button.pack(side="right", padx=(0, 8))
        choice = ttk.Combobox(body, state="readonly", values=[device.description for device in devices])
        choice.pack(fill="x", pady=(10, 7), ipady=5)
        if devices:
            choice.current(0)
        scan_status = tk.StringVar(value="Quét để tìm thiết bị ở gần.")
        label(body, textvariable=scan_status, size=9, color=C["muted"],
              wraplength=540, justify="left").pack(anchor="w")
        label(body, textvariable=self.robot_connection_var, size=9, color=C["green"],
              wraplength=540, justify="left").pack(anchor="w", pady=(14, 15))
        self._robot_dialog = {"window": window, "devices": devices, "choice": choice,
                              "scan_button": scan_button, "scan_status": scan_status, "token": None,
                              "enable_button": enable_button, "radio_token": None}

        def scan():
            if self.closing or not window.winfo_exists():
                return
            self._robot_scan_cancel.set()
            self._pause_robot_connection()
            self._robot_scan_cancel = threading.Event()
            self._robot_scan_token += 1
            token = self._robot_scan_token
            self._robot_dialog["token"] = token
            scan_status.set("Đang quét Bluetooth…")
            scan_button.state(["disabled"])
            threading.Thread(target=_scan_robot_devices,
                             args=(self.events, token, self._robot_scan_cancel, self.isolate_bluetooth, self._robot_radio_lock),
                             name="VietOCR-BLE-scan", daemon=True).start()
            self._sync_robot_dialog_controls()

        def turn_on():
            self._robot_scan_cancel.set()
            self._pause_robot_connection()
            self._robot_radio_cancel.set()
            self._robot_radio_cancel = threading.Event()
            self._robot_dialog["token"] = None
            self._robot_radio_token += 1
            token = self._robot_radio_token
            self._robot_dialog["radio_token"] = token
            scan_button.state(["disabled"])
            enable_button.state(["disabled"])
            scan_status.set("Đang bật Bluetooth…")
            self._start_background(_enable_robot_radio, (self.events, token, self._robot_radio_cancel, self._robot_radio_lock), "VietOCR-Bluetooth-on")
            self._sync_robot_dialog_controls()

        def connect():
            if self._robot_dialog["connect_button"].instate(["disabled"]):
                return
            index = choice.current()
            available = self._robot_dialog["devices"]
            if index < 0 or index >= len(available):
                messagebox.showinfo("Chọn thiết bị", "Quét Bluetooth rồi chọn VietOCR-Assistant.", parent=window)
                return
            device = available[index]
            self.connect_robot(device.address, name=device.name)

        def beep():
            if self.robot_link is not None and self.robot_link.connected.is_set():
                self.robot_link.beep()
            else:
                messagebox.showinfo("Chưa kết nối", "Kết nối ESP32 thành công rồi thử còi nhé.", parent=window)

        def close_dialog():
            self._robot_scan_cancel.set()
            self._robot_radio_cancel.set()
            window.destroy()
            self._robot_dialog = None

        buttons = tk.Frame(body, bg=C["white"])
        buttons.pack(fill="x", side="bottom")
        connect_button = ttk.Button(buttons, text="Kết nối", style="Primary.TButton", command=connect)
        connect_button.pack(side="left")
        ttk.Button(buttons, text="Ngắt kết nối", command=self.disconnect_robot).pack(side="left", padx=8)
        beep_button = ttk.Button(buttons, text="Thử còi", command=beep)
        beep_button.pack(side="left")
        ttk.Button(buttons, text="Đóng", command=close_dialog).pack(side="right")
        scan_button.configure(command=scan)
        enable_button.configure(command=turn_on)
        self._robot_dialog["scan"] = scan
        self._robot_dialog["connect_button"] = connect_button
        self._robot_dialog["beep_button"] = beep_button
        window.protocol("WM_DELETE_WINDOW", close_dialog)
        window.bind("<Return>", lambda _: connect())
        window.bind("<Escape>", lambda _: close_dialog())
        if self.robot_link is None or self.robot_link.closed.is_set() or self.robot_link.stopping:
            scan()
        else:
            scan_status.set("App đang kết nối thiết bị đã lưu. Quét Bluetooth để chọn thiết bị khác.")
            self._sync_robot_dialog_controls()

    def _receive_robot_permission(self, token, loop, promise):
        dialog = self._robot_dialog
        if loop.is_closed() or promise.done():
            return
        if (self.closing or not dialog or token != dialog["radio_token"]
                or self._robot_radio_cancel.is_set() or not dialog["window"].winfo_exists()):
            try:
                loop.call_soon_threadsafe(promise.cancel)
            except RuntimeError:
                pass
            return
        try:
            operation = begin_bluetooth_access()  # Windows consent must start on Tk's thread.
        except Exception as exc:
            def reject(error=exc):
                if not promise.done():
                    promise.set_exception(error)
            try:
                loop.call_soon_threadsafe(reject)
            except RuntimeError:
                pass
            return
        completion = _complete_radio_access(operation, promise)
        try:
            asyncio.run_coroutine_threadsafe(completion, loop)
        except RuntimeError:
            completion.close()
            cancel = getattr(operation, "cancel", None)
            if cancel is not None:
                cancel()

    def _receive_robot_radio(self, token, result):
        dialog = self._robot_dialog
        if (self.closing or not dialog or token != dialog["radio_token"]
                or not dialog["window"].winfo_exists()):
            return
        dialog["radio_token"] = None
        dialog["enable_button"].state(["!disabled"])
        dialog["scan_button"].state(["!disabled"])
        dialog["scan_status"].set(result.message)
        if result.enabled:
            dialog["scan"]()
        elif result.open_settings:
            try:
                open_bluetooth_settings()
            except OSError:
                logger.exception("Cannot open Windows Bluetooth settings")
        self._sync_robot_dialog_controls()

    def _receive_robot_scan(self, token, devices, error):
        dialog = self._robot_dialog
        if (self.closing or not dialog or token != dialog["token"]
                or not dialog["window"].winfo_exists()):
            return
        dialog["token"] = None
        dialog["scan_button"].state(["!disabled"])
        dialog["devices"] = devices
        choice = dialog["choice"]
        choice.set("")
        choice.configure(values=[device.description for device in devices])
        if devices:
            selected = next((index for index, device in enumerate(devices)
                             if device.address.casefold() == self.robot_address.casefold()), 0)
            choice.current(selected)
        if error:
            text = f"Không quét được. Bật Bluetooth và cho phép ứng dụng truy cập: {error}"
        elif devices:
            text = f"Tìm thấy {len(devices)} thiết bị. Chọn trợ lý rồi bấm Kết nối."
        else:
            text = "Chưa tìm thấy. Đưa ESP32 lại gần và ngắt điện thoại/app khác đang kết nối."
        dialog["scan_status"].set(text)
        self._sync_robot_dialog_controls()

    def _sync_controls(self):
        locked = self.running or self.importing or self.camera is not None or self.closing
        selected = self.batch.get(self.selected_id)
        pending = sum(item.status != "done" for item in self.batch.items)
        has_text = any(item.text.strip() for item in self.batch.items)
        self.upload_button.configure(state="normal" if not locked and self.batch.remaining else "disabled")
        camera_stopping = self.camera is None and any(worker.is_alive() for worker in self._camera_workers)
        self.camera_button.configure(state="normal" if not locked and self.batch.remaining and not camera_stopping else "disabled")
        self.settings_button.configure(state="disabled" if locked else "normal")
        for button in (self.rotate_button, self.remove_button):
            button.configure(state="normal" if selected and not locked else "disabled")
        self.clear_button.configure(state="normal" if self.batch.items and not locked else "disabled")
        self.retry_button.configure(state="normal" if selected and not locked else "disabled")
        self.recognize_button.configure(state="normal" if pending and not locked else "disabled",
                                        text=f"Nhận diện {pending} ảnh" if pending else "Nhận diện ảnh")
        self.cancel_button.configure(state="normal" if self.running and not self.cancel_event.is_set() else "disabled")
        self.layout_combo.configure(state="disabled" if locked else "readonly")
        self.copy_button.configure(state="normal" if selected and selected.text.strip() else "disabled")
        self.copy_all_button.configure(state="normal" if has_text else "disabled")
        self.save_button.configure(state="normal" if has_text else "disabled")

    def _render_queue(self):
        position = self.queue_list.canvas.yview()[0]
        for child in self.queue_list.inner.winfo_children():
            child.destroy()
        self._thumbs.clear()
        self.queue_count.configure(text=f"{len(self.batch.items)} / {MAX_IMAGES}")
        if not self.batch.items:
            label(self.queue_list.inner, "Danh sách đang trống", size=9, color=C["muted"]).pack(pady=(35, 8))
            label(self.queue_list.inner, "Thêm ảnh từ máy\nhoặc chụp bằng webcam.", size=9,
                  color=C["muted"], justify="center").pack()
        for index, item in enumerate(self.batch.items, 1):
            bg = C["pale"] if item.id == self.selected_id else C["white"]
            row = tk.Frame(self.queue_list.inner, bg=bg, padx=8, pady=10, cursor="hand2")
            row.pack(fill="x", pady=2)
            thumb = item.image.copy()
            thumb.thumbnail((54, 53), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(thumb, master=self.root)
            self._thumbs.append(photo)
            picture = tk.Label(row, image=photo, bg=bg, width=56, height=56)
            picture.pack(side="left", padx=(0, 8))
            info = tk.Frame(row, bg=bg)
            info.pack(side="left", fill="x", expand=True)
            name = item.name if len(item.name) <= 15 else item.name[:12] + "…"
            title = label(info, f"{index:02d}  {name}", size=8, bold=True, anchor="w")
            title.pack(anchor="w")
            color = C["error"] if item.status == "error" else C["green"] if item.status == "done" else C["muted"]
            status = label(info, STATUS_LABELS[item.status], size=8, color=color, anchor="w")
            status.pack(anchor="w", pady=(4, 0))
            for widget in (row, picture, info, title, status):
                widget.bind("<Button-1>", lambda _, item_id=item.id: self.select_item(item_id))
                self.queue_list.bind_scroll(widget)
        self.queue_list.canvas.update_idletasks()
        self.queue_list.canvas.yview_moveto(position)

    def select_item(self, item_id: str):
        self._save_editor()
        self.selected_id = item_id
        self._render_queue()
        self._draw_preview()
        self._render_result()
        self._sync_controls()

    def _schedule_preview(self, _=None):
        if self._preview_timer:
            self.root.after_cancel(self._preview_timer)
        self._preview_timer = self.root.after(80, self._draw_preview)

    def _draw_preview(self):
        if self._preview_timer:
            self.root.after_cancel(self._preview_timer)
        self._preview_timer = None
        width, height = max(1, self.preview.winfo_width()), max(1, self.preview.winfo_height())
        item = self.batch.get(self.selected_id)
        # Configure notifications also occur during ttk palette updates. A pending
        # resize must not rebuild the same PhotoImage after the atomic repaint.
        key = (item.id if item else None, id(item.image) if item else None, width, height)
        if getattr(self, "_preview_key", None) == key and self.preview.find_all():
            return
        self._preview_key = key
        self.preview.delete("all")
        if item is None:
            scale = min(1.0, max(0.5, (height-65)/125))
            x, y = width / 2, max(50*scale+8, height/2-30*scale)
            self.preview.create_rectangle(x-32*scale, y-50*scale, x+32*scale, y+28*scale,
                                          fill=C["white"], outline=C["paper_border"], width=2)
            for offset, length in ((-27, 40), (-13, 32), (1, 38)):
                self.preview.create_line(x-20*scale, y+offset*scale, x+(-20+length)*scale, y+offset*scale,
                                         fill=C["paper_line"], width=3)
            self.preview.create_oval(x+12*scale, y+5*scale, x+45*scale, y+38*scale, fill=C["green"], outline="")
            self.preview.create_text(x+28*scale, y+21*scale, text="+", fill=C["on_accent"], font=("Segoe UI", max(12, int(20*scale))))
            self.preview.create_text(x, y+70*scale, text="Bắt đầu với một tấm ảnh", fill=C["ink"],
                                     font=("Segoe UI", 10 if scale < 1 else 12, "bold"))
            self.preview.create_text(x, y+101*scale, text="Nhấn Tải ảnh lên hoặc Chụp ảnh", fill=C["muted"],
                                     font=("Segoe UI", 8 if scale < 1 else 9))
            self.preview_index.configure(text="")
            self.image_info.configure(text="PNG, JPG, WEBP, BMP, TIFF")
            self.preview.configure(cursor="hand2")
            return
        image = item.image.copy()
        image.thumbnail((max(1, width-24), max(1, height-24)), Image.Resampling.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(image, master=self.root)
        self.preview.create_rectangle((width-image.width)/2-1, (height-image.height)/2-1,
                                      (width+image.width)/2+1, (height+image.height)/2+1,
                                      fill=C["white"], outline=C["border"])
        self.preview.create_image(width/2, height/2, image=self._preview_photo)
        self.preview_index.configure(text=f"{self.batch.items.index(item)+1} / {len(self.batch.items)}")
        self.image_info.configure(text=f"{item.image.width} × {item.image.height} px  ·  {item.name[:36]}")
        self.preview.configure(cursor="")

    def _render_result(self):
        item = self.batch.get(self.selected_id)
        self._rendering_text = True
        self._result_id = item.id if item else None
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        if item and item.text:
            self.result_text.insert("1.0", item.text)
        self.result_text.edit_reset()
        self.result_text.edit_modified(False)
        self.result_text.configure(state="normal" if item and item.status == "done" else "disabled")
        self._rendering_text = False
        if item and item.status == "done":
            self.empty_result.place_forget()
            self.result_hint.configure(text=f"{item.seconds:.1f} giây · Bạn có thể sửa văn bản trước khi lưu.", fg=C["muted"])
        else:
            title, detail = "Chưa có văn bản", "Thêm ảnh rồi nhấn Nhận diện.\nMình sẽ đọc từng dòng cho bạn."
            if item:
                title, detail = "Ảnh đã sẵn sàng", "Nhấn Nhận diện để chuyển\nchữ trong ảnh thành văn bản."
                if item.status == "processing":
                    title, detail = "Mình đang đọc chữ…", "Bạn có thể xem các ảnh khác\ntrong lúc chờ kết quả."
                elif item.status == "error":
                    title, detail = "Chưa đọc được ảnh này", item.error[:520]
                elif item.status == "cancelled":
                    title, detail = "Đã dừng nhận diện", "Nhấn Nhận diện để thử lại ảnh này."
            self.empty_result_title.configure(text=title, fg=C["error"] if item and item.status == "error" else C["ink"])
            self.empty_result_detail.configure(text=detail)
            self.empty_result.place(relx=0.5, rely=0.4, anchor="center", relwidth=0.88)
            self.result_hint.configure(text="Kết quả có thể chỉnh sửa trực tiếp ở đây.", fg=C["muted"])
        self._update_text_stats()

    def _save_editor(self):
        item = self.batch.get(self._result_id)
        if item and item.status == "done":
            item.text = self.result_text.get("1.0", "end-1c")

    def _on_text_modified(self, _):
        if self.result_text.edit_modified():
            if not self._rendering_text:
                self._save_editor()
                self._update_text_stats()
                self._sync_controls()
            self.result_text.edit_modified(False)

    def _update_text_stats(self):
        item = self.batch.get(self.selected_id)
        text = item.text if item else ""
        self.text_stats.configure(text=f"{len(text)} ký tự  ·  {len(text.split())} từ")

    @property
    def locked(self) -> bool:
        return self.running or self.importing or self.camera is not None or self.closing

    def import_files(self, paths: list[str] | None = None):
        if self.locked:
            return
        if paths is None:
            paths = list(filedialog.askopenfilenames(
                parent=self.root, title=f"Chọn ảnh · Còn {self.batch.remaining} / 10 chỗ",
                filetypes=[("Ảnh", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"), ("Tất cả file", "*.*")],
            ))
        if not paths:
            return
        try:
            self.batch.check_capacity(len(paths))
        except BatchFullError as exc:
            messagebox.showwarning("Giới hạn 10 ảnh", str(exc), parent=self.root)
            return
        self.importing = True
        self._sync_controls()
        self.operation_var.set(f"Đang đọc {len(paths)} ảnh…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._start_background(import_images, (paths, self.events, self._shutdown), "VietOCR-import")


    def open_camera(self):
        if self.locked or not self.batch.remaining:
            return
        if any(worker.is_alive() for worker in self._camera_workers):
            self.operation_var.set("Camera đang giải phóng thiết bị · Vui lòng chờ một chút")
            return
        self.camera = CameraWindow(self.root, self.batch, self._on_capture, self._on_camera_close, self.camera_index)
        self._camera_workers = [self.camera._worker]
        self._sync_controls()

    def _on_capture(self, image: Image.Image, name: str):
        try:
            item = self.batch.add(image, name)
        except (BatchFullError, ValueError) as exc:
            messagebox.showwarning("Không thể thêm ảnh", str(exc), parent=self.camera or self.root)
            return
        self.select_item(item.id)
        self._set_assistant(AssistantState.RECEIVED, "Đã nhận ảnh của bạn!", f"Có {len(self.batch.items)} ảnh đang chờ trong danh sách.")
        self.operation_var.set(f"Đã chụp {name} · {len(self.batch.items)}/10 ảnh")

    def _on_camera_close(self):
        self.camera = None
        self._sync_controls()
        if not self.closing:
            self._wait_camera_release()

    def _wait_camera_release(self):
        self._camera_release_timer = None
        if self.closing:
            return
        self._camera_workers = [worker for worker in self._camera_workers if worker.is_alive()]
        self._sync_controls()
        if self._camera_workers:
            self._camera_release_timer = self.root.after(50, self._wait_camera_release)

    def rotate_selected(self):
        item = self.batch.get(self.selected_id)
        if not item or self.locked:
            return
        item.rotate()
        self.select_item(item.id)
        self.operation_var.set("Đã xoay ảnh 90° sang trái · Nhận diện lại để cập nhật văn bản")

    def remove_selected(self):
        if self.locked or self.selected_id is None:
            return
        index = next((i for i, item in enumerate(self.batch.items) if item.id == self.selected_id), 0)
        self.batch.remove(self.selected_id)
        self.selected_id = self.batch.items[min(index, len(self.batch.items)-1)].id if self.batch.items else None
        self._result_id = None
        self._refresh()
        if not self.batch.items:
            self._set_assistant(AssistantState.AWAKE, "Mình vẫn ở đây!", "Thêm ảnh để bắt đầu một lượt mới nhé.")
        else:
            self._publish_robot_state()
        self.operation_var.set(f"Danh sách hiện có {len(self.batch.items)}/10 ảnh")

    def clear_batch(self):
        if self.locked:
            return
        self.batch.items.clear()
        self.selected_id = self._result_id = None
        self._refresh()
        self.progress["value"] = 0
        self._set_assistant(AssistantState.AWAKE, "Bắt đầu một lượt mới nhé!", "Mình đã sẵn sàng nhận thêm ảnh.")
        self.operation_var.set("Đã dọn danh sách · Bạn có thể thêm tối đa 10 ảnh mới")

    def _refresh(self):
        self._render_queue()
        self._draw_preview()
        self._render_result()
        self._sync_controls()

    def retry_selected(self):
        item = self.batch.get(self.selected_id)
        if item and not self.locked:
            self.start_recognition([item])

    def start_recognition(self, items=None):
        if self.locked:
            return
        self._save_editor()
        jobs = list(items) if items is not None else [item for item in self.batch.items if item.status != "done"]
        if not jobs:
            return
        self.running = True
        self.cancel_event = threading.Event()
        self._run_total = len(jobs)
        self._run_index = 0
        settings = OCRSettings(self.settings.weights, self.settings.device,
                               "auto" if self.layout_var.get() == "Tự tách dòng" else "line")
        self._sync_controls()
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.operation_var.set("Đang nạp model · Lần đầu có thể cần vài giây…")
        self._set_assistant(AssistantState.PROCESSING, "Để mình đọc giúp bạn…", "Đang chuẩn bị mô hình nhận diện trên máy.")
        # Queue membership and images stay fixed until the worker finishes.
        snapshots = [(item.id, item.image) for item in jobs]
        self._start_background(recognize_images, (snapshots, settings, self.cancel_event, self.service, self.events), "VietOCR-OCR")


    def cancel_recognition(self):
        if not self.running or self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self._sync_controls()
        self.operation_var.set("Đang dừng nhận diện và giải phóng model…")
        self._set_assistant(AssistantState.PROCESSING, "Mình đang dừng lại…", "Kết quả đã hoàn tất được giữ lại.")

    def _start_background(self, target, args, name):
        self._jobs = [job for job in self._jobs if job.is_alive()]
        job = threading.Thread(target=target, args=args, name=name, daemon=True)
        self._jobs.append(job)
        job.start()

    def report_callback_exception(self, exception_type, exception, traceback):
        logger.error("UI callback failed", exc_info=(exception_type, exception, traceback))
        if self.closing:
            return
        self.operation_var.set("Có lỗi giao diện · Chi tiết đã lưu trong .logs/vietocr.log")
        if self._error_dialog_pending:
            return
        self._error_dialog_pending = True

        def show_error():
            try:
                if not self.closing:
                    messagebox.showerror("Lỗi ứng dụng", f"{str(exception)[:1200]}\n\nLog: {LOG_DIRECTORY / 'vietocr.log'}",
                                         parent=self.root)
            finally:
                self._error_dialog_pending = False

        self.root.after_idle(show_error)

    def _poll_events(self):
        if self.closing:
            return
        self._poll_timer = None
        try:
            # Bound work per tick, keeping camera and input events responsive.
            for _ in range(25):
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_event(event)
                except Exception as exc:
                    self.report_callback_exception(type(exc), exc, exc.__traceback__)
        finally:
            if not self.closing:
                self._poll_timer = self.root.after(65, self._poll_events)

    def _handle_event(self, event):
        kind, *data = event
        if kind == "robot_connection":
            link, status, detail = data
            if link is self.robot_link:
                self.robot_connection_var.set(detail)
                summary = {"connected": "ESP32 · Đã kết nối BLE", "connecting": "ESP32 · Đang kết nối…",
                           "waiting": "ESP32 · Đang chờ Bluetooth…"}.get(status, "ESP32 · Chưa kết nối")
                self.robot_connection_label.configure(text=summary, fg=C["green"] if status == "connected" else C["muted"])
                self._sync_robot_dialog_controls()
        elif kind == "robot_scan":
            self._receive_robot_scan(*data)
        elif kind == "robot_radio":
            self._receive_robot_radio(*data)
        elif kind == "robot_radio_permission":
            self._receive_robot_permission(*data)
        elif kind == "import_item":
            path, image = data
            item = self.batch.add(image, Path(path).name, str(Path(path).resolve()))
            self.select_item(item.id)
        elif kind == "import_finished":
            self.importing = False
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self._sync_controls()
            errors = data[0]
            self.operation_var.set(f"Đã nhận {len(self.batch.items)}/10 ảnh · Sẵn sàng nhận diện")
            if self.batch.items:
                self._set_assistant(AssistantState.RECEIVED, "Đã nhận ảnh của bạn!", f"Mình sẵn sàng đọc {len(self.batch.items)} ảnh trong danh sách.")
            if errors:
                self._set_assistant(AssistantState.ERROR, "Có ảnh mình chưa mở được", "Bạn có thể thêm ảnh khác rồi thử lại.")
                messagebox.showwarning("Một số ảnh không đọc được", "\n\n".join(errors[:5]), parent=self.root)
        elif kind == "model_loaded":
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
        elif kind == "started":
            item_id, self._run_index, total = data
            item = self.batch.get(item_id)
            if item:
                item.status, item.text, item.error = "processing", "", ""
                self._render_queue()
                if self.selected_id == item_id:
                    self._render_result()
                self._sync_controls()
                self.operation_var.set(f"Đang nhận diện ảnh {self._run_index}/{total} · {item.name}")
                self._set_assistant(AssistantState.PROCESSING, f"Đang đọc ảnh {self._run_index}/{total}", "Từng dòng chữ đang trở thành văn bản.")
        elif kind == "line_progress":
            item_id, line, total = data
            self.progress["value"] = (self._run_index-1 + (line-1)/total) / self._run_total * 100
            self._publish_robot_progress()
            if not self.cancel_event.is_set():
                self.operation_var.set(f"Ảnh {self._run_index}/{self._run_total} · Đang đọc dòng {line}/{total}")
        elif kind == "result":
            item_id, text, error, seconds = data
            item = self.batch.get(item_id)
            if item:
                item.text, item.error, item.seconds = text, error, seconds
                item.status = "error" if error else "done"
                self._render_queue()
                if self.selected_id == item_id:
                    self._render_result()
                self.progress["value"] = self._run_index / self._run_total * 100
                self._publish_robot_progress()
                self._sync_controls()
        elif kind == "cancelled":
            item = self.batch.get(data[0])
            if item:
                item.status = "cancelled"
                self._render_queue()
                if item.id == self.selected_id:
                    self._render_result()
        elif kind == "fatal":
            self.operation_var.set("Không thể nạp model · Kiểm tra Cài đặt model")
            messagebox.showerror("Không thể khởi động AI", data[0], parent=self.root)
        elif kind == "finished":
            successes, failures, cancelled = data
            self.running = False
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self._sync_controls()
            if cancelled:
                self.operation_var.set(f"Đã dừng · {successes} ảnh hoàn tất, {failures} ảnh lỗi · Kết quả đã có được giữ lại")
                self._set_assistant(AssistantState.AWAKE, "Đã dừng theo ý bạn", "Bạn có thể tiếp tục với các ảnh còn lại.")
            elif failures:
                self.operation_var.set(f"{successes} ảnh hoàn tất · {failures} lỗi · Kiểm tra ảnh hoặc Cài đặt model rồi thử lại")
                self._set_assistant(AssistantState.ERROR, "Có ảnh cần thử lại", "Xem thông báo ở phần văn bản hoặc kiểm tra model.")
            else:
                self.progress["value"] = 100
                self.operation_var.set(f"Hoàn tất {successes} ảnh · Chỉnh sửa văn bản, sao chép hoặc lưu .txt")
                self._set_assistant(AssistantState.DONE, "Xong rồi, bạn ơi!", "Văn bản đã sẵn sàng. Mình chờ lượt tiếp theo nhé.")

    def copy_selected(self):
        self._save_editor()
        item = self.batch.get(self.selected_id)
        if item and item.text.strip():
            self._copy(item.text, "Đã sao chép văn bản của ảnh đang chọn")

    def copy_all(self):
        self._save_editor()
        text = self.batch.combined_text()
        if text:
            self._copy(text, "Đã sao chép toàn bộ văn bản theo thứ tự ảnh")

    def _copy(self, text: str, message: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.operation_var.set(message)

    def save_results(self):
        self._save_editor()
        text = self.batch.combined_text()
        if not text:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Lưu văn bản tất cả ảnh", defaultextension=".txt",
                                          initialfile=f"VietOCR_{datetime.now():%Y%m%d_%H%M}.txt",
                                          filetypes=[("Văn bản UTF-8", "*.txt")])
        if path:
            try:
                Path(path).write_text(text + "\n", encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Không lưu được file", str(exc), parent=self.root)
            else:
                self.operation_var.set(f"Đã lưu {Path(path).name} · Văn bản UTF-8")

    def open_settings(self):
        if self.locked:
            return
        window = tk.Toplevel(self.root)
        window.title("VietOCR · Cài đặt model")
        window.configure(bg=C["white"])
        window.geometry("690x430")
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        window.after_idle(lambda: apply_titlebar(window))
        body = tk.Frame(window, bg=C["white"], padx=25, pady=22)
        body.pack(fill="both", expand=True)
        label(body, "Mô hình nhận diện cục bộ", size=18, bold=True).pack(anchor="w")
        label(body, "Thiết lập cho phiên làm việc này. Model chỉ được nạp khi nhận diện.",
              size=9, color=C["muted"]).pack(anchor="w", pady=(5, 20))
        label(body, "File trọng số (.pth)", bold=True).pack(anchor="w")
        path_row = tk.Frame(body, bg=C["white"])
        path_row.pack(fill="x", pady=(6, 14))
        weights_var = tk.StringVar(value=self.settings.weights)
        ttk.Entry(path_row, textvariable=weights_var).pack(side="left", fill="x", expand=True, ipady=5)

        def browse():
            path = filedialog.askopenfilename(parent=window, title="Chọn model VietHandOCR", filetypes=[("PyTorch weights", "*.pth")])
            if path:
                weights_var.set(path)

        ttk.Button(path_row, text="Chọn file", command=browse).pack(side="left", padx=(8, 0))
        row = tk.Frame(body, bg=C["white"])
        row.pack(fill="x", pady=(0, 15))
        device_column = tk.Frame(row, bg=C["white"])
        device_column.pack(side="left", fill="x", expand=True)
        label(device_column, "Thiết bị xử lý", bold=True).pack(anchor="w", pady=(0, 6))
        device_var = tk.StringVar(value="CPU" if self.settings.device == "cpu" else "GPU (CUDA)")
        ttk.Combobox(device_column, textvariable=device_var, values=("CPU", "GPU (CUDA)"), state="readonly", width=23).pack(anchor="w")
        camera_column = tk.Frame(row, bg=C["white"])
        camera_column.pack(side="left", fill="x", expand=True)
        label(camera_column, "Camera (0 là mặc định)", bold=True).pack(anchor="w", pady=(0, 6))
        camera_var = tk.StringVar(value=str(self.camera_index))
        ttk.Spinbox(camera_column, from_=0, to=9, textvariable=camera_var, width=13).pack(anchor="w", ipady=6)
        label(body, "Tự tách dòng: dành cho giấy một cột, chữ ngay ngắn.\nMột dòng: dành cho ảnh đã cắt sát một dòng chữ. GPU cần PyTorch hỗ trợ CUDA.",
              size=9, color=C["muted"], justify="left").pack(anchor="w", pady=(0, 20))

        def save():
            path = Path(weights_var.get()).expanduser()
            if not path.is_file():
                messagebox.showwarning("Chưa tìm thấy model", "Hãy chọn một file trọng số .pth có sẵn.", parent=window)
                return
            try:
                camera_index = int(camera_var.get())
                if not 0 <= camera_index <= 9:
                    raise ValueError()
            except ValueError:
                messagebox.showwarning("Camera không hợp lệ", "Nhập số camera từ 0 đến 9.", parent=window)
                return
            self.settings = OCRSettings(str(path.resolve()), "cpu" if device_var.get() == "CPU" else "cuda:0")
            self.camera_index = camera_index
            self.model_label.configure(text=f"VietHandOCR  ·  {self.settings.device.upper()}")
            self.operation_var.set("Đã cập nhật cài đặt · Model sẽ được nạp ở lượt nhận diện tiếp theo")
            window.destroy()

        ttk.Button(body, text="Lưu cài đặt", style="Primary.TButton", command=save).pack(side="right")
        ttk.Button(body, text="Đóng", command=window.destroy).pack(side="right", padx=10)
        window.bind("<Escape>", lambda _: window.destroy())

    def close(self):
        if self.closing:
            return
        self.closing = True
        self._shutdown.set()
        self.cancel_event.set()
        self._robot_scan_cancel.set()
        self._robot_radio_cancel.set()

        def cleanup(description, action):
            try:
                action()
            except Exception:
                logger.exception("Shutdown cleanup failed: %s", description)

        close_service = getattr(self.service, "close", None)
        if close_service is not None:
            cleanup("AI process", close_service)
        cleanup("progress animation", self.progress.stop)
        if self.camera is not None:
            cleanup("camera", self.camera.close)
        for timer in (self._poll_timer, self._preview_timer, self._camera_release_timer):
            if timer is not None:
                cleanup("UI timer", lambda token=timer: self.root.after_cancel(token))
        cleanup("controls", self._sync_controls)
        cleanup("assistant", lambda: self._set_assistant(
            AssistantState.SLEEP, "Mình đi ngủ đây…", "Hẹn gặp bạn ở lần mở app tiếp theo."))
        for link in self._robot_links:
            cleanup("Bluetooth link", link.stop)
        self._close_deadline = time.monotonic() + 2.5
        try:
            self.root.after(100, self._finish_close)
        except tk.TclError:
            self._destroy()

    def _finish_close(self):
        service_closed = getattr(self.service, "closed", None)
        busy = (any(not link.closed.is_set() for link in self._robot_links)
                or any(job.is_alive() for job in self._jobs)
                or any(worker.is_alive() for worker in self._camera_workers)
                or (service_closed is not None and not service_closed.is_set()))
        if busy and time.monotonic() < self._close_deadline:
            self.root.after(50, self._finish_close)
        else:
            self._destroy()

    def _destroy(self):
        try:
            self.robot.stop()
        except tk.TclError:
            pass
        self._preview_photo = None
        self._thumbs.clear()
        self._robot_dialog = None
        self.root.__dict__.pop("report_callback_exception", None)
        try:
            self.root.destroy()
        except tk.TclError:
            pass  # A preceding Tcl error may already have destroyed the window.
