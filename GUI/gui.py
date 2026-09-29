"""
Barnacle Cleaning Robot — Control GUI

Architecture:
  - Main thread (Tk)     : owns pygame, polls Xbox controller every 30 ms,
                           draws UI, holds the canonical state.
  - control_thread       : pure serial IO. Reads shared state, writes frames
                           to ESP32_1 at SEND_HZ, drains echoes from ESP32_2.
  - detector_thread      : runs YOLO barnacle detection on camera frames.

Run:
    pip install pygame-ce pyserial pillow ultralytics
    python gui.py
"""

import os, sys, time, json, queue, struct, ctypes, threading, traceback, tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

import pygame
import serial, serial.tools.list_ports
from PIL import Image, ImageDraw, ImageFont, ImageTk

# ── App identity ──
APP_NAME = "HullVanguard"
APP_VERSION = "1.0.0"
APP_AUTHOR = "WEIJIAN"
SETTINGS_VERSION = 1


def _user_data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~/.config")
    p = os.path.join(base, APP_NAME)
    os.makedirs(p, exist_ok=True)
    return p


def _app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


USER_DATA_DIR = _user_data_dir()
LOG_DIR = os.path.join(USER_DATA_DIR, "logs"); os.makedirs(LOG_DIR, exist_ok=True)
SNAPSHOT_DIR = os.path.join(USER_DATA_DIR, "snapshots"); os.makedirs(SNAPSHOT_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(USER_DATA_DIR, "settings.json")


def _find_ai_model() -> str:
    base = _app_base_dir()
    candidates = [
        os.path.join(base, "AI", "runs", "barnacle_detect_v2", "weights", "best.pt"),
        os.path.join(base, "AI", "runs", "barnacle_detect",    "weights", "best.pt"),
        os.path.join(base, "..", "AI", "runs", "barnacle_detect_v2", "weights", "best.pt"),
        os.path.join(base, "..", "AI", "runs", "barnacle_detect",    "weights", "best.pt"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return os.path.normpath(p)
    return os.path.normpath(candidates[0])


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(d: dict) -> None:
    try:
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except OSError:
        pass


# ── Protocol ──
FRAME_H1, FRAME_H2 = 0xAA, 0x55
CMD_DRIVE, CMD_DRUM = 0x01, 0x02
SEND_HZ = 50

# ── Xbox mapping ──
AXIS_LT, AXIS_RT = 4, 5
BTN_A, BTN_LB, BTN_RB, BTN_ESTOP = 0, 4, 5, 1


def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


def build_frame(cmd: int, payload: bytes) -> bytes:
    body = bytes([cmd, len(payload)]) + payload
    return bytes([FRAME_H1, FRAME_H2]) + body + bytes([crc8(body)])


def trigger_to_pct(v: float) -> int:
    # Released triggers idle at -1.0. Before SDL polls the device for the first
    # time, pygame reports 0.0, which would falsely read as 50% pressed and spin
    # the motors on connect. Real triggers always have analog noise, so an exact
    # 0.0 is the uninitialized state — treat it as released.
    if v == 0.0:
        return 0
    x = (v + 1.0) * 0.5
    return 0 if x < 0.05 else int(round(x * 100))


def list_esp32_ports():
    ports = list(serial.tools.list_ports.comports())
    kw = ("CP210", "CH340", "CH343", "Silicon Labs", "USB-SERIAL",
          "USB-Enhanced-SERIAL", "USB Serial Device", "USB JTAG",
          "Espressif", "ESP32")
    hit = []
    for p in ports:
        desc = ((p.description or "") + " " + (p.manufacturer or "")).lower()
        hid = (getattr(p, "hwid", "") or "").upper()
        if any(k.lower() in desc for k in kw) or "VID:PID=303A" in hid:
            hit.append(p.device)
    return hit or [p.device for p in ports]


# ── Shared state ──
@dataclass
class Bus:
    lt: int = 0; rt: int = 0
    lb: bool = False; rb: bool = False
    estop: bool = False
    left: int = 0; right: int = 0
    drum: bool = False
    connected: bool = False
    controller_name: str = ""
    last_echo_ts: float = 0.0
    last_i2c_ok_ts: float = 0.0
    cam_connected: bool = False
    last_jpeg: bytes = b""
    last_jpeg_ts: float = 0.0
    rendered_jpeg_ts: float = 0.0
    ai_detections: list = field(default_factory=list)
    ai_result_ts: float = 0.0
    log_queue: queue.Queue = field(default_factory=queue.Queue)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def log(self, msg: str):
        self.log_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ── Serial-IO thread ──
class IoThread(threading.Thread):
    def __init__(self, bus, port_name):
        super().__init__(daemon=True)
        self.bus, self.port_name = bus, port_name
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            ser = serial.Serial(self.port_name, 115200, timeout=0)
            time.sleep(1.5)
            self.bus.log(f"Opened {self.port_name}")
        except Exception as e:
            self.bus.log(f"SERIAL ERROR: {e}")
            with self.bus.lock:
                self.bus.connected = False
            return

        with self.bus.lock:
            self.bus.connected = True

        period = 1.0 / SEND_HZ
        while not self.stop_event.is_set():
            t0 = time.time()
            with self.bus.lock:
                left, right, drum = self.bus.left, self.bus.right, self.bus.drum
            try:
                ser.write(build_frame(CMD_DRIVE, struct.pack("bb", left, right)))
                ser.write(build_frame(CMD_DRUM, bytes([1 if drum else 0])))
                incoming = ser.read(256)
                if incoming:
                    now = time.time()
                    with self.bus.lock:
                        self.bus.last_echo_ts = now
                    for line in incoming.decode("utf-8", errors="replace").splitlines():
                        s = line.strip()
                        if not s:
                            continue
                        if s.startswith("STATUS "):
                            if "i2c=OK" in s:
                                with self.bus.lock:
                                    self.bus.last_i2c_ok_ts = now
                        else:
                            self.bus.log(f"<- {s}")
            except Exception as e:
                self.bus.log(f"IO ERROR: {e}")
                break
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)

        try:
            ser.write(build_frame(CMD_DRIVE, struct.pack("bb", 0, 0)))
            ser.write(build_frame(CMD_DRUM, bytes([0])))
            ser.close()
        except Exception:
            pass
        with self.bus.lock:
            self.bus.connected = False
        self.bus.log("Disconnected.")


# ── Camera thread ──
class CamThread(threading.Thread):
    MAGIC = bytes([0xA5, 0x5A, 0xF0, 0x0D])
    MAX_FRAME = 300_000

    def __init__(self, bus, port_name):
        super().__init__(daemon=True)
        self.bus, self.port_name = bus, port_name
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            ser = serial.Serial(self.port_name, 921600, timeout=0.05)
            time.sleep(1.5)
            self.bus.log(f"Camera opened on {self.port_name}")
        except Exception as e:
            self.bus.log(f"CAM SERIAL ERROR: {e}")
            return

        with self.bus.lock:
            self.bus.cam_connected = True

        buf = bytearray()
        while not self.stop_event.is_set():
            try:
                chunk = ser.read(16384)
            except Exception as e:
                self.bus.log(f"CAM IO ERROR: {e}")
                break
            if not chunk:
                continue
            buf.extend(chunk)

            while True:
                idx = buf.find(self.MAGIC)
                if idx < 0:
                    if len(buf) > 3:
                        del buf[:-3]
                    break
                if idx > 0:
                    del buf[:idx]
                if len(buf) < 8:
                    break
                length = int.from_bytes(bytes(buf[4:8]), "big")
                if length == 0 or length > self.MAX_FRAME:
                    del buf[:4]
                    continue
                if len(buf) < 8 + length:
                    break
                jpeg = bytes(buf[8:8 + length])
                del buf[:8 + length]
                if jpeg[:2] != b'\xff\xd8' or jpeg[-2:] != b'\xff\xd9':
                    continue
                with self.bus.lock:
                    self.bus.last_jpeg = jpeg
                    self.bus.last_jpeg_ts = time.time()

        try:
            ser.close()
        except Exception:
            pass
        with self.bus.lock:
            self.bus.cam_connected = False
        self.bus.log("Camera disconnected.")


# ── AI detection thread ──
AI_MODEL_PATH = _find_ai_model()


class DetectorThread(threading.Thread):
    def __init__(self, bus, model_path):
        super().__init__(daemon=True)
        self.bus = bus
        self.model_path = model_path
        self.stop_event = threading.Event()
        self._input_q = queue.Queue(maxsize=1)

    def stop(self):
        self.stop_event.set()

    def submit(self, pil_img):
        try:
            self._input_q.get_nowait()
        except queue.Empty:
            pass
        self._input_q.put(pil_img)

    def run(self):
        try:
            from ultralytics import YOLO
            model = YOLO(self.model_path)
            self.bus.log(f"AI model loaded: {os.path.basename(self.model_path)}")
        except Exception as e:
            self.bus.log(f"AI MODEL ERROR: {e}")
            return

        while not self.stop_event.is_set():
            try:
                img = self._input_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                results = model(img, verbose=False, conf=0.15, iou=0.45,
                                imgsz=960, max_det=1000, agnostic_nms=True)
                detections = []
                for r in results:
                    for box in r.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        conf = box.conf[0].item()
                        cls = int(box.cls[0].item())
                        name = r.names[cls]
                        detections.append((x1, y1, x2, y2, conf, name))
                with self.bus.lock:
                    self.bus.ai_detections = detections
                    self.bus.ai_result_ts = time.time()
            except Exception as e:
                self.bus.log(f"AI DETECT ERROR: {e}")


def draw_detections(img, detections):
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("consola.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    for x1, y1, x2, y2, conf, name in detections:
        draw.rectangle([x1, y1, x2, y2], outline="#00ffcc", width=2)
        label = f"{name} {conf:.0%}"
        lx, ly = x1, max(0, y1 - 18)
        tw = draw.textlength(label, font=font)
        draw.rectangle([lx, ly, lx + tw + 6, ly + 17], fill="#00ffcc")
        draw.text((lx + 3, ly + 1), label, fill="#000000", font=font)
    return img


# ── Palette ──
C = {
    "bg":    "#1e1e1e",
    "surf":  "#262626",
    "card":  "#2e2e2e",
    "edge":  "#3a3a3a",
    "input": "#1a1a1a",
    "log":   "#181818",
    "text":  "#e0e0e0",
    "dim":   "#808080",
    "hi":    "#17bebb",
    "ok":    "#28d17c",
    "warn":  "#e2b93b",
    "err":   "#ff4d4f",
    "off":   "#444444",
    "ai":    "#00ffcc",
}


# ── App ──
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.bus = Bus()
        self.io_thread = self.cam_thread = None
        self.detector_thread = None
        self.ai_enabled = False
        self.cam_photo = None
        self._showing_feed = False
        self._fps_window = []

        pygame.init(); pygame.joystick.init()
        self.joy = None
        self.last_a = self.drum_state = False
        self.keys_held = set()

        self.settings = load_settings()
        z = self.settings.get("zoom_pct", 100)
        self.zoom_pct = z if isinstance(z, int) and 50 <= z <= 200 else 100

        root.title(f"{APP_NAME} — Barnacle Cleaning Robot")
        root.minsize(980, 560)
        root.configure(bg=C["bg"])
        geom = self.settings.get("window_geometry")
        if isinstance(geom, str) and "x" in geom:
            try:
                root.geometry(geom)
            except tk.TclError:
                root.state("zoomed")
        else:
            root.state("zoomed")

        self._apply_styles()
        self._build_ui()
        self.root.after(100, self._apply_windows_chrome)

        root.bind("<KeyPress>", self._on_key_press)
        root.bind("<KeyRelease>", self._on_key_release)
        root.bind("<Control-MouseWheel>", self._on_ctrl_scroll)
        root.bind("<F12>", self._probe_controller)   # F12 = probe controller axes/buttons
        root.focus_set()

        self.refresh_ports()
        self.detect_joystick()
        self.bus.log("GUI ready.  Plug in ESP32 + controller, then Connect.")
        self.bus.log("Keys: ↑↓ left side · WS right side · Enter drum · Esc E-stop")
        self.root.after(30, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Zoom helpers ──

    def s(self, v):
        return max(1, int(round(v * self.zoom_pct / 100)))

    def set_zoom(self, pct):
        self.zoom_pct = max(50, min(200, pct))
        self.view_menu.entryconfigure(self._zoom_idx, label=f"  {self.zoom_pct}%")
        self._apply_styles()
        for w in self._tk_widgets:
            w.configure(font=("Segoe UI", self.s(9)))
        for d in self._dots:
            d.configure(font=("Segoe UI", self.s(10)))
        self.log_box.configure(font=("Consolas", self.s(9)), padx=self.s(6), pady=self.s(4))
        self._center_placeholder()

    def zoom_in(self):
        self.set_zoom(self.zoom_pct + 1)

    def zoom_out(self):
        self.set_zoom(self.zoom_pct - 1)

    def zoom_reset(self):
        self.set_zoom(100)

    # ── Styles ──

    def _apply_styles(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass

        sz = self.s
        st.configure(".", font=("Segoe UI", sz(10)), background=C["bg"], foreground=C["text"])

        for name, bg in [("Shell.TFrame", C["bg"]), ("Bar.TFrame", C["surf"]),
                         ("Panel.TFrame", C["surf"]), ("Card.TFrame", C["card"]),
                         ("Log.TFrame", C["log"]), ("Sep.TFrame", C["edge"])]:
            st.configure(name, background=bg)

        st.configure("Title.TLabel", background=C["surf"], foreground=C["text"],
                     font=("Segoe UI Semibold", sz(14)))
        st.configure("Section.TLabel", background=C["surf"], foreground=C["text"],
                     font=("Segoe UI Semibold", sz(11)))
        st.configure("Eye.TLabel", background=C["surf"], foreground=C["dim"],
                     font=("Segoe UI Semibold", sz(8)))
        st.configure("EyeCard.TLabel", background=C["card"], foreground=C["dim"],
                     font=("Segoe UI Semibold", sz(8)))
        st.configure("Dim.TLabel", background=C["surf"], foreground=C["dim"])
        st.configure("Body.TLabel", background=C["card"], foreground=C["text"])
        st.configure("Val.TLabel", background=C["card"], foreground=C["text"],
                     font=("Consolas", sz(10)))
        st.configure("Metric.TLabel", background=C["surf"], foreground=C["text"],
                     font=("Consolas", sz(16), "bold"))
        st.configure("Mono.TLabel", background=C["card"], foreground=C["text"],
                     font=("Consolas", sz(9)))
        st.configure("AboutVal.TLabel", background=C["surf"], foreground=C["text"],
                     font=("Segoe UI", sz(11)))

        pad_badge = (sz(7), sz(3))
        st.configure("Off.TLabel", background=C["off"], foreground="#b0b0b0",
                     padding=pad_badge, font=("Segoe UI Semibold", sz(8)))
        st.configure("Live.TLabel", background="#143028", foreground="#a0f0c0",
                     padding=pad_badge, font=("Segoe UI Semibold", sz(8)))

        pad_ind = (sz(6), sz(4))
        st.configure("IndOff.TLabel", background=C["off"], foreground="#b0b0b0",
                     padding=pad_ind, font=("Segoe UI Semibold", sz(9)))
        st.configure("IndOn.TLabel", background="#0e5b44", foreground="#d9ffec",
                     padding=pad_ind, font=("Segoe UI Semibold", sz(9)))
        st.configure("IndOK.TLabel", background="#0e5b44", foreground="#d9ffec",
                     padding=pad_ind, font=("Segoe UI Semibold", sz(9)))
        st.configure("IndDanger.TLabel", background="#7f1d1d", foreground="#ffe4e4",
                     padding=pad_ind, font=("Segoe UI Semibold", sz(9)))

        st.configure("TButton", padding=(sz(8), sz(4)), background="#3a3a3a",
                     foreground=C["text"], borderwidth=0)
        st.map("TButton",
               background=[("active", "#484848"), ("disabled", "#2a2a2a")],
               foreground=[("disabled", "#6f7b89")])
        st.configure("Accent.TButton", background="#0b6b67", foreground="#effffd")
        st.map("Accent.TButton",
               background=[("active", "#11837d"), ("disabled", "#2a2a2a")])

        st.configure("Dark.TCombobox", fieldbackground=C["input"], background="#3a3a3a",
                     foreground=C["text"], arrowcolor=C["text"],
                     bordercolor=C["edge"], lightcolor=C["edge"],
                     darkcolor=C["edge"], insertcolor=C["text"])
        st.map("Dark.TCombobox",
               fieldbackground=[("readonly", "focus", C["input"]), ("readonly", C["input"])],
               selectbackground=[("readonly", C["input"])],
               selectforeground=[("readonly", C["text"])],
               foreground=[("readonly", C["text"])],
               background=[("active", "#484848"), ("pressed", "#484848"),
                           ("readonly", "#3a3a3a"), ("disabled", "#2a2a2a")],
               arrowcolor=[("disabled", "#6f7b89")])

        self.root.option_add("*TCombobox*Listbox.background", C["input"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#0e7a7a")
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#fff")
        for k, v in [("background", C["surf"]), ("foreground", C["text"]),
                     ("activeBackground", "#3a3a3a"), ("activeForeground", "#fff")]:
            self.root.option_add(f"*Menu.{k}", v)

        st.configure("Dark.Vertical.TScrollbar", background="#3a3a3a",
                     troughcolor=C["log"], bordercolor=C["log"],
                     arrowcolor=C["dim"], gripcount=0, relief=tk.FLAT)
        st.map("Dark.Vertical.TScrollbar",
               background=[("active", "#484848"), ("pressed", "#555")])

        st.configure("Drive.Horizontal.TProgressbar", troughcolor=C["input"],
                     background=C["hi"], bordercolor=C["input"],
                     lightcolor=C["hi"], darkcolor=C["hi"])

        st.configure("TSeparator", background=C["edge"])

    # ── UI build ──

    def _build_ui(self):
        mc = {"bg": C["surf"], "fg": C["text"], "activebackground": "#3a3a3a",
              "activeforeground": "#fff", "relief": tk.FLAT, "borderwidth": 0}
        self._tk_widgets = []
        self._dots = []

        shell = ttk.Frame(self.root, style="Shell.TFrame", padding=4)
        shell.pack(fill=tk.BOTH, expand=True)

        # ── Top bar: menus + title + status ──
        bar = ttk.Frame(shell, style="Bar.TFrame", padding=(8, 4))
        bar.pack(fill=tk.X)
        bar.columnconfigure(1, weight=1)

        menu_frame = ttk.Frame(bar, style="Bar.TFrame")
        menu_frame.grid(row=0, column=0, sticky="w")

        view_btn = tk.Menubutton(menu_frame, text="View", bg=C["surf"], fg=C["text"],
                                 activebackground="#3a3a3a", activeforeground="#fff",
                                 relief=tk.FLAT, padx=7, pady=2, font=("Segoe UI", self.s(9)))
        self.view_menu = tk.Menu(view_btn, tearoff=False, **mc)
        self.view_menu.add_command(label="Zoom In", accelerator="Ctrl+=", command=self.zoom_in)
        self.view_menu.add_command(label="Zoom Out", accelerator="Ctrl+−", command=self.zoom_out)
        self.view_menu.add_command(label="Reset Zoom", accelerator="Ctrl+0", command=self.zoom_reset)
        self.view_menu.add_separator()
        self.view_menu.add_command(label="  100%", state="disabled")
        self._zoom_idx = self.view_menu.index(tk.END)
        view_btn.configure(menu=self.view_menu)
        view_btn.pack(side=tk.LEFT)
        self._tk_widgets.append(view_btn)

        help_btn = tk.Menubutton(menu_frame, text="Help", bg=C["surf"], fg=C["text"],
                                 activebackground="#3a3a3a", activeforeground="#fff",
                                 relief=tk.FLAT, padx=7, pady=2, font=("Segoe UI", self.s(9)))
        help_menu = tk.Menu(help_btn, tearoff=False, **mc)
        help_menu.add_command(label="About", command=self._show_about)
        help_btn.configure(menu=help_menu)
        help_btn.pack(side=tk.LEFT, padx=(4, 0))
        self._tk_widgets.append(help_btn)

        ttk.Label(bar, text="Barnacle Cleaning Robot", style="Title.TLabel"
                  ).grid(row=0, column=1, sticky="w", padx=(16, 0))

        status_box = ttk.Frame(bar, style="Bar.TFrame")
        status_box.grid(row=0, column=2, sticky="e")
        self.cam_fps_lbl = ttk.Label(status_box, text="", style="Dim.TLabel")
        self.cam_fps_lbl.pack(side=tk.RIGHT, padx=(6, 0))
        self.cam_status_lbl = ttk.Label(status_box, text="CAM OFF", style="Off.TLabel")
        self.cam_status_lbl.pack(side=tk.RIGHT, padx=(4, 0))
        self.status_lbl = ttk.Label(status_box, text="OFFLINE", style="Off.TLabel")
        self.status_lbl.pack(side=tk.RIGHT)

        # ── Connection rail ──
        rail = ttk.Frame(shell, style="Panel.TFrame", padding=(6, 4))
        rail.pack(fill=tk.X, pady=(3, 3))
        for i in range(3):
            rail.columnconfigure(i, weight=1)

        def _port_group(parent, col, label, padx):
            f = ttk.Frame(parent, style="Panel.TFrame")
            f.grid(row=0, column=col, sticky="ew", padx=padx)
            r = ttk.Frame(f, style="Panel.TFrame")
            r.pack(fill=tk.X)
            ttk.Label(r, text=label, style="Eye.TLabel").pack(side=tk.LEFT, padx=(0, 5))
            var = tk.StringVar()
            box = ttk.Combobox(r, textvariable=var, width=11, state="readonly",
                               style="Dark.TCombobox")
            box.pack(side=tk.LEFT, fill=tk.X, expand=True)
            return r, var, box

        cr, self.port_var, self.port_box = _port_group(rail, 0, "CONTROL", (0, 4))
        self.connect_btn = ttk.Button(cr, text="Connect", style="Accent.TButton",
                                      command=self.toggle_connect)
        self.connect_btn.pack(side=tk.LEFT, padx=(5, 0))

        camr, self.cam_port_var, self.cam_port_box = _port_group(rail, 1, "CAMERA", 4)
        self.cam_connect_btn = ttk.Button(camr, text="Connect Cam", command=self.toggle_cam)
        self.cam_connect_btn.pack(side=tk.LEFT, padx=(5, 0))

        bf = ttk.Frame(rail, style="Panel.TFrame")
        bf.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        br = ttk.Frame(bf, style="Panel.TFrame")
        br.pack(fill=tk.X)
        ttk.Label(br, text="BOARDS", style="Eye.TLabel").pack(side=tk.LEFT, padx=(0, 5))
        self.dot_1 = self._dot(br, "ESP32_1")
        self.dot_2 = self._dot(br, "ESP32_2")
        self.dot_3 = self._dot(br, "ESP32_3")
        ttk.Button(br, text="Refresh", command=self.refresh_ports).pack(side=tk.RIGHT)

        # ── Main split (vertical: upper panels | log) ──
        sash_kw = dict(bg=C["edge"], sashwidth=5, sashrelief=tk.FLAT,
                       borderwidth=0, sashpad=0, opaqueresize=True)
        vsplit = tk.PanedWindow(shell, orient=tk.VERTICAL, **sash_kw)
        vsplit.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

        # ── Horizontal split (camera | telemetry) ──
        hsplit = tk.PanedWindow(vsplit, orient=tk.HORIZONTAL, **sash_kw)

        # Camera
        cam_frame = ttk.Frame(hsplit, style="Panel.TFrame", padding=5)
        cam_head = ttk.Frame(cam_frame, style="Panel.TFrame")
        cam_head.pack(fill=tk.X, pady=(0, 3))
        ttk.Label(cam_head, text="Live Camera", style="Section.TLabel").pack(side=tk.LEFT)
        self.snap_btn = ttk.Button(cam_head, text="Snapshot", command=self._snapshot,
                                   state=tk.DISABLED)
        self.snap_btn.pack(side=tk.RIGHT)
        self.snap_lbl = ttk.Label(cam_head, text="", style="Dim.TLabel")
        self.snap_lbl.pack(side=tk.RIGHT, padx=(0, 6))
        self.ai_btn = ttk.Button(cam_head, text="AI OFF", command=self.toggle_ai)
        self.ai_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.ai_count_lbl = ttk.Label(cam_head, text="", style="Dim.TLabel")
        self.ai_count_lbl.pack(side=tk.RIGHT, padx=(0, 4))

        self.cam_canvas = tk.Canvas(cam_frame, bg=C["log"], highlightthickness=1,
                                    highlightbackground=C["edge"])
        self.cam_canvas.pack(fill=tk.BOTH, expand=True)
        self.cam_canvas.bind("<Configure>", lambda e: self._center_placeholder())

        # Telemetry
        tele = ttk.Frame(hsplit, style="Panel.TFrame", padding=6)
        tele.columnconfigure(0, weight=1)
        tele.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(tele, text="Telemetry", style="Section.TLabel"
                  ).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1

        ttk.Separator(tele).grid(row=row, column=0, columnspan=2, sticky="ew", pady=4); row += 1

        ttk.Label(tele, text="CONTROLLER", style="Eye.TLabel"
                  ).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        self.ctrl_lbl = ttk.Label(tele, text="—", style="Dim.TLabel")
        self.ctrl_lbl.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2)); row += 1

        ttk.Separator(tele).grid(row=row, column=0, columnspan=2, sticky="ew", pady=4); row += 1

        ttk.Label(tele, text="TRIGGERS", style="Eye.TLabel"
                  ).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1

        trig = ttk.Frame(tele, style="Card.TFrame", padding=4)
        trig.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(2, 0)); row += 1
        trig.columnconfigure(1, weight=1)
        ttk.Label(trig, text="LT", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=2)
        self.lt_bar = ttk.Progressbar(trig, maximum=100, style="Drive.Horizontal.TProgressbar")
        self.lt_bar.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self.lt_val = ttk.Label(trig, text="  0", style="Mono.TLabel")
        self.lt_val.grid(row=0, column=2, sticky="e", pady=2)
        ttk.Label(trig, text="RT", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=2)
        self.rt_bar = ttk.Progressbar(trig, maximum=100, style="Drive.Horizontal.TProgressbar")
        self.rt_bar.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.rt_val = ttk.Label(trig, text="  0", style="Mono.TLabel")
        self.rt_val.grid(row=1, column=2, sticky="e", pady=2)

        bump = ttk.Frame(trig, style="Card.TFrame")
        bump.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.lb_ind = ttk.Label(bump, text="LB", style="IndOff.TLabel", width=8, anchor="center")
        self.lb_ind.pack(side=tk.LEFT)
        self.rb_ind = ttk.Label(bump, text="RB", style="IndOff.TLabel", width=8, anchor="center")
        self.rb_ind.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(tele).grid(row=row, column=0, columnspan=2, sticky="ew", pady=4); row += 1

        ttk.Label(tele, text="LEFT DRIVE", style="Eye.TLabel"
                  ).grid(row=row, column=0, sticky="w")
        ttk.Label(tele, text="RIGHT DRIVE", style="Eye.TLabel"
                  ).grid(row=row, column=1, sticky="w", padx=(6, 0)); row += 1
        self.left_val = ttk.Label(tele, text="+000", style="Metric.TLabel")
        self.left_val.grid(row=row, column=0, sticky="w", pady=(0, 2))
        self.right_val = ttk.Label(tele, text="+000", style="Metric.TLabel")
        self.right_val.grid(row=row, column=1, sticky="w", padx=(6, 0), pady=(0, 2)); row += 1

        ttk.Separator(tele).grid(row=row, column=0, columnspan=2, sticky="ew", pady=4); row += 1

        ttk.Label(tele, text="DRUM", style="Eye.TLabel"
                  ).grid(row=row, column=0, sticky="w")
        ttk.Label(tele, text="E-STOP", style="Eye.TLabel"
                  ).grid(row=row, column=1, sticky="w", padx=(6, 0)); row += 1
        self.drum_ind = ttk.Label(tele, text="OFF", style="IndOff.TLabel", anchor="center")
        self.drum_ind.grid(row=row, column=0, sticky="ew", pady=(3, 0))
        self.estop_ind = ttk.Label(tele, text="OK", style="IndOK.TLabel", anchor="center")
        self.estop_ind.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=(3, 0)); row += 1

        ttk.Separator(tele).grid(row=row, column=0, columnspan=2, sticky="ew", pady=4); row += 1

        ttk.Label(tele, text="AI DETECTION", style="Eye.TLabel"
                  ).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        ai_card = ttk.Frame(tele, style="Card.TFrame", padding=6)
        ai_card.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(2, 0)); row += 1
        ai_card.columnconfigure(1, weight=1)
        ttk.Label(ai_card, text="Status", style="Body.TLabel").grid(row=0, column=0, sticky="w")
        self.ai_status_lbl = ttk.Label(ai_card, text="OFF", style="Mono.TLabel")
        self.ai_status_lbl.grid(row=0, column=1, sticky="e")
        ttk.Label(ai_card, text="Barnacles", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.ai_barnacle_count = ttk.Label(ai_card, text="—", style="Mono.TLabel")
        self.ai_barnacle_count.grid(row=1, column=1, sticky="e", pady=(3, 0))
        ttk.Label(ai_card, text="Confidence", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(3, 0))
        self.ai_conf_lbl = ttk.Label(ai_card, text="—", style="Mono.TLabel")
        self.ai_conf_lbl.grid(row=2, column=1, sticky="e", pady=(3, 0))

        hsplit.add(cam_frame, stretch="always", minsize=300)
        hsplit.add(tele, stretch="always", minsize=200)

        # Log
        log_frame = ttk.Frame(vsplit, style="Panel.TFrame", padding=6)
        ttk.Label(log_frame, text="Event Log", style="Section.TLabel"
                  ).pack(anchor="w", pady=(0, 3))
        log_body = ttk.Frame(log_frame, style="Log.TFrame")
        log_body.pack(fill=tk.BOTH, expand=True)
        self.log_box = tk.Text(log_body, height=4, state="disabled",
                               bg=C["log"], fg="#ccc", insertbackground="#ccc",
                               selectbackground="#0e7a7a", selectforeground="#fff",
                               relief=tk.FLAT, borderwidth=0,
                               font=("Consolas", self.s(9)), padx=self.s(6), pady=self.s(4))
        scr = ttk.Scrollbar(log_body, orient=tk.VERTICAL, command=self.log_box.yview,
                            style="Dark.Vertical.TScrollbar")
        self.log_box.configure(yscrollcommand=scr.set)
        self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr.pack(side=tk.RIGHT, fill=tk.Y)

        vsplit.add(hsplit, stretch="always", minsize=250)
        vsplit.add(log_frame, stretch="always", minsize=60)

    def _dot(self, parent, label):
        d = tk.Label(parent, text="●", fg=C["off"], bg=C["surf"],
                     font=("Segoe UI", self.s(10)))
        d.pack(side=tk.LEFT)
        self._dots.append(d)
        ttk.Label(parent, text=label, style="Dim.TLabel").pack(side=tk.LEFT, padx=(1, 6))
        return d

    def _center_placeholder(self):
        if self._showing_feed:
            return
        self.cam_canvas.delete("placeholder")
        w = self.cam_canvas.winfo_width()
        h = self.cam_canvas.winfo_height()
        if w > 1 and h > 1:
            self.cam_canvas.create_text(
                w // 2, h // 2, text="CAMERA  FEED  STANDBY",
                fill="#555", font=("Consolas", self.s(14)), tags=("placeholder",))

    # ── Windows dark title bar ──

    def _apply_windows_chrome(self, window=None):
        if sys.platform != "win32":
            return
        target = window or self.root
        try:
            target.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(target.winfo_id())
            v = ctypes.c_int(1)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            for attr, color in [(35, 0x1E1E1E), (36, 0xE0E0E0)]:
                c = ctypes.c_int(color)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(c), ctypes.sizeof(c))
        except Exception:
            pass

    # ── About ──

    def _show_about(self):
        w = tk.Toplevel(self.root)
        w.title("About")
        w.configure(bg=C["bg"])
        w.resizable(False, False)
        w.transient(self.root)
        w.grab_set()

        box = ttk.Frame(w, style="Panel.TFrame", padding=20)
        box.pack(fill=tk.BOTH, expand=True)

        cv = tk.Canvas(box, width=76, height=90, bg=C["surf"], highlightthickness=0)
        cv.pack(pady=(0, 10))
        cx, cy, r = 38, 38, 30
        cv.create_oval(cx-r, cy-r, cx+r, cy+r, fill="#0b6b67", outline=C["hi"], width=2)
        cv.create_arc(cx-r+10, cy-r+10, cx+r-10, cy+r-10, start=205, extent=250,
                      style=tk.ARC, outline="#d9ffec", width=4)
        cv.create_line(cx-10, cy+8, cx+4, cy-12, cx+14, cy+10,
                       fill="#d9ffec", width=4, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        cv.create_text(cx, cy+r+8, text="BCR", fill=C["dim"], font=("Segoe UI Semibold", 8))

        ttk.Label(box, text=APP_NAME, style="Title.TLabel").pack()
        ttk.Label(box, text="Barnacle Cleaning Robot — Control Deck", style="Dim.TLabel").pack(pady=(2, 12))
        ttk.Label(box, text=f"Version {APP_VERSION}", style="AboutVal.TLabel").pack()
        ttk.Label(box, text=f"Authority: {APP_AUTHOR}", style="AboutVal.TLabel").pack(pady=(4, 14))
        ttk.Button(box, text="Close", command=w.destroy).pack()

        w.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - w.winfo_height()) // 2
        w.geometry(f"+{x}+{y}")
        self._apply_windows_chrome(w)

    # ── Keyboard ──

    KEY_L_FWD = "Up"; KEY_L_BACK = "Down"
    KEY_R_FWD = "w";  KEY_R_BACK = "s"
    KEY_ESTOP = "Escape"; KEY_DRUM = "Return"

    def _on_key_press(self, ev):
        ks = ev.keysym

        # Ctrl+zoom
        if ev.state & 0x4:
            if ks in ("plus", "equal", "KP_Add"):
                self.zoom_in(); return
            if ks in ("minus", "underscore", "KP_Subtract"):
                self.zoom_out(); return
            if ks == "0":
                self.zoom_reset(); return

        if len(ks) == 1:
            ks = ks.lower()
        was_held = ks in self.keys_held
        self.keys_held.add(ks)

        if ks == self.KEY_DRUM and not was_held:
            with self.bus.lock:
                conn = self.bus.connected
            if conn:
                self.drum_state = not self.drum_state
                self.bus.log(f"Drum {'ON' if self.drum_state else 'OFF'} (keyboard)")

    def _on_key_release(self, ev):
        ks = ev.keysym
        if len(ks) == 1:
            ks = ks.lower()
        self.keys_held.discard(ks)

    def _on_ctrl_scroll(self, ev):
        if ev.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def _kb_drive(self):
        l = (100 if self.KEY_L_FWD in self.keys_held else 0) - \
            (100 if self.KEY_L_BACK in self.keys_held else 0)
        r = (100 if self.KEY_R_FWD in self.keys_held else 0) - \
            (100 if self.KEY_R_BACK in self.keys_held else 0)
        return l, r

    # ── Snapshot ──

    def _snapshot(self):
        with self.bus.lock:
            jpeg = self.bus.last_jpeg
        if not jpeg:
            self.bus.log("No camera frame yet."); return
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        name = f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        path = os.path.join(SNAPSHOT_DIR, name)
        try:
            with open(path, "wb") as f:
                f.write(jpeg)
            self.bus.log(f"Snapshot: {path}")
            self.snap_lbl.config(text=f"saved {name}", foreground=C["ok"])
        except Exception as e:
            self.bus.log(f"Snapshot failed: {e}")

    # ── Controller ──

    def detect_joystick(self):
        try:
            pygame.joystick.quit(); pygame.joystick.init()
        except Exception:
            pass
        if pygame.joystick.get_count() > 0:
            self.joy = pygame.joystick.Joystick(0)
            self.joy.init()
            # Let SDL read initial device state so triggers report -1.0 (released),
            # not the placeholder 0.0 that would look like half-pressed.
            for _ in range(5):
                pygame.event.pump()
                time.sleep(0.01)
            with self.bus.lock:
                self.bus.controller_name = self.joy.get_name()
            self.bus.log(f"Controller: {self.joy.get_name()}  "
                         f"({self.joy.get_numaxes()} axes, {self.joy.get_numbuttons()} buttons)")
            self.bus.log(f"Trigger mapping: AXIS_LT={AXIS_LT}, AXIS_RT={AXIS_RT}. "
                         f"Press F12 with a trigger held to verify.")
        else:
            self.joy = None
            with self.bus.lock:
                self.bus.controller_name = ""

    def _probe_controller(self, _event=None):
        """Log every axis and button value — diagnostic for controller mapping.
        Bound to F12. Press while holding a trigger or button to identify
        which AXIS_LT / AXIS_RT / BTN_* index it actually corresponds to."""
        if self.joy is None:
            self.bus.log("PROBE: no joystick detected.")
            return
        try:
            pygame.event.pump()
            n_ax = self.joy.get_numaxes()
            n_bt = self.joy.get_numbuttons()
            axes = " ".join(f"a{i}={self.joy.get_axis(i):+.2f}" for i in range(n_ax))
            btns = " ".join(f"b{i}={int(self.joy.get_button(i))}" for i in range(n_bt))
            self.bus.log(f"PROBE axes: {axes}")
            self.bus.log(f"PROBE btns: {btns}")
        except pygame.error as e:
            self.bus.log(f"PROBE error: {e}")

    def _poll_controller(self):
        with self.bus.lock:
            conn = self.bus.connected

        if not conn:
            self.drum_state = self.last_a = False
            with self.bus.lock:
                self.bus.lt = self.bus.rt = 0
                self.bus.lb = self.bus.rb = False
                self.bus.estop = False
                self.bus.left = self.bus.right = 0
                self.bus.drum = False
            if self.joy is None and pygame.joystick.get_count() > 0:
                self.detect_joystick()
            return

        lt = rt = 0; lb = rb = a = estop = False
        if self.joy is not None:
            pygame.event.pump()
            try:
                lt = trigger_to_pct(self.joy.get_axis(AXIS_LT))
                rt = trigger_to_pct(self.joy.get_axis(AXIS_RT))
                lb = bool(self.joy.get_button(BTN_LB))
                rb = bool(self.joy.get_button(BTN_RB))
                a = bool(self.joy.get_button(BTN_A))
                estop = bool(self.joy.get_button(BTN_ESTOP))
            except pygame.error:
                self.bus.log("Controller disconnected.")
                self.joy = None
                with self.bus.lock:
                    self.bus.controller_name = ""
        elif pygame.joystick.get_count() > 0:
            self.detect_joystick()

        if a and not self.last_a and not estop:
            self.drum_state = not self.drum_state
            self.bus.log(f"Drum {'ON' if self.drum_state else 'OFF'}")
        self.last_a = a

        cl = max(-100, min(100, lt - (100 if lb else 0)))
        cr = max(-100, min(100, rt - (100 if rb else 0)))
        kl, kr = self._kb_drive()
        left = cl if cl else kl
        right = cr if cr else kr

        kb_estop = self.KEY_ESTOP in self.keys_held
        estop = estop or kb_estop
        if estop:
            left = right = 0; self.drum_state = False

        with self.bus.lock:
            self.bus.lt, self.bus.rt = lt, rt
            self.bus.lb, self.bus.rb = lb, rb
            self.bus.estop = estop
            self.bus.left, self.bus.right = left, right
            self.bus.drum = self.drum_state

    # ── Connection actions ──

    def refresh_ports(self):
        ports = list_esp32_ports()
        self.port_box["values"] = ports
        self.cam_port_box["values"] = ports

        saved_ctrl = self.settings.get("control_port", "")
        saved_cam = self.settings.get("camera_port", "")
        if not self.port_var.get() and saved_ctrl in ports:
            self.port_var.set(saved_ctrl)
        if not self.cam_port_var.get() and saved_cam in ports and saved_cam != self.port_var.get():
            self.cam_port_var.set(saved_cam)

        if ports and not self.port_var.get():
            self.port_var.set(ports[0])
        if len(ports) >= 2 and not self.cam_port_var.get():
            for p in ports:
                if p != self.port_var.get():
                    self.cam_port_var.set(p); break

    def toggle_connect(self):
        if self.io_thread and self.io_thread.is_alive():
            self.io_thread.stop(); self.io_thread = None
            self.connect_btn.config(text="Connect")
        else:
            port = self.port_var.get()
            if not port:
                self.bus.log("Pick a COM port first."); return
            self.io_thread = IoThread(self.bus, port)
            self.io_thread.start()
            self.connect_btn.config(text="Disconnect")

    def toggle_cam(self):
        if self.cam_thread and self.cam_thread.is_alive():
            self.cam_thread.stop(); self.cam_thread = None
            self.cam_connect_btn.config(text="Connect Cam")
            self._showing_feed = False
            self.cam_canvas.delete("all")
            self.cam_photo = None
            self._center_placeholder()
        else:
            port = self.cam_port_var.get()
            if not port:
                self.bus.log("Pick a camera COM port first."); return
            if port == self.port_var.get() and self.io_thread and self.io_thread.is_alive():
                self.bus.log("Camera port can't be the same as the active control port."); return
            self.cam_thread = CamThread(self.bus, port)
            self.cam_thread.start()
            self.cam_connect_btn.config(text="Disconnect Cam")

    def toggle_ai(self):
        if self.ai_enabled:
            self.ai_enabled = False
            if self.detector_thread:
                self.detector_thread.stop()
                self.detector_thread = None
            self.ai_btn.config(text="AI OFF")
            self.ai_status_lbl.config(text="OFF")
            self.ai_barnacle_count.config(text="—")
            self.ai_conf_lbl.config(text="—")
            self.ai_count_lbl.config(text="")
            with self.bus.lock:
                self.bus.ai_detections = []
            self.bus.log("AI detection disabled.")
        else:
            model_path = os.path.normpath(AI_MODEL_PATH)
            if not os.path.isfile(model_path):
                self.bus.log(f"AI model not found at: {model_path}")
                self.bus.log("Train the model first: python AI/train.py")
                return
            self.ai_enabled = True
            self.detector_thread = DetectorThread(self.bus, model_path)
            self.detector_thread.start()
            self.ai_btn.config(text="AI ON")
            self.ai_status_lbl.config(text="LOADING...")
            self.bus.log("AI detection starting...")

    def _on_close(self):
        try:
            geom = self.root.geometry() if self.root.state() != "zoomed" else None
            save_settings({
                "version": SETTINGS_VERSION,
                "zoom_pct": self.zoom_pct,
                "control_port": self.port_var.get(),
                "camera_port": self.cam_port_var.get(),
                "window_geometry": geom,
                "maximized": self.root.state() == "zoomed",
            })
        except Exception:
            pass
        if self.io_thread:
            self.io_thread.stop()
        if self.cam_thread:
            self.cam_thread.stop()
        if self.detector_thread:
            self.detector_thread.stop()
        try:
            pygame.quit()
        except Exception:
            pass
        time.sleep(0.15)
        self.root.destroy()

    # ── Main tick ──

    def _tick(self):
        self._poll_controller()

        with self.bus.lock:
            b = self.bus
            conn, ctrl_name = b.connected, b.controller_name
            lt, rt, lb, rb = b.lt, b.rt, b.lb, b.rb
            left, right, drum, estop = b.left, b.right, b.drum, b.estop

        self.status_lbl.config(text="LIVE" if conn else "OFFLINE",
                               style="Live.TLabel" if conn else "Off.TLabel")
        self.ctrl_lbl.config(text=ctrl_name or "—",
                             foreground=C["text"] if ctrl_name else C["dim"])

        self.lt_bar["value"] = lt; self.lt_val.config(text=f"{lt:3d}")
        self.rt_bar["value"] = rt; self.rt_val.config(text=f"{rt:3d}")
        self.lb_ind.config(style="IndOn.TLabel" if lb else "IndOff.TLabel")
        self.rb_ind.config(style="IndOn.TLabel" if rb else "IndOff.TLabel")
        self.left_val.config(text=f"{left:+4d}")
        self.right_val.config(text=f"{right:+4d}")
        self.drum_ind.config(text="ON" if drum else "OFF",
                             style="IndOn.TLabel" if drum else "IndOff.TLabel")
        self.estop_ind.config(text="ESTOP" if estop else "OK",
                              style="IndDanger.TLabel" if estop else "IndOK.TLabel")

        # Camera
        with self.bus.lock:
            cam_conn = self.bus.cam_connected
            jts = self.bus.last_jpeg_ts
            jpeg = self.bus.last_jpeg if jts > self.bus.rendered_jpeg_ts else None
            if jpeg is not None:
                self.bus.rendered_jpeg_ts = jts

        self.cam_status_lbl.config(text="CAM LIVE" if cam_conn else "CAM OFF",
                                   style="Live.TLabel" if cam_conn else "Off.TLabel")
        self.snap_btn.config(state=tk.NORMAL if cam_conn else tk.DISABLED)
        self.cam_connect_btn.config(text="Disconnect Cam" if cam_conn else "Connect Cam")

        if jpeg:
            try:
                img = Image.open(BytesIO(jpeg)).rotate(180)

                if self.ai_enabled and self.detector_thread:
                    self.detector_thread.submit(img.copy())

                with self.bus.lock:
                    detections = list(self.bus.ai_detections) if self.ai_enabled else []

                if detections:
                    img = draw_detections(img, detections)

                cw = max(self.cam_canvas.winfo_width(), 100)
                ch = max(self.cam_canvas.winfo_height(), 100)
                iw, ih = img.size
                scale = min(cw / iw, ch / ih)
                img = img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))),
                                 Image.BILINEAR)
                self.cam_photo = ImageTk.PhotoImage(img)
                self.cam_canvas.delete("all")
                self.cam_canvas.create_image(cw // 2, ch // 2,
                                             image=self.cam_photo, anchor="center")
                self._showing_feed = True
            except Exception as e:
                self.bus.log(f"CAM decode: {e}")

        if cam_conn:
            if jpeg is not None:
                self._fps_window.append(time.time())
            now = time.time()
            self._fps_window = [t for t in self._fps_window if now - t < 1.0]
            self.cam_fps_lbl.config(text=f"{len(self._fps_window)} fps")
        else:
            self.cam_fps_lbl.config(text="")
            if self._showing_feed:
                self._showing_feed = False
                self.cam_canvas.delete("all")
                self.cam_photo = None
                self._center_placeholder()

        # AI telemetry
        if self.ai_enabled:
            with self.bus.lock:
                dets = list(self.bus.ai_detections)
            n = len(dets)
            avg_conf = sum(d[4] for d in dets) / n if n else 0
            self.ai_status_lbl.config(text="ACTIVE")
            self.ai_barnacle_count.config(text=str(n))
            self.ai_conf_lbl.config(text=f"{avg_conf:.0%}" if n else "—")
            self.ai_count_lbl.config(text=f"{n} detected", foreground=C["ai"] if n else C["dim"])

        # Board dots
        now = time.time()
        with self.bus.lock:
            echo_ts, i2c_ts = self.bus.last_echo_ts, self.bus.last_i2c_ok_ts

        def dot_color(ts):
            if not conn or not ts:
                return C["off"]
            age = now - ts
            return C["ok"] if age < 1.5 else C["warn"] if age < 4.0 else C["err"]

        self.dot_1.config(fg=C["ok"] if conn else C["off"])
        self.dot_2.config(fg=dot_color(echo_ts))
        self.dot_3.config(fg=dot_color(i2c_ts))

        # Log
        try:
            while True:
                msg = self.bus.log_queue.get_nowait()
                self.log_box.config(state="normal")
                self.log_box.insert(tk.END, msg + "\n")
                self.log_box.see(tk.END)
                self.log_box.config(state="disabled")
        except queue.Empty:
            pass

        self.root.after(30, self._tick)


class _SingleInstance:
    """Windows named-mutex single-instance guard. Releases on process exit."""
    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str):
        self.handle = None
        self.already_running = False
        if sys.platform != "win32":
            return
        try:
            self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
            if ctypes.windll.kernel32.GetLastError() == self.ERROR_ALREADY_EXISTS:
                self.already_running = True
        except Exception:
            self.handle = None

    def release(self):
        if self.handle:
            try:
                ctypes.windll.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


def _setup_logging():
    log_path = os.path.join(LOG_DIR, f"{APP_NAME.lower()}.log")
    try:
        for k in range(4, 0, -1):
            src = os.path.join(LOG_DIR, f"{APP_NAME.lower()}.log.{k}")
            dst = os.path.join(LOG_DIR, f"{APP_NAME.lower()}.log.{k+1}")
            if os.path.isfile(src):
                if os.path.isfile(dst):
                    os.remove(dst)
                os.replace(src, dst)
        if os.path.isfile(log_path) and os.path.getsize(log_path) > 2_000_000:
            os.replace(log_path, os.path.join(LOG_DIR, f"{APP_NAME.lower()}.log.1"))
    except OSError:
        pass

    try:
        f = open(log_path, "a", encoding="utf-8", buffering=1)
        f.write(f"\n=== {APP_NAME} {APP_VERSION} starting {datetime.now().isoformat(timespec='seconds')} ===\n")
        sys.stdout = f
        sys.stderr = f
    except OSError:
        pass
    return log_path


def main():
    log_path = _setup_logging()

    lock = _SingleInstance(f"Global\\{APP_NAME}_SingleInstance_v1")
    if lock.already_running:
        try:
            root = tk.Tk(); root.withdraw()
            messagebox.showwarning(
                APP_NAME,
                f"{APP_NAME} is already running.\n\n"
                "Only one instance can be open at a time so the COM ports stay exclusive."
            )
            root.destroy()
        except Exception:
            pass
        return

    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    except Exception:
        tb = traceback.format_exc()
        try:
            with open(os.path.join(LOG_DIR, "crash.log"), "a", encoding="utf-8") as f:
                f.write(f"\n=== CRASH {datetime.now().isoformat(timespec='seconds')} ===\n{tb}\n")
        except OSError:
            pass
        try:
            root = tk.Tk(); root.withdraw()
            messagebox.showerror(
                APP_NAME,
                f"{APP_NAME} hit an unrecoverable error and must close.\n\n"
                f"A crash log was written to:\n{LOG_DIR}"
            )
            root.destroy()
        except Exception:
            pass
    finally:
        lock.release()


if __name__ == "__main__":
    main()
