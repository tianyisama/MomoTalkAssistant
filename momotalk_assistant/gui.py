from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, ttk

import cv2
from PIL import Image, ImageTk

from . import __version__
from .adb import AdbClient, AdbError, Device, DisplayBinding, resolve_adb
from .diagnostics import analyze_video, inspect_image
from .paths import data_dir
from .paths import resource_dir
from .runner import Runner
from .options import RunOptions
from .preview import PreviewService
from .servers import can_automate
from .ui_copy import USAGE_STEPS, USAGE_TIPS, REPOSITORY_URL
from .vision import annotate


COLORS = {"bg":"#F4F3F1", "surface":"#FFFFFF", "text":"#202D3D", "muted":"#536174",
          "line":"#D7DCE2", "accent":"#A32C55", "hover":"#842244", "soft":"#FAEDF2",
          "preview":"#182331", "error":"#B42332", "ok":"#21724E"}


class Application:
    def __init__(self, preview_file: str = ""):
        self.root = tk.Tk()
        self.root.title(f"桃信助手 · MomoTalk Assistant {__version__}")
        self.root.geometry("1120x840")
        self.root.minsize(1020, 800)
        self.root.configure(bg=COLORS["bg"])
        icon=resource_dir()/"assets/app.ico"
        if icon.is_file(): self.root.iconbitmap(str(icon))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.events = queue.Queue()
        self.latest_frame = None
        self.worker = None
        self.stop_event = threading.Event()
        self.devices: list[Device] = []
        self.display_targets: list[DisplayBinding] = []
        self.preview_ready=False
        self.image_reference = None
        self.preview_image = None
        self.busy = False
        self.settings_window = None
        self.usage_window = None
        self.browse_button = None
        self.connect_button = None
        self.config_path = data_dir()/"settings.json"
        self.settings = self._read_settings()
        try: self.options = RunOptions(self.settings.get("idle_seconds",8))
        except (ValueError,TypeError): self.options = RunOptions()
        self.idle_wait = tk.StringVar(value=f"{self.options.idle_seconds:g}")
        self.wait_save_timer = None
        self.pending_device_preview = False
        self.preview_service = PreviewService(self.emit)
        self.adb_path = tk.StringVar(value=self.settings.get("adb_path", ""))
        self.endpoint = tk.StringVar(value=self.settings.get("endpoint", ""))
        self.device_label = tk.StringVar()
        self.display_label = tk.StringVar()
        self.preview_only = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="尚未连接模拟器")
        self.scene = tk.StringVar(value="等待连接")
        self.preview_source = tk.StringVar(value="设备画面将在这里显示")
        self.counter = tk.StringVar(value="回复确认 0  ·  剧情完成 0  ·  列表刷新 0")
        self._styles()
        self._layout()
        self.preview_only.trace_add("write",lambda *_:self._update_buttons())
        self.idle_wait.trace_add("write",self._idle_wait_changed)
        self.root.bind("<Escape>", lambda event:self.stop())
        self.root.after(80, self._poll)
        self._log("先打开模拟器中的游戏主页，再点击“查找模拟器”。")
        self._update_buttons()
        if preview_file:
            self.root.after(250, lambda:self.inspect_file(Path(preview_file)))
        else:
            self.root.after(400, self.discover)

    def _read_settings(self):
        try:
            result = json.loads(self.config_path.read_text(encoding="utf-8"))
            return result if isinstance(result, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self):
        settings = {"adb_path":self.adb_path.get(), "endpoint":self.endpoint.get(),
                    "serial":self.selected_serial(),"idle_seconds":self.options.idle_seconds}
        try: self.config_path.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding="utf-8")
        except OSError as exc: self._log(f"设置未保存：{exc}")

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["surface"],foreground=COLORS["text"])
        style.configure("Muted.TLabel", foreground=COLORS["muted"])
        style.configure("Section.TLabel", font=("Microsoft YaHei UI",11,"bold"))
        style.configure("TButton", padding=(10,6),background="#EEF1F5",foreground=COLORS["text"],
                        borderwidth=1, bordercolor=COLORS["line"],focuscolor=COLORS["accent"])
        style.map("TButton",background=[("active","#E1E6ED"),("disabled","#F2F3F5")],
                  foreground=[("disabled","#697789")])
        style.configure("Primary.TButton",background=COLORS["accent"],foreground="#FFFFFF",
                        font=("Microsoft YaHei UI",11,"bold"),padding=(14,11),borderwidth=0)
        style.map("Primary.TButton",background=[("active",COLORS["hover"]),("disabled","#D7C4CB")],
                  foreground=[("disabled","#59434B")])
        style.configure("Stop.TButton",foreground=COLORS["error"],padding=(10,10))
        style.configure("TEntry",padding=7,fieldbackground="#FFFFFF",foreground=COLORS["text"],
                        bordercolor=COLORS["line"], lightcolor=COLORS["line"],darkcolor=COLORS["line"])
        style.configure("TCombobox",padding=7,fieldbackground="#FFFFFF",foreground=COLORS["text"])
        style.map("TCombobox",fieldbackground=[("readonly","#FFFFFF")],foreground=[("readonly",COLORS["text"])])
        style.configure("TCheckbutton",background=COLORS["surface"],foreground=COLORS["text"])
        style.configure("TSpinbox",padding=6,fieldbackground="#FFFFFF",foreground=COLORS["text"])
        style.configure("Invalid.TSpinbox",foreground=COLORS["error"],fieldbackground="#FFF4F4")
        style.configure("GitHub.TButton",padding=(7,5),background=COLORS["bg"],borderwidth=0)
        style.map("GitHub.TButton",background=[("active","#E5E8ED")])

    def _layout(self):
        header=tk.Frame(self.root,bg=COLORS["surface"],padx=24,pady=17)
        header.pack(fill="x")
        title=tk.Frame(header,bg=COLORS["surface"]); title.pack(side="left")
        tk.Label(title,text="桃信助手",font=("Microsoft YaHei UI",20,"bold"),bg=COLORS["surface"],fg=COLORS["text"]).pack(anchor="w")
        tk.Label(header,text=f"日服 / 国服 / 繁中  ·  v{__version__}",bg=COLORS["soft"],fg=COLORS["accent"],padx=12,pady=8).pack(side="right")
        tk.Frame(self.root,height=1,bg=COLORS["line"]).pack(fill="x")
        self.main_footer=tk.Frame(self.root,bg=COLORS["bg"])
        self.main_footer.pack(side="bottom",fill="x",padx=20,pady=(0,8))
        github_mark=Image.open(resource_dir()/"assets/github-mark.png").convert("RGBA")
        github_mark.thumbnail((22,22),Image.Resampling.LANCZOS)
        self.github_icon=ImageTk.PhotoImage(github_mark)
        self.github_button=ttk.Button(self.main_footer,text="GitHub",image=self.github_icon,
                                     compound="left",style="GitHub.TButton",command=self.open_repository)
        self.github_button.pack(side="left")
        body=tk.Frame(self.root,bg=COLORS["bg"]); body.pack(fill="both",expand=True,padx=20,pady=20)
        body.columnconfigure(1,weight=1); body.rowconfigure(0,weight=1)
        left=ttk.Frame(body,padding=18); left.grid(row=0,column=0,sticky="nsew",padx=(0,16))
        left.configure(width=290)
        self.usage_button=ttk.Button(left,text="点击查看使用方法",command=self.show_usage)
        self.usage_button.pack(fill="x",pady=(0,8))
        ttk.Label(left,text="设备连接",style="Section.TLabel").pack(anchor="w",pady=(0,8))
        self.discover_button=ttk.Button(left,text="查找模拟器",command=self.discover)
        self.discover_button.pack(fill="x",pady=(0,6))
        ttk.Label(left,text="模拟器",style="Muted.TLabel").pack(anchor="w")
        self.device_combo=ttk.Combobox(left,textvariable=self.device_label,state="readonly",width=27)
        self.device_combo.pack(fill="x",pady=(4,6))
        self.device_combo.bind("<<ComboboxSelected>>",self.device_selected)
        ttk.Label(left,text="画面 / 应用",style="Muted.TLabel").pack(anchor="w")
        display_row=ttk.Frame(left); display_row.pack(fill="x",pady=(4,6))
        self.display_combo=ttk.Combobox(display_row,textvariable=self.display_label,state="disabled",width=22)
        self.display_combo.pack(side="left",fill="x",expand=True)
        self.display_combo.bind("<<ComboboxSelected>>",self.display_selected)
        self.refresh_display_button=ttk.Button(display_row,text="刷新",command=self.refresh_display_list,padding=(7,7))
        self.refresh_display_button.pack(side="left",padx=(6,0))
        self.settings_button=ttk.Button(left,text="手动连接 / ADB 设置",command=self.connection_settings)
        self.settings_button.pack(fill="x",pady=(2,8))
        ttk.Separator(left).pack(fill="x",pady=(0,8))
        ttk.Label(left,text="自动运行",style="Section.TLabel").pack(anchor="w",pady=(0,6))
        wait_row=ttk.Frame(left); wait_row.pack(fill="x",pady=(0,6))
        ttk.Label(wait_row,text="无后续消息等待（秒）",style="Muted.TLabel").pack(side="left")
        self.wait_spin=ttk.Spinbox(wait_row,from_=1,to=120,increment=.5,width=6,textvariable=self.idle_wait)
        self.wait_spin.pack(side="right",padx=(8,0))
        self.wait_spin.bind("<FocusOut>",self._commit_idle_wait)
        self.wait_spin.bind("<Return>",self._commit_idle_wait)
        self.preview_check=ttk.Checkbutton(left,text="仅预览，不发送触控",variable=self.preview_only)
        self.preview_check.pack(anchor="w",pady=(0,6))
        self.start_button=ttk.Button(left,text="开始处理未读",style="Primary.TButton",command=self.start)
        self.start_button.pack(fill="x")
        self.stop_button=ttk.Button(left,text="停止  ·  Esc",style="Stop.TButton",command=self.stop)
        self.stop_button.pack(fill="x",pady=(5,5))
        ttk.Separator(left).pack(fill="x",pady=8)
        self.inspect_button=ttk.Button(left,text="用录屏或截图检查识别",command=self.choose_file)
        self.inspect_button.pack(fill="x")
        ttk.Button(left,text="打开日志文件夹",command=self.open_logs).pack(fill="x",pady=(6,0))

        right=tk.Frame(body,bg=COLORS["bg"]); right.grid(row=0,column=1,sticky="nsew")
        right.columnconfigure(0,weight=1); right.rowconfigure(1,weight=1)
        top=tk.Frame(right,bg=COLORS["bg"]); top.grid(row=0,column=0,sticky="ew",pady=(0,9))
        tk.Label(top,text="识别预览",bg=COLORS["bg"],fg=COLORS["text"],font=("Microsoft YaHei UI",11,"bold")).pack(side="left")
        tk.Label(top,textvariable=self.scene,bg=COLORS["bg"],fg=COLORS["accent"]).pack(side="right")
        self.canvas=tk.Canvas(right,bg=COLORS["preview"],highlightthickness=0,height=330)
        self.canvas.grid(row=1,column=0,sticky="nsew")
        self.canvas.bind("<Configure>",lambda event:self._draw_preview())
        tk.Label(right,textvariable=self.preview_source,bg=COLORS["bg"],fg=COLORS["muted"],anchor="w").grid(row=2,column=0,sticky="ew",pady=(7,12))
        status_area=tk.Frame(right,bg=COLORS["surface"],padx=14,pady=11)
        status_area.grid(row=3,column=0,sticky="ew",pady=(0,12))
        self.status_label=tk.Label(status_area,textvariable=self.status,bg=COLORS["surface"],fg=COLORS["text"],
                                   font=("Microsoft YaHei UI",11,"bold"),anchor="w",justify="left",wraplength=620)
        self.status_label.pack(fill="x")
        tk.Label(status_area,textvariable=self.counter,bg=COLORS["surface"],fg=COLORS["muted"],anchor="w").pack(fill="x",pady=(6,0))
        tk.Label(right,text="运行记录",bg=COLORS["bg"],fg=COLORS["text"],font=("Microsoft YaHei UI",11,"bold"),anchor="w").grid(row=4,column=0,sticky="ew",pady=(0,7))
        log_frame=tk.Frame(right,bg=COLORS["surface"]); log_frame.grid(row=5,column=0,sticky="ew")
        self.log_text=tk.Text(log_frame,height=7,wrap="word",bg=COLORS["surface"],fg=COLORS["text"],
                              relief="flat",borderwidth=0,padx=12,pady=10,state="disabled",
                              font=("Microsoft YaHei UI",10),takefocus=True)
        self.log_text.pack(side="left",fill="both",expand=True)
        scrollbar=ttk.Scrollbar(log_frame,command=self.log_text.yview); scrollbar.pack(side="right",fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _log(self,message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end",f"{datetime.now():%H:%M:%S}  {message}\n")
        if int(self.log_text.index("end-1c").split(".")[0])>500:
            self.log_text.delete("1.0","100.0")
        self.log_text.see("end"); self.log_text.configure(state="disabled")

    def show_usage(self):
        if self.usage_window is not None and self.usage_window.winfo_exists():
            self.usage_window.lift()
            return
        window=tk.Toplevel(self.root)
        window.withdraw()
        self.usage_window=window
        window.title("使用方法")
        window.minsize(640,450)
        window.configure(bg=COLORS["surface"])
        window.transient(self.root)
        icon=resource_dir()/"assets/app.ico"
        if icon.is_file(): window.iconbitmap(str(icon))
        area=tk.Frame(window,bg=COLORS["surface"])
        area.pack(fill="both",expand=True,padx=28,pady=24)
        self.usage_text_widgets=[]
        self.usage_body_labels=[]
        for section_index,(heading,items) in enumerate((("使用方法：",USAGE_STEPS),("Tips：",USAGE_TIPS))):
            title=tk.Label(area,text=heading,font=("Microsoft YaHei UI",15,"bold"),anchor="w",
                           bg=COLORS["surface"],fg=COLORS["text"])
            title.pack(fill="x",pady=(18 if section_index else 0,10))
            self.usage_text_widgets.append(title)
            for item in items:
                number,body=item.split(".",1)
                row=tk.Frame(area,bg=COLORS["surface"])
                row.pack(fill="x",pady=(0,9))
                row.columnconfigure(1,weight=1)
                number_label=tk.Label(row,text=number+".",font=("Microsoft YaHei UI",11,"bold"),
                                      width=3,anchor="nw",bg=COLORS["surface"],fg=COLORS["accent"])
                number_label.grid(row=0,column=0,sticky="nw",padx=(0,8))
                body_label=tk.Label(row,text=body,font=("Microsoft YaHei UI",11),anchor="nw",justify="left",
                                    wraplength=640,bg=COLORS["surface"],fg=COLORS["text"])
                body_label.grid(row=0,column=1,sticky="ew")
                self.usage_text_widgets.extend((number_label,body_label))
                self.usage_body_labels.append(body_label)
        def rewrap(event):
            if event.widget is window:
                for label in self.usage_body_labels:
                    label.configure(wraplength=max(300,window.winfo_width()-106))
        window.bind("<Configure>",rewrap)
        self._center_popup(window,740,480)

    def _center_popup(self,window,width,height):
        self.root.update_idletasks()
        x=self.root.winfo_x()+(self.root.winfo_width()-width)//2
        y=self.root.winfo_y()+(self.root.winfo_height()-height)//2
        window.geometry(f"{width}x{height}{x:+d}{y:+d}")
        window.deiconify()
        window.lift()

    def open_repository(self):
        webbrowser.open(REPOSITORY_URL,new=2)

    def emit(self,event):
        if event.get("kind")=="frame": self.latest_frame=event
        else: self.events.put(event)

    def selected_serial(self):
        return next((d.serial for d in self.devices if d.label==self.device_label.get()),"")

    def selected_display(self):
        return next((item for item in self.display_targets if item.label==self.display_label.get()),None)

    def _idle_wait_changed(self,*_):
        try: self.options.set_idle_seconds(float(self.idle_wait.get()))
        except (ValueError,TypeError):
            self.wait_spin.configure(style="Invalid.TSpinbox")
            return
        self.wait_spin.configure(style="TSpinbox")
        if self.wait_save_timer is not None: self.root.after_cancel(self.wait_save_timer)
        self.wait_save_timer=self.root.after(400,self._persist_idle_wait)

    def _persist_idle_wait(self):
        self.wait_save_timer=None
        self._save_settings()
        self._log(f"无后续消息等待已设为 {self.options.idle_seconds:g} 秒，运行中实时生效。")

    def _commit_idle_wait(self,event=None):
        try: self.options.set_idle_seconds(float(self.idle_wait.get()))
        except (ValueError,TypeError):
            self.idle_wait.set(f"{self.options.idle_seconds:g}")
            self.status.set("等待时间应为 1–120 秒，已保留上一个有效值。")

    def _invalidate_preview(self):
        self.preview_service.invalidate()
        self.pending_device_preview=False
        self.latest_frame=None

    def device_selected(self,event=None):
        if self.busy: return
        self._invalidate_preview()
        serial=self.selected_serial()
        self.display_targets=[]
        self.display_label.set("")
        self.display_combo["values"]=[]
        self.preview_ready=False
        self._update_buttons()
        self.preview_image=None
        self._draw_preview()
        if not serial:
            self.preview_source.set("设备画面将在这里显示")
            self.scene.set("等待连接")
            return
        if ":" in serial: self.endpoint.set(serial)
        self.scene.set("正在读取设备预览")
        self.preview_source.set(f"设备预览 · {serial} · 读取中")
        self.status.set("正在读取所选设备画面…")
        self.preview_service.request(serial,self.adb_path.get())
        self._save_settings()

    def display_selected(self,event=None):
        if self.busy: return
        target=self.selected_display()
        if target is None: return
        self._request_display_preview(target)

    def refresh_display_list(self):
        if self.busy: return
        target=self.selected_display()
        if target is None: self.device_selected()
        else: self._request_display_preview(target,fallback_to_desktop=True)

    def _request_display_preview(self,target,fallback_to_desktop=False):
        self._invalidate_preview()
        self.preview_ready=False
        self.preview_image=None
        self._draw_preview()
        serial=self.selected_serial()
        self.scene.set("正在读取所选画面")
        self.preview_source.set(f"{target.label} · 读取中")
        self.status.set("正在读取所选应用画面…")
        self._update_buttons()
        self.preview_service.request(serial,self.adb_path.get(),target.logical_id,fallback_to_desktop=fallback_to_desktop)

    def _apply_device_preview(self,event):
        if (self.busy or event["serial"]!=self.selected_serial()
                or not self.preview_service.is_current(event["generation"])):
            return
        if event["kind"]=="device_preview_error":
            self.preview_ready=False
            self.status.set("无法读取所选设备的预览")
            self.scene.set("预览失败")
            self.preview_source.set(f"设备预览 · {event['serial']} · 读取失败")
            self._log(event["message"])
            self._update_buttons()
            return
        self.display_targets=event["targets"]
        self.display_combo["values"]=[item.label for item in self.display_targets]
        self.display_label.set(event["target"].label)
        self.preview_ready=True
        self.preview_image=event["image"]
        self.scene.set(event["scene"])
        self.status.set(event["message"])
        self.status_label.configure(fg=COLORS["text"])
        width,height=event["resolution"]
        self.preview_source.set(f"{event['target'].label}  |  {width} × {height}  |  预览于 {datetime.now():%H:%M:%S}")
        self._draw_preview()
        self._update_buttons()

    def _update_buttons(self):
        idle=not self.busy
        for button in (self.discover_button,self.settings_button,self.connect_button,self.browse_button,self.inspect_button,self.refresh_display_button):
            if button is not None and button.winfo_exists():
                button.configure(state="normal" if idle else "disabled")
        target=self.selected_display()
        can_start=bool(self.preview_ready and target and (self.preview_only.get() or can_automate(target.package)))
        self.start_button.configure(state="normal" if idle and self.selected_serial() and can_start else "disabled",
                                    text="开始持续预览" if self.preview_only.get() else "开始处理未读")
        self.stop_button.configure(state="normal" if self.busy else "disabled")
        self.preview_check.configure(state="normal" if idle else "disabled")
        self.device_combo.configure(state="readonly" if idle else "disabled")
        self.display_combo.configure(state="readonly" if idle and self.display_targets else "disabled")

    def _background(self, function):
        if self.busy: return
        self.busy=True; self.stop_event.clear(); self._update_buttons()
        def work():
            try: function()
            except Exception as exc:
                self.emit({"kind":"finished","outcome":"error","message":str(exc),"stats":{}})
            finally: self.emit({"kind":"idle"})
        self.worker=threading.Thread(target=work,daemon=True)
        self.worker.start()

    def discover(self):
        if self.busy: return
        self._invalidate_preview()
        custom=self.adb_path.get()
        self.status.set("正在查找已连接设备和常用本机端口…")
        def work():
            client=AdbClient(custom,stop=self.stop_event)
            devices=client.discover(lambda message:self.emit({"kind":"log","message":message}))
            self.emit({"kind":"devices","devices":devices})
        self._background(work)

    def connect(self):
        if self.busy: return
        self._invalidate_preview()
        custom,endpoint=self.adb_path.get(),self.endpoint.get()
        self.status.set("正在连接指定设备…")
        def work():
            client=AdbClient(custom,stop=self.stop_event)
            client.connect(endpoint)
            self.emit({"kind":"devices","devices":client.group_devices(client.devices()),"preferred":endpoint})
        self._background(work)

    def browse_adb(self):
        path=filedialog.askopenfilename(parent=self.root,title="选择 adb.exe",filetypes=[("ADB 程序","*.exe"),("所有文件","*.*")])
        if path: self.adb_path.set(path)

    def connection_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        window=tk.Toplevel(self.root)
        window.withdraw()
        window.title("手动连接与 ADB 设置")
        window.minsize(500,310)
        window.configure(bg=COLORS["surface"])
        window.transient(self.root)
        self.settings_window=window
        area=ttk.Frame(window,padding=22); area.pack(fill="both",expand=True)
        ttk.Label(area,text="ADB 程序",style="Section.TLabel").pack(anchor="w")
        path_row=ttk.Frame(area); path_row.pack(fill="x",pady=(8,6))
        ttk.Entry(path_row,textvariable=self.adb_path).pack(side="left",fill="x",expand=True)
        self.browse_button=ttk.Button(path_row,text="选择文件",command=self.browse_adb)
        self.browse_button.pack(side="left",padx=(8,0))
        ttk.Label(area,text="留空时使用随附或已安装的 ADB。",style="Muted.TLabel").pack(anchor="w")
        ttk.Label(area,text="模拟器连接地址",style="Section.TLabel").pack(anchor="w",pady=(23,7))
        endpoint_row=ttk.Frame(area); endpoint_row.pack(fill="x")
        ttk.Entry(endpoint_row,textvariable=self.endpoint).pack(side="left",fill="x",expand=True)
        self.connect_button=ttk.Button(endpoint_row,text="连接",command=self.connect)
        self.connect_button.pack(side="left",padx=(8,0))
        ttk.Label(area,text="请填写模拟器设置中显示的主机和端口，例如 127.0.0.1:16416。",
                  style="Muted.TLabel",wraplength=490).pack(anchor="w",pady=(8,0))
        ttk.Label(area,text="连接成功后，可回到主窗口开始运行。",style="Muted.TLabel").pack(anchor="w",pady=(17,0))
        self._center_popup(window,560,330)

    def start(self):
        if self.busy: return
        serial=self.selected_serial()
        target=self.selected_display()
        if not serial or target is None or not self.preview_ready: return
        if not self.preview_only.get() and not can_automate(target.package):
            self.status.set("请选择支持的游戏画面，或勾选仅预览。")
            return
        self._invalidate_preview()
        self._save_settings()
        custom,preview=self.adb_path.get(),self.preview_only.get()
        self.status.set("正在读取设备画面…")
        self.preview_source.set(target.label)
        def work():
            client=AdbClient(custom,serial,self.stop_event)
            # Reconnect a TCP endpoint if a previous adb server has gone away.
            if ":" in serial and not any(d.serial==serial and d.state=="device" for d in client.devices()):
                client.connect(serial)
            client.bind_display(target.logical_id,expected_package=target.package)
            Runner(client,self.emit,self.stop_event,preview_only=preview,options=self.options).run()
        self._background(work)

    def stop(self):
        if self.busy:
            self.stop_event.set()
            self.status.set("正在停止，后续触控已禁用…")
            self.stop_button.configure(state="disabled")

    def choose_file(self):
        path=filedialog.askopenfilename(parent=self.root,title="检查录屏或截图（不发送触控）",
                                       filetypes=[("录屏与截图","*.mp4 *.mkv *.avi *.png *.jpg *.jpeg"),("所有文件","*.*")])
        if path: self.inspect_file(Path(path))

    def inspect_file(self,path: Path):
        if self.busy: return
        self._invalidate_preview()
        self.preview_source.set(f"本地文件 · {path.name} · 不发送触控")
        self.status.set("正在进行离线识别…")
        def work():
            if path.suffix.lower() in (".png",".jpg",".jpeg"):
                frame,obs=inspect_image(path)
                self.emit({"kind":"frame","image":annotate(frame,obs),"scene":str(obs.scene),
                           "status":"截图识别完成 · 不发送触控","resolution":frame.original_size,"stats":{}})
                self.emit({"kind":"log","message":f"识别到：{obs.scene}；可见目标 {len(obs.targets)} 个。"})
            else:
                output=data_dir()/"replays"/datetime.now().strftime("%Y%m%d_%H%M%S")
                report=analyze_video(path,output,self.emit,self.stop_event)
                self.emit({"kind":"log","message":f"录屏识别完成：{report['samples']} 帧，发送触控 0 次。报告：{output}"})
            self.emit({"kind":"finished","outcome":"stopped","message":"离线识别完成，不发送触控。","stats":{}})
        self._background(work)

    def open_logs(self):
        directory=data_dir()/"logs"; directory.mkdir(parents=True,exist_ok=True)
        os.startfile(str(directory))

    def _poll(self):
        try:
            while True:
                event=self.events.get_nowait()
                kind=event.get("kind")
                if kind=="log": self._log(event["message"])
                elif kind in ("device_preview","device_preview_error"):
                    self._apply_device_preview(event)
                elif kind=="status": self.status.set(event["message"])
                elif kind=="devices":
                    available=[d for d in event["devices"] if d.state=="device"]
                    self.devices=available
                    self.device_combo["values"]=[d.label for d in available]
                    desired=event.get("preferred") or self.settings.get("serial")
                    selected=next((d for d in available if d.matches(desired)),available[0] if available else None)
                    self.device_label.set(selected.label if selected else "")
                    if selected:
                        self.status.set("已找到模拟器，正在读取画面列表")
                        connections=sum(1+len(d.aliases) for d in available)
                        self._log(f"已找到 {len(available)} 台模拟器（{connections} 个连接地址）；当前选择 {selected.serial}。")
                        if ":" in selected.serial: self.endpoint.set(selected.serial)
                        self.pending_device_preview=True
                    else:
                        self.status.set("未找到设备，请检查模拟器的 ADB 开关或填写端口")
                        self._log("未找到可用设备。模拟器需要允许本机 ADB 连接；可在其设置中查看端口。")
                    for d in event["devices"]:
                        if d.state!="device": self._log(f"设备 {d.serial} 状态：{d.state}")
                elif kind=="finished":
                    self.status.set(event["message"])
                    self._log(event["message"])
                    self.status_label.configure(fg=COLORS["error"] if event.get("outcome")=="error" else COLORS["text"])
                    if event.get("log_path"): self._log(f"本次日志：{event['log_path']}")
                    self._stats(event.get("stats",{}))
                elif kind=="idle":
                    self.busy=False; self.worker=None; self._update_buttons()
        except queue.Empty:
            pass
        frame=self.latest_frame
        if frame:
            self.latest_frame=None
            self.preview_image=frame["image"]
            self.scene.set(frame["scene"])
            if self.busy:
                self.status.set(frame["status"])
                self.status_label.configure(fg=COLORS["text"])
            self._stats(frame.get("stats",{}))
            resolution=frame.get("resolution")
            current=self.preview_source.get().split("  |  ")[0]
            if resolution: self.preview_source.set(f"{current}  |  {resolution[0]} × {resolution[1]}  |  更新于 {datetime.now():%H:%M:%S}")
            self._draw_preview()
        if self.pending_device_preview and not self.busy:
            self.pending_device_preview=False
            self.device_selected()
        self.root.after(80,self._poll)

    def _stats(self,stats):
        if stats:
            self.counter.set(f"回复确认 {stats.get('replies',0)}  ·  剧情完成 {stats.get('stories',0)}  ·  列表刷新 {stats.get('refreshes',0)}")

    def _draw_preview(self):
        self.canvas.delete("all")
        width,height=self.canvas.winfo_width(),self.canvas.winfo_height()
        if self.preview_image is None:
            self.canvas.create_text(width/2,height/2-12,text="选择画面后显示预览",fill="#F1F4F8",font=("Microsoft YaHei UI",14))
            self.canvas.create_text(width/2,height/2+20,text="也可以使用本地录屏检查识别",fill="#C5D0DF",font=("Microsoft YaHei UI",10))
            return
        image=Image.fromarray(cv2.cvtColor(self.preview_image,cv2.COLOR_BGR2RGB))
        image.thumbnail((max(1,width),max(1,height)),Image.Resampling.LANCZOS)
        self.image_reference=ImageTk.PhotoImage(image)
        self.canvas.create_image(width/2,height/2,image=self.image_reference,anchor="center")

    def close(self):
        self.stop_event.set()
        self.preview_service.close()
        if self.wait_save_timer is not None: self.root.after_cancel(self.wait_save_timer)
        self._save_settings()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
