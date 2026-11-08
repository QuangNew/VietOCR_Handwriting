"""Server-only account, quota and cloud history. Network operations never run on Tk."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
from dataclasses import replace
from .preferences import update_preferences
from .remote_transport import VietOcrClient
from .widgets import COLORS as C, label, ScrollableFrame
from .theme import apply_titlebar

def open_server_settings(app, parent):
    window=tk.Toplevel(parent);window.title('VietOCR · Tài khoản & OCR Server')
    window.geometry('850x720');window.minsize(620,520);window.resizable(True,True);window.transient(parent)
    window.configure(bg=C['white']);window.grab_set();window.after_idle(lambda:apply_titlebar(window))
    footer=tk.Frame(window,bg=C['white'],padx=24,pady=14);footer.pack(side='bottom',fill='x')
    scroller=ScrollableFrame(window);scroller.pack(fill='both',expand=True)
    body=tk.Frame(scroller.inner,bg=C['white'],padx=26,pady=24);body.pack(fill='both',expand=True)
    label(body,'Tài khoản & OCR Server',size=19,bold=True).pack(anchor='w')
    label(body,'Nhận diện trên server. Ứng dụng không cài hoặc nạp model trên máy.',color=C['muted'],wraplength=730).pack(anchor='w',pady=(8,20))
    label(body,'Địa chỉ máy host',bold=True).pack(anchor='w')
    url=tk.StringVar(value=app.settings.server_url)
    ttk.Entry(body,textvariable=url).pack(fill='x',pady=(7,12),ipady=5)
    insecure=tk.BooleanVar(value=app.settings.allow_insecure_lan)
    ttk.Checkbutton(body,text='Cho phép HTTP trong mạng LAN tin cậy',variable=insecure).pack(anchor='w')
    label(body,'Nếu dùng HTTP LAN, máy host cần chạy Run-Server.cmd -Lan.',color=C['muted'],size=9).pack(anchor='w',pady=(5,18))
    account=tk.StringVar(value=app.auth.email or 'Chưa đăng nhập Google')
    label(body,'ĐĂNG NHẬP GOOGLE',size=9,bold=True,color=C['muted']).pack(anchor='w')
    label(body,textvariable=account,bold=True).pack(anchor='w',pady=(8,6))
    identity=tk.StringVar(value='Mỗi tài khoản có một định danh OCR cố định · tối đa 500 ảnh/ngày, 30 request/phút.')
    label(body,textvariable=identity,wraplength=730,justify='left',color=C['muted']).pack(anchor='w',pady=(0,12))
    actions=tk.Frame(body,bg=C['white']);actions.pack(fill='x')
    status=tk.StringVar(value='Đăng nhập mở trong trình duyệt. Token được mã hoá bằng tài khoản Windows.')
    label(body,textvariable=status,wraplength=730,justify='left').pack(anchor='w',pady=(14,18))
    label(body,'Lịch sử OCR trên Supabase',bold=True).pack(anchor='w')
    history=tk.Listbox(body,height=6,bg=C['white'],fg=C['ink'],selectbackground=C['green']);history.pack(fill='x',pady=(8,10))
    result=tk.Text(body,height=5,wrap='word',bg=C['white'],fg=C['ink']);result.pack(fill='both',expand=True)
    events=queue.Queue();cancel=threading.Event();rows=[];buttons=[];closed=False;running=False
    previous_email=app.auth.email
    def save():
        target=url.get().strip();allow=insecure.get()
        VietOcrClient(target,'',allow_insecure_lan=allow)
        update_preferences(app.preferences_path,ocr_server_url=target,ocr_server_enabled=True,ocr_server_insecure=allow,ocr_server_key_dpapi='')
        app.settings=replace(app.settings,server_url=target,allow_insecure_lan=allow)
        app.service._remote=None
        app.model_label.configure(text='OCR Server · '+target)
        return target,allow
    def launch(operation):
        nonlocal running
        if running:return
        try:target,allow=save()
        except Exception as e:status.set(str(e));return
        running=True
        for button in buttons:button.state(['disabled'])
        status.set('Đang mở Google trong trình duyệt…' if operation=='login' else 'Đang kết nối…')
        def work():
            try:
                if operation=='login':app.auth.login(cancel)
                if operation=='logout':app.auth.logout();events.put(('logout',None));return
                client=VietOcrClient(target,app.auth.access_token,allow_insecure_lan=allow)
                info=client.account();items=client.history();events.put(('account',(info,items)))
            except Exception as e:events.put(('error',str(e)))
        threading.Thread(target=work,name='VietOCR-account',daemon=True).start()
    for title,operation in [('Đăng nhập Google','login'),('Làm mới tài khoản','refresh'),('Đăng xuất','logout')]:
        button=ttk.Button(actions,text=title,command=lambda op=operation:launch(op));button.pack(side='left',padx=(0,10));buttons.append(button)
    def select(_=None):
        selected=history.curselection()
        if not selected:return
        item=rows[selected[0]]
        # Fetch full result separately; summary responses deliberately omit recognized text.
        target,allow=app.settings.server_url,app.settings.allow_insecure_lan
        def read():
            try:events.put(('text',VietOcrClient(target,app.auth.access_token,allow_insecure_lan=allow).get(item['id']).get('text') or item.get('error') or item['state']))
            except Exception as e:events.put(('error',str(e)))
        threading.Thread(target=read,name='VietOCR-history',daemon=True).start()
    history.bind('<<ListboxSelect>>',select)
    def poll():
        nonlocal running,rows,previous_email
        if closed:return
        while True:
            try:kind,value=events.get_nowait()
            except queue.Empty:break
            if kind=='text':result.delete('1.0','end');result.insert('1.0',value);continue
            running=False
            for button in buttons:button.state(['!disabled'])
            if previous_email and previous_email != app.auth.email:
                app.clear_batch()
            previous_email=app.auth.email
            account.set(app.auth.email or 'Chưa đăng nhập Google')
            if kind=='account':
                info,rows=value;identity.set(f"{info.get('ocrId') or info['id']}\nHôm nay {info['usedToday']}/{info['dailyLimit']} ảnh · {info['ratePerMinute']} request/phút · đặt lại 00:00 giờ Việt Nam")
                history.delete(0,'end')
                for item in rows:history.insert('end',f"{item['createdAt'][:19].replace('T',' ')} · {item['state']} · #{item['id'][:8]}")
                status.set('Đã kết nối OCR Server và Supabase.')
            elif kind=='logout':identity.set('Đã đăng xuất. Đăng nhập lại để nhận diện.');history.delete(0,'end');result.delete('1.0','end');status.set('Đã xoá phiên đăng nhập khỏi máy.')
            else:status.set(value)
        window.after(100,poll)
    def close():
        nonlocal closed
        closed=True;cancel.set();window.destroy()
    def save_close():
        try:save();app.operation_var.set('Đã lưu OCR Server');close()
        except Exception as e:status.set(str(e))
    ttk.Button(footer,text='Lưu địa chỉ server',command=save_close,style='Primary.TButton').pack(side='right')
    ttk.Button(footer,text='Đóng',command=close).pack(side='right',padx=10)
    window.protocol('WM_DELETE_WINDOW',close);window.bind('<Escape>',lambda _:close());window.after(100,poll)
    if app.auth.email:window.after(150,lambda:launch('refresh'))
    for child in (body,*body.winfo_children()):scroller.bind_scroll(child)
