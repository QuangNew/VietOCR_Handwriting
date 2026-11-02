"""Resizable Wi-Fi form and saved ESP32 networks; credentials stay out of logs."""
import tkinter as tk
from tkinter import ttk
from .widgets import COLORS as C, label
from .theme import apply_titlebar


def open_wifi_settings(app):
    if app._wifi_dialog is not None and app._wifi_dialog.winfo_exists():
        app._wifi_dialog.lift()
        return
    window = app._wifi_dialog = tk.Toplevel(app.root)
    window.title('Wi-Fi camera · ESP32')
    window.configure(bg=C['bg']); window.transient(app.root)
    window.geometry(f'{min(820,window.winfo_screenwidth()-60)}x{min(760,window.winfo_screenheight()-80)}')
    window.minsize(660, 620)
    footer = tk.Frame(window, bg=C['bg'], padx=20, pady=14); footer.pack(side='bottom', fill='x')
    body = tk.Frame(window, bg=C['bg'], padx=20, pady=18); body.pack(fill='both', expand=True)
    label(body, 'Wi-Fi của ESP32', bold=True, size=17).pack(anchor='w')
    label(body, textvariable=app.wifi_connection_var, bold=True, justify='left', anchor='w', wraplength=740).pack(fill='x', pady=(12, 4))
    label(body, textvariable=app.wifi_detail_var, justify='left', anchor='w', wraplength=740).pack(fill='x', pady=(0, 12))
    tabs = ttk.Notebook(body); tabs.pack(fill='both', expand=True)
    form = tk.Frame(tabs, bg=C['bg'], padx=14, pady=16); tabs.add(form, text='Kết nối mạng')
    saved = tk.Frame(tabs, bg=C['bg'], padx=14, pady=16); tabs.add(saved, text='Mạng đã lưu trên ESP32')
    ssid, password = tk.StringVar(), tk.StringVar()
    if app._wifi_state is not None:
        ssid.set(app._wifi_state.ssid or app._wifi_state.saved_ssid)
    label(form, 'Tên Wi-Fi 2.4 GHz').pack(anchor='w')
    combo = ttk.Combobox(form, textvariable=ssid); combo.pack(fill='x', pady=(5, 14))
    label(form, 'Mật khẩu (để trống với mạng mở)').pack(anchor='w')
    password_entry = ttk.Entry(form, textvariable=password, show='•'); password_entry.pack(fill='x', pady=(5, 8))
    show_password = tk.BooleanVar(value=False)
    ttk.Checkbutton(form, text='Hiện mật khẩu', variable=show_password,
                    command=lambda: password_entry.configure(show='' if show_password.get() else '•')).pack(anchor='w')
    message = tk.StringVar(value='Trạng thái tự cập nhật mỗi 3 giây. Chỉ quét khi cần chọn mạng mới.')
    label(footer, textvariable=message, justify='left', anchor='w', wraplength=740).pack(fill='x', pady=(0, 10))
    controls = []

    def request(action):
        try:
            if action == 'wifi_join':
                if app._wifi_state is not None and app._wifi_state.state=='ready' and ssid.get()==app._wifi_state.ssid and not password.get():
                    message.set('Mạng này đã kết nối. Không cần nhập lại mật khẩu hoặc kết nối lại.')
                    return
                from .wifi_camera import wifi_commands
                wifi_commands(ssid.get(), password.get())
            if app.robot_link is None or not app.robot_link.wifi(action, ssid.get(), password.get()):
                raise ValueError('Kết nối trợ lý Bluetooth và đợi thao tác trước hoàn tất.')
            for button in controls: button.configure(state='disabled')
            if action == 'wifi_join': password.set('')
            message.set({'wifi_scan':'Đang quét mạng…', 'wifi_join':'Đang gửi cấu hình…',
                         'wifi_profiles':'Đang đọc các mạng lưu trong flash ESP32…'}[action])
        except ValueError as error:
            message.set(str(error))

    buttons = tk.Frame(form, bg=C['bg']); buttons.pack(fill='x', pady=14)
    for text, action in [('Quét mạng', 'wifi_scan'), ('Kết nối', 'wifi_join')]:
        button = ttk.Button(buttons, text=text, command=lambda value=action: request(value))
        button.pack(side='left', padx=(0, 8)); controls.append(button)
    saved_actions = tk.Frame(saved, bg=C['bg']); saved_actions.pack(side='bottom', fill='x', pady=(10, 0))
    secrets_area = tk.Frame(saved, bg=C['bg']); secrets_area.pack(side='bottom', fill='x', pady=(10, 0))
    label(saved, 'Mạng được lưu trong flash, giữ lại khi rút nguồn.\nChọn mạng để xem mật khẩu hoặc dùng lại cấu hình.',
          size=9, color=C['muted'], justify='left', wraplength=660).pack(anchor='w', pady=(0, 8))
    tree = ttk.Treeview(saved, columns=('ssid',), show='headings', height=4, selectmode='browse')
    tree.heading('ssid', text='Tên mạng · mạng dùng gần nhất ở đầu danh sách'); tree.column('ssid', width=460)
    tree.pack(fill='both', expand=True)
    secret = tk.StringVar()
    saved_secret = ttk.Entry(secrets_area, textvariable=secret, state='readonly', show='•'); saved_secret.pack(fill='x', pady=(0, 6))
    reveal = tk.BooleanVar(value=False)
    ttk.Checkbutton(secrets_area, text='Hiện mật khẩu mạng đã chọn', variable=reveal,
                    command=lambda: saved_secret.configure(show='' if reveal.get() else '•')).pack(anchor='w')
    profiles = []

    def selected(_=None):
        selection = tree.selection()
        secret.set(profiles[int(selection[0])].password if selection else '')
    tree.bind('<<TreeviewSelect>>', selected)

    def use_saved():
        selection = tree.selection()
        if not selection: return
        profile = profiles[int(selection[0])]
        ssid.set(profile.ssid); password.set(profile.password)
        app._wifi_widgets['name_edited'] = True
        tabs.select(form)
        message.set('Đã điền cấu hình đã lưu. Bấm Kết nối để dùng mạng này.')

    load = ttk.Button(saved_actions, text='Tải danh sách', command=lambda: request('wifi_profiles'))
    load.pack(side='left'); controls.append(load)
    ttk.Button(saved_actions, text='Dùng mạng đã chọn', command=use_saved).pack(side='left', padx=8)

    def receive_profiles(values):
        profiles[:] = values
        for row in tree.get_children(): tree.delete(row)
        secret.set('')
        for index, profile in enumerate(profiles): tree.insert('', 'end', iid=str(index), values=(profile.ssid,))
        if profiles:
            tree.selection_set('0'); selected()
        message.set(f'{len(values)} mạng đã lưu trên ESP32. Mật khẩu chỉ hiện khi bạn bật xem.')

    app._wifi_widgets = {'message':message,'combo':combo,'buttons':controls,'password':password,
                        'ssid':ssid,'name_edited':False,'receive_profiles':receive_profiles,'request':request}
    def edited(_): app._wifi_widgets['name_edited'] = True
    combo.bind('<KeyRelease>', edited); combo.bind('<<ComboboxSelected>>', edited)
    def close():
        password.set(''); secret.set(''); profiles.clear()
        app._wifi_dialog = None; app._wifi_widgets = {}; window.destroy()
    ttk.Button(footer, text='Đóng', command=close).pack(side='right')
    window.protocol('WM_DELETE_WINDOW', close); window.bind('<Escape>', lambda _:close())
    def resize(event):
        for child in body.winfo_children():
            if isinstance(child, tk.Label): child.configure(wraplength=max(200,event.width-40))
    body.bind('<Configure>', resize)
    window.after_idle(lambda:apply_titlebar(window))
    if app.robot_link is not None:
        app.robot_link.wifi('wifi_state')
