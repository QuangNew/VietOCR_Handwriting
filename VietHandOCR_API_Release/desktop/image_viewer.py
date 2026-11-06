"""Full-resolution image inspection; viewport transformations never edit pixels."""

import math
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .theme import apply_titlebar
from .widgets import COLORS as C
from .shape_crop import outline, rotate_points, crop_shape


@dataclass
class ImageViewport:
    width: int
    height: int
    scale: float = 1.0
    x: float = 0.0
    y: float = 0.0

    def fit(self, width, height):
        self.scale = max(0.01, min(width / self.width, height / self.height))
        self.x, self.y = (width - self.width * self.scale) / 2, (height - self.height * self.scale) / 2

    def point(self, x, y):
        return (max(0, min(self.width, (x - self.x) / self.scale)),
                max(0, min(self.height, (y - self.y) / self.scale)))

    def zoom(self, factor, x, y):
        # Use the unclamped point here so zooming on the letterbox also stays put.
        px, py = (x - self.x) / self.scale, (y - self.y) / self.scale
        self.scale = max(0.02, min(16.0, self.scale * factor))
        self.x, self.y = x - px * self.scale, y - py * self.scale

    def crop_box(self, start, end):
        left, right = sorted((start[0], end[0]))
        top, bottom = sorted((start[1], end[1]))
        box = (max(0, math.floor(left)), max(0, math.floor(top)),
               min(self.width, math.ceil(right)), min(self.height, math.ceil(bottom)))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return None
        return box


class ImageViewer:
    def __init__(self, root, item, on_change, can_edit, on_close):
        self.item, self.on_change, self.can_edit, self.on_close = item, on_change, can_edit, on_close
        self.image = item.image
        self.viewport = ImageViewport(*self.image.size)
        self.fit_mode, self.selection, self.drag = True, None, None
        self.stroke = []
        self.photo = None
        self.window = tk.Toplevel(root)
        self.window.title(f'Ảnh chi tiết · {item.name}')
        self.window.configure(bg=C['bg'])
        self.window.geometry(f'{min(1200, root.winfo_screenwidth()-60)}x{min(880, root.winfo_screenheight()-100)}')
        self.window.minsize(640, 440)
        self.window.resizable(True, True)
        footer = tk.Frame(self.window, bg=C['bg'], padx=12, pady=12)
        footer.pack(side='bottom', fill='x')
        self.info = tk.StringVar()
        tk.Label(footer, textvariable=self.info, bg=C['bg'], fg=C['ink']).pack(anchor='w', pady=(0, 8))
        for text, command in (('Vừa cửa sổ', self.fit), ('−', lambda: self.zoom(.8)),
                              ('+', lambda: self.zoom(1.25)), ('100%', self.actual_size)):
            ttk.Button(footer, text=text, command=command, style='Small.TButton').pack(side='left', padx=(0, 5))
        self.crop_mode = tk.BooleanVar(value=False)
        ttk.Checkbutton(footer, text='Chọn vùng crop', variable=self.crop_mode).pack(side='left', padx=6)
        self.apply_button = ttk.Button(footer, text='Áp dụng crop', command=self.apply_crop, style='Small.TButton')
        self.apply_button.pack(side='left', padx=5)
        tools = tk.Frame(self.window, bg=C['bg'], padx=12, pady=10)
        tools.pack(side='top', fill='x')
        for text, command in (('Lưu ảnh', self.save), ('Lưu ảnh gốc', lambda: self.save(original=True)),
                              ('Khôi phục ảnh gốc', self.restore), ('Đóng', self.close)):
            ttk.Button(tools, text=text, command=command, style='Small.TButton').pack(side='left', padx=(0, 6))
        crop_tools=tk.Frame(self.window,bg=C['bg'],padx=12,pady=6);crop_tools.pack(side='top',fill='x')
        self.crop_shape=tk.StringVar(value='Chữ nhật');self.crop_angle=tk.DoubleVar(value=0)
        picker=ttk.Combobox(crop_tools,textvariable=self.crop_shape,values=('Chữ nhật','Elip','Tự vẽ'),state='readonly',width=12)
        picker.pack(side='left',padx=(0,12));picker.bind('<<ComboboxSelected>>',self._reset_selection)
        tk.Label(crop_tools,text='Xoay vùng:',bg=C['bg'],fg=C['ink']).pack(side='left')
        ttk.Scale(crop_tools,from_=-180,to=180,variable=self.crop_angle,command=lambda _:self.draw()).pack(side='left',fill='x',expand=True,padx=8)
        ttk.Button(crop_tools,text='0°',style='Small.TButton',command=lambda:(self.crop_angle.set(0),self.draw())).pack(side='right')
        tk.Label(self.window, text='Cuộn để zoom · Bật crop rồi kéo/vẽ vùng kín · Xoay vùng chọn để căn chữ · Ngoài vùng là nền trắng',
                 bg=C['bg'], fg=C['muted']).pack(anchor='w', padx=12, pady=(0, 8))
        self.canvas = tk.Canvas(self.window, bg=C['preview'], highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=12)
        self.canvas.bind('<Configure>', self._resize)
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Button-4>', lambda e: self._wheel(e, 1.2))
        self.canvas.bind('<Button-5>', lambda e: self._wheel(e, 1/1.2))
        self.canvas.bind('<ButtonPress-1>', self._down)
        self.canvas.bind('<B1-Motion>', self._move)
        self.canvas.bind('<ButtonRelease-1>', self._up)
        self.window.bind('<Escape>', lambda _: self.close())
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.after_idle(lambda: apply_titlebar(self.window))

    def _resize(self, _=None):
        if self.fit_mode:
            self.viewport.fit(max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
        self.draw()

    def fit(self):
        self.fit_mode = True
        self._resize()

    def actual_size(self):
        self.zoom(1 / self.viewport.scale)

    def zoom(self, factor, x=None, y=None):
        self.fit_mode = False
        self.viewport.zoom(factor, self.canvas.winfo_width()/2 if x is None else x,
                           self.canvas.winfo_height()/2 if y is None else y)
        self.draw()

    def _wheel(self, event, factor=None):
        self.zoom(factor or (1.2 if event.delta > 0 else 1/1.2), event.x, event.y)
        return 'break'

    def _down(self, event):
        if self.crop_mode.get():
            start = self.viewport.point(event.x, event.y)
            self.drag = ('crop', start)
            self.selection = (start, start)
            self.stroke = [start];self.crop_angle.set(0)
        else:
            self.fit_mode = False
            self.drag = ('pan', event.x, event.y, self.viewport.x, self.viewport.y)

    def _move(self, event):
        if self.drag is None:
            return
        if self.drag[0] == 'crop':
            point=self.viewport.point(event.x,event.y)
            if self.crop_shape.get()=='Tự vẽ':
                if math.dist(point,self.stroke[-1])>=max(.5,2/self.viewport.scale): self.stroke.append(point)
                if len(self.stroke)>4096:self.stroke=self.stroke[::2]
                self.selection=((min(p[0] for p in self.stroke),min(p[1] for p in self.stroke)),
                                (max(p[0] for p in self.stroke),max(p[1] for p in self.stroke)))
            else:self.selection = (self.drag[1],point)
        else:
            _, x, y, ox, oy = self.drag
            self.viewport.x, self.viewport.y = ox + event.x - x, oy + event.y - y
        self.draw()

    def _up(self, event):
        self._move(event)
        self.drag = None

    def draw(self):
        self.canvas.delete('selection')
        v = self.viewport
        # Render only the visible source rectangle: even 1600% zoom stays bounded
        # by the screen size, rather than allocating a huge enlarged 3 MP image.
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        left, top = max(0, math.floor(-v.x/v.scale)), max(0, math.floor(-v.y/v.scale))
        right = min(v.width, math.ceil((width-v.x)/v.scale))
        bottom = min(v.height, math.ceil((height-v.y)/v.scale))
        render_key=(id(self.image),v.scale,v.x,v.y,width,height)
        if right > left and bottom > top and getattr(self,'_render_key',None)!=render_key:
            visible = self.image.crop((left, top, right, bottom))
            visible = visible.resize((max(1, round((right-left)*v.scale)), max(1, round((bottom-top)*v.scale))), Image.Resampling.BICUBIC)
            self.photo = ImageTk.PhotoImage(visible, master=self.window)
            self.canvas.delete('photo')
            self.canvas.create_image(v.x+left*v.scale, v.y+top*v.scale, image=self.photo, anchor='nw',tags='photo')
            self._render_key=render_key
        elif right<=left or bottom<=top:
            self.canvas.delete('photo');self._render_key=None
        crop = v.crop_box(*self.selection) if self.selection else None
        points=self._selection_points()
        if len(points)>=2:
            rotated=rotate_points(points,self.crop_angle.get())
            coords=[value for x,y in rotated for value in (v.x+x*v.scale,v.y+y*v.scale)]
            if len(points)>2:self.canvas.create_polygon(*coords,fill='',outline=C['green'],width=2,dash=(6,3),tags='selection')
            else:self.canvas.create_line(*coords,fill=C['green'],width=2,tags='selection')
        self.sync_controls()

    def _reset_selection(self,_=None):
        self.selection=None;self.stroke=[];self.crop_angle.set(0);self.crop_mode.set(True);self.draw()

    def _selection_points(self):
        box=self.viewport.crop_box(*self.selection) if self.selection else None
        if not box:return []
        if self.crop_shape.get()=='Tự vẽ':return self.stroke
        return outline(box,'ellipse' if self.crop_shape.get()=='Elip' else 'rectangle')

    def sync_controls(self):
        v = self.viewport
        crop = v.crop_box(*self.selection) if self.selection else None
        self.apply_button.configure(state='normal' if crop and len(self._selection_points())>=3 and self.can_edit() else 'disabled')
        detail = f' · Crop {crop[2]-crop[0]} × {crop[3]-crop[1]} · {self.crop_angle.get():.0f}°' if crop else ''
        waiting = ' · Đợi nhận diện xong để áp dụng crop' if not self.can_edit() else ''
        self.info.set(f'{self.image.width} × {self.image.height} px · Zoom {v.scale:.0%}{detail}{waiting}')

    def apply_crop(self):
        box = self.viewport.crop_box(*self.selection) if self.selection else None
        if box is None or not self.can_edit():
            return
        try:self._replace(crop_shape(self.image,self._selection_points(),self.crop_angle.get()))
        except ValueError as error:messagebox.showerror('Không crop được ảnh',str(error),parent=self.window)

    def restore(self):
        if not self.can_edit() or self.item.original_path is None:
            return
        with Image.open(self.item.original_path) as original:
            self._replace(original.convert('RGB'))

    def _replace(self, image):
        try:
            self.item.replace_image(image)
        except (OSError, ValueError) as error:
            messagebox.showerror('Không sửa được ảnh', str(error), parent=self.window)
            return
        self.image = self.item.image
        self.viewport = ImageViewport(*self.image.size)
        self.selection = None
        self.stroke=[];self.crop_angle.set(0)
        self.fit()
        self.on_change(self.item)

    def save(self, original=False):
        save_image_dialog(self.window, self.item, original=original)

    def close(self):
        self.window.destroy()
        self.image.close()
        self.on_close()


def save_image_dialog(parent, item, *, original=False):
    suffix = '.jpg' if original and item.original_path and item.original_path.suffix == '.jpg' else '.png'
    destination = filedialog.asksaveasfilename(parent=parent, title='Lưu ảnh gốc' if original else 'Lưu ảnh',
        initialfile=Path(item.name).stem + suffix, defaultextension=suffix,
        filetypes=[('JPEG', '*.jpg'), ('PNG', '*.png')])
    if destination:
        try:
            item.export(destination, original=original)
        except (OSError, ValueError) as error:
            messagebox.showerror('Không lưu được ảnh', str(error), parent=parent)

