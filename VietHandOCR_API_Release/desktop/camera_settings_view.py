"""Native camera controls. Edits stay local until Apply is pressed."""
import tkinter as tk
from tkinter import ttk
from .camera_settings import FIELDS, DEFAULTS, PRESETS, validate_settings
from .widgets import COLORS as C, label, ScrollableFrame
from .theme import apply_titlebar

class CameraSettingsWindow:
    def __init__(self, parent, on_load, on_apply):
        self.on_load, self.on_apply = on_load, on_apply
        self.window = tk.Toplevel(parent)
        self.window.title('Cấu hình camera OV5640')
        self.window.configure(bg=C['bg']); self.window.transient(parent)
        self.window.geometry(f'{min(980,parent.winfo_screenwidth()-80)}x{min(800,parent.winfo_screenheight()-100)}')
        self.window.minsize(720,500)
        self.values, self.inputs = {}, {}
        self.loaded = False; self.working = True
        self.persist = tk.BooleanVar(value=True)
        footer=tk.Frame(self.window,bg=C['bg'],padx=16,pady=12); footer.pack(side='bottom',fill='x')
        self.message=tk.StringVar(value='Đang đọc cấu hình từ ESP32…')
        label(footer,textvariable=self.message,wraplength=690,justify='left').pack(fill='x',pady=(0,8))
        self.save=ttk.Checkbutton(footer,text='Nhớ cấu hình trên ESP32 sau khi mất điện',variable=self.persist)
        self.save.pack(anchor='w',pady=(0,8))
        buttons=tk.Frame(footer,bg=C['bg']); buttons.pack(fill='x')
        self.reload=ttk.Button(buttons,text='Tải lại',command=on_load); self.reload.pack(side='left')
        self.defaults=ttk.Button(buttons,text='Mặc định',command=self.reset); self.defaults.pack(side='left',padx=6)
        self.apply=ttk.Button(buttons,text='Áp dụng',style='Primary.TButton',command=self.submit); self.apply.pack(side='right')
        ttk.Button(buttons,text='Đóng',command=self.window.destroy).pack(side='right',padx=6)
        header=tk.Frame(self.window,bg=C['bg'],padx=16,pady=12); header.pack(fill='x')
        label(header,'Camera OV5640',size=16,bold=True).pack(anchor='w')
        label(header,'Ảnh chụp luôn 5 MP. Bấm vào chữ trên preview để chọn điểm AF.\nQS thấp = nét hơn, ảnh nặng hơn. Chỉnh xong bấm Áp dụng.',justify='left',wraplength=860).pack(anchor='w',pady=8)
        presets=tk.Frame(header,bg=C['bg']); presets.pack(fill='x')
        for name in PRESETS:
            ttk.Button(presets,text=name,style='Small.TButton',command=lambda n=name:self.preset(n)).pack(side='left',padx=(0,6))
        tabs=ttk.Notebook(self.window); tabs.pack(fill='both',expand=True,padx=16)
        groups={}
        for key,(title,group,low,high,default,choices) in FIELDS.items():
            if group not in groups:
                scroll=ScrollableFrame(tabs); tabs.add(scroll,text=group); groups[group]=scroll
            scroll=groups[group]; row=tk.Frame(scroll.inner,bg=C['white'],padx=12,pady=10)
            row.pack(fill='x'); row.columnconfigure(1,weight=1)
            label(row,title,bg=C['white'],wraplength=310,justify='left').grid(row=0,column=0,sticky='w',padx=(0,12))
            if choices is not None:
                value=tk.StringVar(value=choices[default])
                control=ttk.Combobox(row,textvariable=value,values=list(choices.values()),state='readonly',width=24)
            else:
                value=tk.IntVar(value=default)
                control=ttk.Spinbox(row,textvariable=value,from_=low,to=high,width=12)
            control.grid(row=0,column=1,sticky='e')
            control.bind('<<ComboboxSelected>>',lambda _:self.sync())
            scroll.bind_scroll(row)
            self.values[key]=value; self.inputs[key]=control
        self.window.after_idle(lambda:apply_titlebar(self.window))
        self.sync()

    @property
    def alive(self):
        return bool(self.window.winfo_exists())

    def set_values(self, values):
        for key,value in values.items():
            choices=FIELDS[key][5]
            self.values[key].set(choices[value] if choices is not None else value)
        self.sync()

    def read(self):
        result={}
        for key,var in self.values.items():
            choices=FIELDS[key][5]
            result[key]=next(n for n,label in choices.items() if label==var.get()) if choices is not None else int(var.get())
        return validate_settings(result)

    def sync(self):
        for key,control in self.inputs.items():
            enabled=self.loaded and not self.working
            if key=='aec_value': enabled=enabled and self.values['aec'].get()==FIELDS['aec'][5][0]
            if key=='ae_level': enabled=enabled and self.values['aec'].get()==FIELDS['aec'][5][1]
            if key=='agc_gain': enabled=enabled and self.values['agc'].get()==FIELDS['agc'][5][0]
            control.configure(state=('readonly' if FIELDS[key][5] is not None else 'normal') if enabled else 'disabled')
        for control in (self.defaults,self.apply,self.save): control.configure(state='normal' if self.loaded and not self.working else 'disabled')
        self.reload.configure(state='disabled' if self.working else 'normal')

    def busy(self, value=True):
        self.working=value
        if value: self.message.set('Đang áp dụng trên ESP32…' if self.loaded else 'Đang đọc cấu hình…')
        self.sync()

    def receive(self, config=None, error=''):
        self.working=False
        if error: self.message.set(str(error))
        else:
            self.loaded=True; self.set_values(config['settings'])
            self.message.set('Đã lưu trên ESP32.' if config['saved'] else 'Cấu hình hiện tại trên ESP32 · Chưa lưu flash.')
        self.sync()

    def reset(self):
        if self.loaded and not self.working:
            self.set_values(DEFAULTS); self.message.set('Đã chọn mặc định. Bấm Áp dụng để gửi tới camera.')

    def preset(self,name):
        if self.loaded and not self.working:
            self.set_values(PRESETS[name]); self.message.set(f'Đã chọn {name}. Ảnh chụp vẫn 5 MP; bấm Áp dụng.')

    def submit(self):
        try: values=self.read()
        except (ValueError,tk.TclError,StopIteration) as error:
            self.message.set(f'Kiểm tra các thông số: {error}'); return
        self.on_apply(values,self.persist.get())
