import os
import sys
import time
import queue
import struct
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

import pygame
import serial
import serial.tools.list_ports
from PIL import Image, ImageTk

# ----- Protocol -----
FRAME_H1, FRAME_H2 = 0xAA, 0x55
CMD_DRIVE = 0x01
SEND_HZ = 50

# ----- Xbox mapping -----
AXIS_LT, AXIS_RT = 4, 5
BTN_LB, BTN_RB, BTN_ESTOP = 4, 5, 1

# ----- Helpers -----
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
    x = (v + 1.0) * 0.5
    return 0 if x < 0.05 else int(round(x * 100))

def list_esp32_ports():
    ports = list(serial.tools.list_ports.comports())
    keywords = ("CP210", "CH340", "CH343", "Silicon Labs", "USB-SERIAL",
                "USB-Enhanced-SERIAL", "USB Serial Device", "USB JTAG",
                "Espressif", "ESP32")
    matched = []
    for p in ports:
        desc = ((p.description or "") + " " + (p.manufacturer or "")).lower()
        hid = (getattr(p, "hwid", "") or "").upper()
        if any(k.lower() in desc for k in keywords) or "VID:PID=303A" in hid:
            matched.append(p.device)
    return matched or [p.device for p in ports]

# ----- Shared state -----
@dataclass
class Bus:
    lt: int = 0
    rt: int = 0
    lb: bool = False
    rb: bool = False
    estop: bool = False
    left:  int = 0
    right: int = 0
    connected: bool = False
    controller_name: str = ""
    last_echo_ts: float = 0.0
    cam_connected: bool = False
    last_jpeg: bytes = b""
    last_jpeg_ts: float = 0.0
    rendered_jpeg_ts: float = 0.0
    log_queue: queue.Queue = field(default_factory=queue.Queue)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def log(self, msg: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{stamp}] {msg}")

# ----- Serial-IO thread -----
class IoThread(threading.Thread):
    def __init__(self, bus: Bus, port_name: str):
        super().__init__(daemon=True)
        self.bus = bus
        self.port_name = port_name
        self.stop_event = threading.Event()
        self.ser = None

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            self.ser = serial.Serial(self.port_name, 115200, timeout=0)
            time.sleep(1.5)
            self.bus.log(f"Opened {self.port_name}")
        except Exception as e:
            self.bus.log(f"SERIAL ERROR: {e}")
            with self.bus.lock: self.bus.connected = False
            return

        with self.bus.lock: self.bus.connected = True
        period = 1.0 / SEND_HZ
        while not self.stop_event.is_set():
            t0 = time.time()
            with self.bus.lock:
                left, right = self.bus.left, self.bus.right
            try:
                self.ser.write(build_frame(CMD_DRIVE, struct.pack("bb", left, right)))
                incoming = self.ser.read(256)
                if incoming:
                    text = incoming.decode("utf-8", errors="replace")
                    now = time.time()
                    with self.bus.lock:
                        self.bus.last_echo_ts = now
                    for line in text.splitlines():
                        s = line.strip()
                        if s:
                            self.bus.log(f"<- {s}")
            except Exception as e:
                self.bus.log(f"IO ERROR: {e}")
                break
            dt = time.time() - t0
            if dt < period: time.sleep(period - dt)

        try:
            if self.ser:
                self.ser.write(build_frame(CMD_DRIVE, struct.pack("bb", 0, 0)))
                self.ser.close()
        except Exception: pass
        with self.bus.lock: self.bus.connected = False
        self.bus.log("Disconnected.")

# ----- Camera thread -----
class CamThread(threading.Thread):
    MAGIC = bytes([0xA5, 0x5A, 0xF0, 0x0D])
    MAX_FRAME = 300_000

    def __init__(self, bus: Bus, port_name: str):
        super().__init__(daemon=True)
        self.bus = bus
        self.port_name = port_name
        self.stop_event = threading.Event()
        self.ser = None

    def stop(self): self.stop_event.set()

    def run(self):
        try:
            self.ser = serial.Serial(self.port_name, 921600, timeout=0.05)
            time.sleep(1.5)
            self.bus.log(f"Camera opened on {self.port_name}")
        except Exception as e:
            self.bus.log(f"CAM SERIAL ERROR: {e}")
            return
        with self.bus.lock: self.bus.cam_connected = True

        buf = bytearray()
        while not self.stop_event.is_set():
            try:
                chunk = self.ser.read(16384)
            except Exception as e:
                self.bus.log(f"CAM IO ERROR: {e}")
                break
            if chunk: buf.extend(chunk)
            else: continue

            while True:
                idx = buf.find(self.MAGIC)
                if idx < 0:
                    if len(buf) > 3: del buf[:-3]
                    break
                if idx > 0: del buf[:idx]
                if len(buf) < 8: break
                length = int.from_bytes(bytes(buf[4:8]), "big")
                if length == 0 or length > self.MAX_FRAME:
                    del buf[:4]; continue
                if len(buf) < 8 + length: break
                jpeg = bytes(buf[8:8 + length])
                del buf[:8 + length]
                with self.bus.lock:
                    self.bus.last_jpeg = jpeg
                    self.bus.last_jpeg_ts = time.time()

        try:
            if self.ser: self.ser.close()
        except Exception: pass
        with self.bus.lock: self.bus.cam_connected = False
        self.bus.log("Camera disconnected.")

# ----- App -----
class App:
    KEY_LEFT_FWD  = "Up"
    KEY_LEFT_BACK = "Down"
    KEY_RIGHT_FWD  = "w"
    KEY_RIGHT_BACK = "s"
    KEY_ESTOP = "Escape"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.bus = Bus()
        self.io_thread = None
        self.cam_thread = None
        self.cam_photo = None

        pygame.init()
        pygame.joystick.init()
        self.joy = None
        self.keys_held = set()

        root.title("Barnacle Robot — Presentation")
        root.geometry("1100x700")
        root.minsize(900, 600)

        # ===== Top bar =====
        topbox = ttk.Frame(root); topbox.pack(side=tk.TOP, fill=tk.X)

        bar = ttk.Frame(topbox, padding=(8, 8, 8, 2)); bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="Control port:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(bar, textvariable=self.port_var, width=14, state="readonly")
        self.port_box.pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Refresh", command=self.refresh_ports).pack(side=tk.LEFT, padx=2)
        self.connect_btn = ttk.Button(bar, text="Connect", command=self.toggle_connect)
        self.connect_btn.pack(side=tk.LEFT, padx=8)
        self.status_lbl = ttk.Label(bar, text="● disconnected", foreground="grey")
        self.status_lbl.pack(side=tk.LEFT, padx=8)

        cbar = ttk.Frame(topbox, padding=(8, 2, 8, 8)); cbar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(cbar, text="Camera port: ").pack(side=tk.LEFT)
        self.cam_port_var = tk.StringVar()
        self.cam_port_box = ttk.Combobox(cbar, textvariable=self.cam_port_var, width=14, state="readonly")
        self.cam_port_box.pack(side=tk.LEFT, padx=4)
        ttk.Button(cbar, text="Refresh", command=self.refresh_ports).pack(side=tk.LEFT, padx=2)
        self.cam_connect_btn = ttk.Button(cbar, text="Connect Cam", command=self.toggle_cam)
        self.cam_connect_btn.pack(side=tk.LEFT, padx=8)
        self.cam_status_lbl = ttk.Label(cbar, text="● cam off", foreground="grey")
        self.cam_status_lbl.pack(side=tk.LEFT, padx=8)
        self.cam_fps_lbl = ttk.Label(cbar, text="", foreground="grey")
        self.cam_fps_lbl.pack(side=tk.LEFT, padx=12)

        # ===== Main split =====
        main = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        cam_frame = ttk.LabelFrame(main, text="Camera", padding=6)
        self.cam_canvas = tk.Canvas(cam_frame, bg="black", width=640, height=480, highlightthickness=0)
        self.cam_canvas.pack(fill=tk.BOTH, expand=True)
        self.cam_canvas.create_text(320, 240, text="no camera connected",
                                     fill="#444", font=("Segoe UI", 18))
        cam_btns = ttk.Frame(cam_frame); cam_btns.pack(fill=tk.X, pady=(4, 0))
        self.snap_btn = ttk.Button(cam_btns, text="Snapshot", command=self.take_snapshot, state=tk.DISABLED)
        self.snap_btn.pack(side=tk.LEFT)
        self.snap_lbl = ttk.Label(cam_btns, text="", foreground="grey")
        self.snap_lbl.pack(side=tk.LEFT, padx=8)
        main.add(cam_frame, weight=3)

        tele = ttk.LabelFrame(main, text="Telemetry", padding=10)
        main.add(tele, weight=2)

        ttk.Label(tele, text="Controller:").grid(row=0, column=0, sticky="w")
        self.ctrl_lbl = ttk.Label(tele, text="—", foreground="grey")
        self.ctrl_lbl.grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Separator(tele, orient="horizontal").grid(row=1, columnspan=3, sticky="ew", pady=6)

        ttk.Label(tele, text="LT:").grid(row=2, column=0, sticky="w")
        self.lt_bar = ttk.Progressbar(tele, length=160, maximum=100); self.lt_bar.grid(row=2, column=1)
        self.lt_val = ttk.Label(tele, text="0"); self.lt_val.grid(row=2, column=2, padx=4)
        ttk.Label(tele, text="RT:").grid(row=3, column=0, sticky="w")
        self.rt_bar = ttk.Progressbar(tele, length=160, maximum=100); self.rt_bar.grid(row=3, column=1)
        self.rt_val = ttk.Label(tele, text="0"); self.rt_val.grid(row=3, column=2, padx=4)

        self.lb_ind = ttk.Label(tele, text="LB", background="#222", foreground="#888",
                                width=6, anchor="center", padding=4)
        self.lb_ind.grid(row=4, column=0, pady=6)
        self.rb_ind = ttk.Label(tele, text="RB", background="#222", foreground="#888",
                                width=6, anchor="center", padding=4)
        self.rb_ind.grid(row=4, column=1, pady=6, sticky="w")

        ttk.Separator(tele, orient="horizontal").grid(row=5, columnspan=3, sticky="ew", pady=6)
        ttk.Label(tele, text="Left:").grid(row=6, column=0, sticky="w")
        self.left_val = ttk.Label(tele, text="0", font=("Consolas", 14))
        self.left_val.grid(row=6, column=1, sticky="w")
        ttk.Label(tele, text="Right:").grid(row=7, column=0, sticky="w")
        self.right_val = ttk.Label(tele, text="0", font=("Consolas", 14))
        self.right_val.grid(row=7, column=1, sticky="w")

        ttk.Label(tele, text="E-Stop:").grid(row=8, column=0, sticky="w", pady=(8, 0))
        self.estop_ind = ttk.Label(tele, text="OK", background="#1a3", foreground="white",
                                   width=8, anchor="center", padding=4)
        self.estop_ind.grid(row=8, column=1, sticky="w", pady=(8, 0))

        # Log
        log_frame = ttk.LabelFrame(root, text="Log", padding=4)
        log_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.log_box = scrolledtext.ScrolledText(log_frame, height=10, state="disabled",
                                                  bg="#111", fg="#ddd", font=("Consolas", 9))
        self.log_box.pack(fill=tk.BOTH, expand=True)

        self.refresh_ports()
        self.detect_joystick()
        self.bus.log("Presentation GUI started. Plug in ESP32 + Xbox controller, click Connect.")
        self.bus.log("Keyboard: ↑/↓ = left side, W/S = right side, Esc = E-stop (hold).")

        root.bind("<KeyPress>",   self.on_key_press)
        root.bind("<KeyRelease>", self.on_key_release)
        root.focus_set()

        self.root.after(30, self.tick)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----- Keyboard -----
    def on_key_press(self, ev):
        ks = ev.keysym
        if len(ks) == 1: ks = ks.lower()
        self.keys_held.add(ks)

    def on_key_release(self, ev):
        ks = ev.keysym
        if len(ks) == 1: ks = ks.lower()
        self.keys_held.discard(ks)

    def keyboard_drive(self):
        left = 0
        if self.KEY_LEFT_FWD  in self.keys_held: left += 100
        if self.KEY_LEFT_BACK in self.keys_held: left -= 100
        right = 0
        if self.KEY_RIGHT_FWD  in self.keys_held: right += 100
        if self.KEY_RIGHT_BACK in self.keys_held: right -= 100
        return left, right

    # ----- Snapshot -----
    def take_snapshot(self):
        with self.bus.lock:
            jpeg = self.bus.last_jpeg
        if not jpeg:
            self.bus.log("Snapshot: no camera frame available yet.")
            return
        folder = os.path.join(os.path.dirname(__file__), "snapshots")
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(folder, f"snap_{stamp}.jpg")
        try:
            with open(path, "wb") as f: f.write(jpeg)
            self.bus.log(f"Snapshot saved: {path}")
            self.snap_lbl.config(text=f"saved {os.path.basename(path)}", foreground="#1a3")
        except Exception as e:
            self.bus.log(f"Snapshot failed: {e}")

    # ----- Controller -----
    def detect_joystick(self):
        try:
            pygame.joystick.quit(); pygame.joystick.init()
        except Exception: pass
        if pygame.joystick.get_count() > 0:
            self.joy = pygame.joystick.Joystick(0)
            self.joy.init()
            with self.bus.lock: self.bus.controller_name = self.joy.get_name()
            self.bus.log(f"Controller: {self.joy.get_name()}")
        else:
            self.joy = None
            with self.bus.lock: self.bus.controller_name = ""

    def poll_controller(self):
        with self.bus.lock: connected = self.bus.connected

        if not connected:
            with self.bus.lock:
                self.bus.lt = self.bus.rt = 0
                self.bus.lb = self.bus.rb = False
                self.bus.estop = False
                self.bus.left = self.bus.right = 0
            if self.joy is None and pygame.joystick.get_count() > 0:
                self.detect_joystick()
            return

        lt = rt = 0
        lb = rb = estop = False
        if self.joy is not None:
            pygame.event.pump()
            try:
                lt = trigger_to_pct(self.joy.get_axis(AXIS_LT))
                rt = trigger_to_pct(self.joy.get_axis(AXIS_RT))
                lb = bool(self.joy.get_button(BTN_LB))
                rb = bool(self.joy.get_button(BTN_RB))
                estop = bool(self.joy.get_button(BTN_ESTOP))
            except pygame.error:
                self.bus.log("Controller disconnected.")
                self.joy = None
                with self.bus.lock: self.bus.controller_name = ""
        elif pygame.joystick.get_count() > 0:
            self.detect_joystick()

        ctl_left  = max(-100, min(100, lt - (100 if lb else 0)))
        ctl_right = max(-100, min(100, rt - (100 if rb else 0)))

        kb_left, kb_right = self.keyboard_drive()
        left  = ctl_left  if ctl_left  != 0 else kb_left
        right = ctl_right if ctl_right != 0 else kb_right

        if estop or (self.KEY_ESTOP in self.keys_held):
            left = right = 0
            estop = True

        with self.bus.lock:
            self.bus.lt, self.bus.rt = lt, rt
            self.bus.lb, self.bus.rb = lb, rb
            self.bus.estop = estop
            self.bus.left, self.bus.right = left, right

    # ----- Connect/Disconnect -----
    def refresh_ports(self):
        ports = list_esp32_ports()
        self.port_box["values"] = ports
        self.cam_port_box["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])
        if len(ports) >= 2 and not self.cam_port_var.get():
            for p in ports:
                if p != self.port_var.get():
                    self.cam_port_var.set(p); break

    def toggle_connect(self):
        if self.io_thread and self.io_thread.is_alive(): self.disconnect()
        else: self.connect()

    def connect(self):
        port = self.port_var.get()
        if not port:
            self.bus.log("Pick a COM port first."); return
        self.io_thread = IoThread(self.bus, port)
        self.io_thread.start()
        self.connect_btn.config(text="Disconnect")

    def disconnect(self):
        if self.io_thread:
            self.io_thread.stop()
            self.io_thread = None
        self.connect_btn.config(text="Connect")

    def toggle_cam(self):
        if self.cam_thread and self.cam_thread.is_alive(): self.disconnect_cam()
        else: self.connect_cam()

    def connect_cam(self):
        port = self.cam_port_var.get()
        if not port:
            self.bus.log("Pick a camera COM port first."); return
        if port == self.port_var.get() and self.io_thread and self.io_thread.is_alive():
            self.bus.log("Camera port can't equal the active control port."); return
        self.cam_thread = CamThread(self.bus, port)
        self.cam_thread.start()
        self.cam_connect_btn.config(text="Disconnect Cam")

    def disconnect_cam(self):
        if self.cam_thread:
            self.cam_thread.stop()
            self.cam_thread = None
        self.cam_connect_btn.config(text="Connect Cam")
        self.cam_canvas.delete("all")
        w = self.cam_canvas.winfo_width() or 640
        h = self.cam_canvas.winfo_height() or 480
        self.cam_canvas.create_text(w // 2, h // 2, text="no camera connected",
                                     fill="#444", font=("Segoe UI", 18))
        self.cam_photo = None

    def on_close(self):
        self.disconnect(); self.disconnect_cam()
        try: pygame.quit()
        except Exception: pass
        time.sleep(0.2)
        self.root.destroy()

    # ----- Tick -----
    def tick(self):
        self.poll_controller()
        with self.bus.lock:
            b = self.bus
            connected = b.connected
            ctrl_name = b.controller_name
            lt, rt = b.lt, b.rt
            lb, rb = b.lb, b.rb
            left, right = b.left, b.right
            estop = b.estop
            cam_connected = b.cam_connected
            jpeg_ts = b.last_jpeg_ts
            jpeg = b.last_jpeg if jpeg_ts > b.rendered_jpeg_ts else None
            if jpeg is not None:
                b.rendered_jpeg_ts = jpeg_ts

        self.status_lbl.config(
            text="● connected" if connected else "● disconnected",
            foreground="#1a3" if connected else "grey")
        self.ctrl_lbl.config(text=ctrl_name or "—",
                             foreground="black" if ctrl_name else "grey")

        self.lt_bar["value"] = lt; self.lt_val.config(text=str(lt))
        self.rt_bar["value"] = rt; self.rt_val.config(text=str(rt))
        self.lb_ind.config(background="#1a3" if lb else "#222",
                           foreground="white" if lb else "#888")
        self.rb_ind.config(background="#1a3" if rb else "#222",
                           foreground="white" if rb else "#888")
        self.left_val.config(text=f"{left:+4d}")
        self.right_val.config(text=f"{right:+4d}")
        self.estop_ind.config(text="ESTOP" if estop else "OK",
                              background="#cc0000" if estop else "#1a3")

        # Cam render
        self.cam_status_lbl.config(
            text="● cam live" if cam_connected else "● cam off",
            foreground="#1a3" if cam_connected else "grey")
        self.snap_btn.config(state=tk.NORMAL if cam_connected else tk.DISABLED)
        self.cam_connect_btn.config(text="Disconnect Cam" if cam_connected else "Connect Cam")

        if jpeg:
            try:
                img = Image.open(BytesIO(jpeg))
                img = img.rotate(180)   # camera is mounted upside-down
                cw = max(self.cam_canvas.winfo_width(), 100)
                ch = max(self.cam_canvas.winfo_height(), 100)
                img.thumbnail((cw, ch), Image.BILINEAR)
                self.cam_photo = ImageTk.PhotoImage(img)
                self.cam_canvas.delete("all")
                self.cam_canvas.create_image(cw // 2, ch // 2, image=self.cam_photo, anchor="center")
            except Exception as e:
                self.bus.log(f"CAM decode error: {e}")

        if cam_connected:
            self._fps_window = getattr(self, "_fps_window", [])
            if jpeg is not None:
                self._fps_window.append(time.time())
                self._fps_window = [t for t in self._fps_window if time.time() - t < 1.0]
            self.cam_fps_lbl.config(text=f"{len(self._fps_window)} fps")
        else:
            self.cam_fps_lbl.config(text="")

        # Drain log
        try:
            while True:
                msg = self.bus.log_queue.get_nowait()
                self.log_box.config(state="normal")
                self.log_box.insert(tk.END, msg + "\n")
                self.log_box.see(tk.END)
                self.log_box.config(state="disabled")
        except queue.Empty:
            pass

        self.root.after(30, self.tick)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
    except Exception: pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
