"""Document-first desktop layout. All actions delegate to the existing controller."""
import tkinter as tk
from tkinter import ttk
from .widgets import COLORS as C, label, card, ScrollableFrame, RobotFace


def build_workspace(self):
    from .application import device_label
    shell = tk.Frame(self.root, bg=C['bg'])
    shell.pack(fill='both', expand=True)
    sidebar = tk.Frame(shell, bg=C['white'], width=292)
    sidebar.pack(side='left', fill='y')
    sidebar.pack_propagate(False)
    tk.Frame(shell, bg=C['border'], width=1).pack(side='left', fill='y')
    brand = tk.Frame(sidebar, bg=C['white'])
    brand.pack(fill='x', padx=20, pady=(14, 12))
    self.brand_mark = tk.Canvas(brand, width=43, height=43, bg=C['white'], highlightthickness=0)
    self._draw_brand()
    self.brand_mark.pack(side='left', padx=(0, 10))
    title = tk.Frame(brand, bg=C['white']); title.pack(side='left')
    label(title, 'VietOCR', size=18, bold=True).pack(anchor='w')
    brand_caption = label(title, 'Không gian tài liệu', size=9, color=C['muted'])
    brand_caption.pack(anchor='w')

    # Reserve utilities and assistant before the scrolling image queue.
    utilities = tk.Frame(sidebar, bg=C['white']); utilities.pack(side='bottom', fill='x', padx=14, pady=14)
    self.settings_button = ttk.Button(utilities, text='Cài đặt model', style='Small.TButton', command=self.open_settings)
    self.settings_button.pack(fill='x', pady=(0, 7))
    self.theme_button = ttk.Button(utilities, text=self._theme_button_text(), style='Small.TButton', width=18, command=self.toggle_theme)
    self.theme_button.pack(fill='x')
    assistant = tk.Frame(sidebar, bg=C['white']); assistant.pack(side='bottom', fill='x', padx=18, pady=(10, 0))
    tk.Frame(assistant, bg=C['border'], height=1).pack(fill='x', pady=(0, 10))
    face = tk.Frame(assistant, bg=C['white']); face.pack(fill='x')
    self.robot = RobotFace(face, size=52, bg=C['white']); self.robot.pack(side='left', padx=(0, 8))
    caption = tk.Frame(face, bg=C['white']); caption.pack(side='left', fill='x', expand=True)
    self.assistant_title = label(caption, size=9, bold=True, justify='left', anchor='w', wraplength=185, height=2)
    self.assistant_title.pack(fill='x')
    self.assistant_badge = label(caption, size=8, color=C['green']); self.assistant_badge.pack(anchor='w')
    self.assistant_detail = label(assistant, size=8, color=C['muted'], justify='left', anchor='nw', wraplength=250, height=2)
    self.assistant_detail.pack(fill='x', pady=(5, 0))

    connection = tk.Frame(sidebar, bg=C['white']); connection.pack(fill='x', padx=16, pady=(0, 16))
    label(connection, 'KẾT NỐI', size=8, bold=True, color=C['muted']).pack(anchor='w', pady=(0, 8))
    network_buttons = tk.Frame(connection, bg=C['white']); network_buttons.pack(fill='x', pady=(0, 8))
    network_buttons.columnconfigure((0, 1), weight=1, uniform='network')
    self.robot_button = ttk.Button(network_buttons, text='ESP32', style='Small.TButton', command=self.open_robot_settings)
    self.robot_button.grid(row=0, column=0, sticky='ew', padx=(0, 6))
    ttk.Button(network_buttons, text='Wi-Fi', style='Small.TButton', command=self.open_wifi_settings).grid(row=0, column=1, sticky='ew')
    self.robot_connection_label = label(connection, 'ESP32 chưa kết nối', size=8, color=C['muted'], wraplength=256, justify='left', anchor='w')
    self.robot_connection_label.pack(fill='x')
    label(connection, textvariable=self.wifi_connection_var, size=8, color=C['muted'], wraplength=256,
          justify='left', anchor='w').pack(fill='x', pady=(4, 0))
    queue_header = tk.Frame(sidebar, bg=C['white']); queue_header.pack(fill='x', padx=18, pady=(0, 10))
    label(queue_header, 'Ảnh của bạn', size=10, bold=True).pack(side='left')
    self.queue_count = label(queue_header, '0 ảnh', size=9, color=C['muted']); self.queue_count.pack(side='right')
    queue_actions = tk.Frame(sidebar, bg=C['white'])
    queue_actions.pack(side='bottom', fill='x', padx=12, pady=(6, 0))
    self.clear_button = ttk.Button(queue_actions, text='Dọn danh sách', style='Small.TButton', command=self.clear_batch)
    self.clear_button.pack(side='right', fill='x', expand=True, padx=(6,0))
    self.save_all_images_button = ttk.Button(queue_actions, text='Tải tất cả', style='Small.TButton', command=self.save_all_images)
    self.save_all_images_button.pack(side='left', fill='x', expand=True)
    self.queue_list = ScrollableFrame(sidebar); self.queue_list.pack(fill='both', expand=True, padx=8)
    # Keep the image queue usable on short windows / high DPI. Theme switches
    # never change this breakpoint or recreate a widget.
    compact_sidebar = None
    def adapt_sidebar(event):
        nonlocal compact_sidebar
        compact = event.height < 820
        if compact == compact_sidebar:
            return
        compact_sidebar = compact
        if compact:
            brand_caption.pack_forget()
            self.assistant_detail.pack_forget()
        else:
            brand_caption.pack(anchor='w')
            self.assistant_detail.pack(fill='x', pady=(5, 0))
    sidebar.bind('<Configure>', adapt_sidebar)

    main = tk.Frame(shell, bg=C['bg']); main.pack(side='left', fill='both', expand=True, padx=24, pady=22)
    footer = tk.Frame(main, bg=C['bg']); footer.pack(side='bottom', fill='x', pady=(14, 0))
    header = tk.Frame(main, bg=C['bg']); header.pack(fill='x', pady=(0, 18))
    heading = tk.Frame(header, bg=C['bg']); heading.pack(side='left')
    label(heading, 'Tài liệu', size=24, bold=True).pack(anchor='w')
    label(heading, 'Chụp ảnh. Đọc chữ. Lưu điều bạn cần.', size=10, color=C['muted']).pack(anchor='w', pady=(3, 0))
    self.ov_shot_button = ttk.Button(header, text='Chụp OV5640', style='Primary.TButton', command=self.open_camera)
    self.ov_shot_button.pack(side='right')
    # One entry opens the viewfinder; the shutter lives inside that window.
    self.camera_button = self.ov_shot_button
    self.upload_button = ttk.Button(header, text='Tải ảnh lên', command=self.import_files)
    self.upload_button.pack(side='right', padx=8)

    self.workspace_split = tk.PanedWindow(main, orient='horizontal', bg=C['bg'], bd=0,
                                        sashwidth=12, sashrelief='flat', opaqueresize=False)
    self.workspace_split.pack(fill='both', expand=True)
    preview_card = card(self.workspace_split)
    result_card = card(self.workspace_split)
    self.workspace_split.add(preview_card, minsize=280, stretch='always')
    self.workspace_split.add(result_card, minsize=280, stretch='always')
    preview_header = tk.Frame(preview_card, bg=C['white']); preview_header.pack(fill='x', padx=18, pady=16)
    label(preview_header, 'Ảnh gốc', size=11, bold=True).pack(side='left')
    self.preview_index = label(preview_header, '', size=9, color=C['muted']); self.preview_index.pack(side='right')
    tools = tk.Frame(preview_card, bg=C['white']); tools.pack(side='bottom', fill='x', padx=12, pady=12)
    self.rotate_button = ttk.Button(tools, text='Xoay trái', style='Small.TButton', command=self.rotate_selected)
    self.rotate_button.pack(side='left')
    self.save_image_button = ttk.Button(tools, text='Lưu ảnh', style='Small.TButton', command=self.save_selected_image)
    self.save_image_button.pack(side='left', padx=5)
    self.remove_button = ttk.Button(tools, text='Xóa', style='Small.TButton', command=self.remove_selected)
    self.remove_button.pack(side='right')
    self.image_info = label(preview_card, 'Bấm vào ảnh để phóng to và cắt vùng chữ', size=8, color=C['muted'], wraplength=310)
    self.image_info.pack(side='bottom', fill='x', padx=12, pady=(10, 0))
    self.preview = tk.Canvas(preview_card, bg=C['preview'], highlightthickness=0, width=1, height=1)
    self.preview.pack(fill='both', expand=True, padx=12)
    self.preview.bind('<Configure>', self._schedule_preview)
    self.preview.bind('<Button-1>', lambda _: self.open_image_viewer())

    result_header = tk.Frame(result_card, bg=C['white']); result_header.pack(fill='x', padx=18, pady=(16, 8))
    label(result_header, 'Văn bản', size=11, bold=True).pack(side='left')
    self.retry_button = ttk.Button(result_header, text='Đọc lại', style='Small.TButton', command=self.retry_selected)
    self.retry_button.pack(side='right')
    self.result_hint = label(result_card, 'Chỉnh sửa trực tiếp, nội dung được giữ trong phiên.', size=9, color=C['muted'], anchor='w', justify='left', wraplength=330)
    self.result_hint.pack(fill='x', padx=18, pady=(0, 12))
    result_card.bind('<Configure>', lambda e: self.result_hint.configure(wraplength=max(100, e.width-36)))
    preview_card.bind('<Configure>', lambda e: self.image_info.configure(wraplength=max(100, e.width-24)))
    bottom = tk.Frame(result_card, bg=C['white']); bottom.pack(side='bottom', fill='x', padx=16, pady=12)
    self.text_stats = label(bottom, '0 ký tự', size=8, color=C['muted']); self.text_stats.pack(side='left')
    self.copy_button = ttk.Button(bottom, text='Sao chép', style='Small.TButton', command=self.copy_selected)
    self.copy_button.pack(side='right')
    text_frame = tk.Frame(result_card, bg=C['white']); text_frame.pack(fill='both', expand=True, padx=12)
    self.result_text = tk.Text(text_frame, bg=C['white'], fg=C['ink'], font=('Segoe UI', 12),
        wrap='word', relief='flat', borderwidth=0, padx=6, pady=12, insertbackground=C['green'],
        selectbackground=C['selection'], selectforeground=C['ink'], undo=True,
        width=20, height=3, highlightthickness=0, spacing1=4, spacing3=6)
    scroll = ttk.Scrollbar(text_frame, command=self.result_text.yview)
    self.result_text.configure(yscrollcommand=scroll.set)
    self.result_text.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
    self.result_text.bind('<<Modified>>', self._on_text_modified)
    self.empty_result = tk.Frame(text_frame, bg=C['white'])
    self.empty_result.place(relx=.5, rely=.4, anchor='center', relwidth=.88)
    self.empty_result_title = label(self.empty_result, 'Văn bản sẽ ở đây', size=16, bold=True); self.empty_result_title.pack()
    self.empty_result_detail = label(self.empty_result, 'Chụp một trang giấy để bắt đầu.\nBạn có thể sửa nội dung sau khi nhận diện.',
                                    size=10, color=C['muted'], justify='center', wraplength=290)
    self.empty_result_detail.pack(pady=(10, 0))
    text_frame.bind('<Configure>', lambda e: self.empty_result_detail.configure(wraplength=max(100, int(e.width*.82))))

    actions = tk.Frame(footer, bg=C['bg']); actions.pack(fill='x', pady=(0, 12))
    self.layout_var = tk.StringVar(value='Tự tách dòng')
    self.layout_combo = ttk.Combobox(actions, textvariable=self.layout_var, state='readonly', width=14,
                                   values=('Tự tách dòng', 'Một dòng'))
    self.layout_combo.pack(side='left')
    self.recognize_button = ttk.Button(actions, text='Nhận diện', style='Primary.TButton', command=self.start_recognition)
    self.recognize_button.pack(side='left', padx=(8, 6))
    self.cancel_button = ttk.Button(actions, text='Dừng', command=self.cancel_recognition, state='disabled'); self.cancel_button.pack(side='left')
    self.save_button = ttk.Button(actions, text='Xuất .txt', command=self.save_results); self.save_button.pack(side='right')
    self.copy_all_button = ttk.Button(actions, text='Chép tất cả', command=self.copy_all); self.copy_all_button.pack(side='right', padx=6)
    self.progress = ttk.Progressbar(footer, style='Green.Horizontal.TProgressbar', maximum=100)
    self.progress.pack(fill='x')
    status = tk.Frame(footer, bg=C['bg']); status.pack(fill='x', pady=(10, 0))
    self.operation_var = tk.StringVar(value='Bắt đầu: tải ảnh từ máy tính hoặc chụp bằng OV5640.')
    self.operation_label = label(status, textvariable=self.operation_var, size=8, color=C['muted'], anchor='w', justify='left')
    self.operation_label.pack(fill='x')
    status.bind('<Configure>', lambda e: self.operation_label.configure(wraplength=max(100,e.width-12)))
    self.model_label = label(status, f'Xử lý trên máy  ·  {device_label(self.settings.device)}', size=8, color=C['muted'], anchor='w')
    self.model_label.pack(fill='x', pady=(4, 0))
