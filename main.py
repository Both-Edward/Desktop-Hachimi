"""
Desktop Hachimi - Windows Desktop Pet Application
VERSION = "1.0.0"
APP_NAME = "Desktop Hachimi"
AUTHOR = "Edward"
AUTHOR_EMAIL = "2651671851@qq.com"
"""

import sys
import os
import json
import random
import shutil
import math
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageSequence
import pystray
from pystray import MenuItem as item, Menu

# ── App Info ──────────────────────────────────────────────────────────────────
VERSION      = "1.0.0"
APP_NAME     = "Desktop Hachimi"
AUTHOR       = "Edward"
AUTHOR_EMAIL = "2651671851@qq.com"
GITHUB_URL   = "https://github.com/Edward-EH-Holmes/Desktop-Hachimi"

# ── DPI Awareness (Windows) ───────────────────────────────────────────────────
def _enable_dpi_awareness():
    """Call SetProcessDpiAwareness so tkinter windows are crisp on HiDPI screens."""
    try:
        import ctypes
        # Windows 8.1+: Per-Monitor DPI awareness
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            # Windows Vista+: System DPI awareness
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

_enable_dpi_awareness()

# ── Global font for dialogs ───────────────────────────────────────────────────
_FONT_NORMAL = ("Microsoft YaHei UI", 10)
_FONT_BOLD   = ("Microsoft YaHei UI", 10, "bold")
_FONT_LARGE  = ("Microsoft YaHei UI", 13, "bold")
_FONT_SMALL  = ("Microsoft YaHei UI", 9)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PETS_DIR   = os.path.join(BASE_DIR, "Pets")
ICO_DIR    = os.path.join(BASE_DIR, "ico")
APP_ICO    = os.path.join(ICO_DIR, "Desktop Hachimi ico.ico")
CONFIG_F   = os.path.join(BASE_DIR, "config.json")

# ── Default Config ────────────────────────────────────────────────────────────
DEFAULT_CFG = {
    "pet":          "Ameath",
    "scale":        1.0,
    "opacity":      1.0,
    "speed":        3,
    "mouse_follow": False,
    "always_on_top": True,
    "x":            100,
    "y":            100,
}


def get_monitors():
    """Return list of (x, y, w, h) for each monitor.
    Tries screeninfo first; falls back to single-screen via tkinter."""
    try:
        from screeninfo import get_monitors as _gm
        return [(m.x, m.y, m.width, m.height) for m in _gm()]
    except Exception:
        pass
    # Fallback: try using win32api if available
    try:
        import ctypes
        monitors = []
        def _cb(hMonitor, hdcMonitor, lprcMonitor, dwData):
            r = lprcMonitor.contents
            monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return 1
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_ulong, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_long * 4),
            ctypes.c_double,
        )
        # Use a simpler struct approach
        import ctypes.wintypes as wt
        class RECT(ctypes.Structure):
            _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                        ("right", wt.LONG), ("bottom", wt.LONG)]
        monitors2 = []
        cb_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(RECT), wt.LPARAM)
        def _cb2(hm, hdc, lprect, data):
            r = lprect.contents
            monitors2.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return True
        ctypes.windll.user32.EnumDisplayMonitors(None, None, cb_type(_cb2), 0)
        if monitors2:
            return monitors2
    except Exception:
        pass
    return None   # caller will use tkinter fallback


def get_screen_for_point(px, py, monitors):
    """Return the (x, y, w, h) of the monitor that contains point (px, py).
    If none contains it, return the closest one."""
    if not monitors:
        return None
    # Check containment
    for mx, my, mw, mh in monitors:
        if mx <= px < mx + mw and my <= py < my + mh:
            return (mx, my, mw, mh)
    # Closest by centre distance
    best, best_d = monitors[0], float("inf")
    for m in monitors:
        mx, my, mw, mh = m
        cx, cy = mx + mw / 2, my + mh / 2
        d = math.hypot(px - cx, py - cy)
        if d < best_d:
            best, best_d = m, d
    return best


def set_window_icon(win):
    """Set the app icon on any Toplevel (or Tk) window."""
    if os.path.exists(APP_ICO):
        try:
            win.iconbitmap(APP_ICO)
        except Exception:
            pass


def load_config():
    if os.path.exists(CONFIG_F):
        try:
            with open(CONFIG_F, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CFG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return DEFAULT_CFG.copy()


def save_config(cfg):
    with open(CONFIG_F, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── GIF Loader ────────────────────────────────────────────────────────────────
def _resize_rgba_no_bleed(img_rgba, new_w, new_h):
    """
    Resize an RGBA image without black-border bleeding artefacts.

    The standard LANCZOS filter mixes transparent (0,0,0,0) pixels with
    opaque pixels at edges, pulling RGB values toward (0,0,0) and creating
    a dark halo / black fringe.  The fix is 'pre-multiplied alpha' (a.k.a.
    alpha-weighted) resampling:
      1. Premultiply: scale each channel by alpha/255 so transparent pixels
         contribute zero colour.
      2. Resize RGB and A channels separately with LANCZOS.
      3. Un-premultiply: divide RGB by the resampled alpha to recover correct
         colour; pixels that became fully transparent get zero colour.
    """
    import numpy as np

    arr = np.array(img_rgba, dtype=np.float32)          # H x W x 4
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    alpha_norm = a / 255.0

    # Premultiply
    pre = np.stack([r * alpha_norm,
                    g * alpha_norm,
                    b * alpha_norm,
                    a], axis=-1).astype(np.uint8)
    pre_img = Image.fromarray(pre, "RGBA")

    # Resize premultiplied image and alpha separately
    pre_resized = pre_img.resize((new_w, new_h), Image.LANCZOS)
    pre_arr     = np.array(pre_resized, dtype=np.float32)

    # Un-premultiply
    ra = pre_arr[..., 3] / 255.0                        # resampled alpha [0,1]
    out = np.zeros_like(pre_arr)
    mask = ra > 0
    for c in range(3):
        ch = pre_arr[..., c]
        out[..., c] = np.where(mask, np.clip(ch / np.where(mask, ra, 1), 0, 255), 0)
    out[..., 3] = pre_arr[..., 3]

    return Image.fromarray(out.astype(np.uint8), "RGBA")


def load_gif_frames(path, scale=1.0):
    """Return list of (ImageTk.PhotoImage, duration_ms, pil_image).
    The pil_image is kept so we can flip it on demand."""
    frames = []
    try:
        img = Image.open(path)
        for frame in ImageSequence.Iterator(img):
            duration = frame.info.get("duration", 100)
            f = frame.convert("RGBA")
            if scale != 1.0:
                w = max(1, int(f.width  * scale))
                h = max(1, int(f.height * scale))
                f = _resize_rgba_no_bleed(f, w, h)
            frames.append((ImageTk.PhotoImage(f), duration, f))
    except Exception as e:
        print(f"[WARN] load_gif_frames({path}): {e}")
    return frames


# ── Pet Data ──────────────────────────────────────────────────────────────────
class PetData:
    """Represents one pet's animation assets and weights."""

    def __init__(self, name, scale=1.0):
        self.name  = name
        self.scale = scale
        self.dir   = os.path.join(PETS_DIR, name)
        self._load()

    def _load(self):
        s = self.scale
        d = self.dir
        n = self.name

        # ── dynamic (active) ────────────────────────────────────────────────
        dynamic_path = os.path.join(d, f"{n}.gif")
        self.dynamic_frames = load_gif_frames(dynamic_path, s) if os.path.exists(dynamic_path) else []
        self.dynamic_weight = self._read_weight("dynamic_weight", 3)

        # ── drag ────────────────────────────────────────────────────────────
        drag_path = os.path.join(d, "drag.gif")
        self.drag_frames = load_gif_frames(drag_path, s) if os.path.exists(drag_path) else []

        # ── idle ────────────────────────────────────────────────────────────
        self.idle_variants   = self._load_variants("idle", s)
        self.idle_weights    = self._read_multi_weight("idle_weight", len(self.idle_variants), 2)

        # ── move ────────────────────────────────────────────────────────────
        self.move_variants   = self._load_variants("move", s)
        self.move_weights    = self._read_multi_weight("move_weight", len(self.move_variants), 1)
        self.move_flip_info  = self._load_flip_info()

    def _load_variants(self, prefix, scale):
        """Load prefix.gif OR prefix1.gif, prefix2.gif ..."""
        d = self.dir
        single = os.path.join(d, f"{prefix}.gif")
        if os.path.exists(single):
            frames = load_gif_frames(single, scale)
            return [frames] if frames else []
        variants = []
        i = 1
        while True:
            p = os.path.join(d, f"{prefix}{i}.gif")
            if not os.path.exists(p):
                break
            variants.append(load_gif_frames(p, scale))
            i += 1
        return variants

    def _load_flip_info(self):
        """Read flip.json if present."""
        p = os.path.join(self.dir, "flip.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _read_weight(self, key, default):
        p = os.path.join(self.dir, "weights.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f).get(key, default)
            except Exception:
                pass
        return default

    def _read_multi_weight(self, key, count, default):
        p = os.path.join(self.dir, "weights.json")
        if os.path.exists(p):
            try:
                data = json.load(open(p, "r", encoding="utf-8"))
                v = data.get(key, None)
                if isinstance(v, list) and len(v) == count:
                    return v
            except Exception:
                pass
        return [default] * max(count, 1)

    def pick_idle(self):
        """Return a random idle frame list."""
        if not self.idle_variants:
            return self.dynamic_frames or []
        return random.choices(self.idle_variants, weights=self.idle_weights, k=1)[0]

    def pick_move(self):
        """Return a random move frame list."""
        if not self.move_variants:
            return self.dynamic_frames or []
        return random.choices(self.move_variants, weights=self.move_weights, k=1)[0]

    def should_flip(self, variant_name, going_right):
        """Determine if the sprite should be horizontally flipped."""
        info = self.move_flip_info.get(variant_name, {})
        if not info.get("enabled", False):
            return False
        default_dir = info.get("default_dir", "left")
        if default_dir == "left":
            # flip when going RIGHT
            return going_right
        else:
            # flip when going LEFT
            return not going_right


# ── Pet Window ────────────────────────────────────────────────────────────────
STATE_DYNAMIC = "dynamic"
STATE_IDLE    = "idle"
STATE_MOVE    = "move"
STATE_DRAG    = "drag"


class PetWindow:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-transparentcolor", "black")
        self.root.attributes("-topmost", self.cfg["always_on_top"])
        self.root.configure(bg="black")
        self.root.attributes("-alpha", self.cfg["opacity"])

        # Set crisp default font for all widgets globally
        try:
            import tkinter.font as tkfont
            default_font = tkfont.nametofont("TkDefaultFont")
            default_font.configure(family="Microsoft YaHei UI", size=10)
            text_font = tkfont.nametofont("TkTextFont")
            text_font.configure(family="Microsoft YaHei UI", size=10)
            fixed_font = tkfont.nametofont("TkFixedFont")
            fixed_font.configure(family="Consolas", size=10)
        except Exception:
            pass

        # set icon if possible
        if os.path.exists(APP_ICO):
            try:
                self.root.iconbitmap(APP_ICO)
            except Exception:
                pass

        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack()
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")

        # state
        self.state        = STATE_IDLE
        self.prev_state   = STATE_IDLE
        self._frame_idx   = 0
        self._after_id    = None
        self.current_frames = []
        self._current_move_key = None   # flip.json key for current move variant
        self._flipped_cache = {}        # key -> list of (PhotoImage, duration)

        # movement
        self.vx = 0.0
        self.vy = 0.0
        self.going_right = True
        self.move_target  = None      # (tx, ty) when following mouse
        self._move_timer  = None

        # mouse follow
        self._mf_loop_id      = None   # after-id for high-freq mouse follow loop
        self._mf_leave_id     = None   # after-id for 1s delay before leaving dynamic
        self._mf_near_mouse   = False  # whether pet is currently near mouse

        # drag
        self._drag_ox = 0
        self._drag_oy = 0

        # position
        self.x = float(self.cfg.get("x", 100))
        self.y = float(self.cfg.get("y", 100))

        # multi-monitor: cache monitor list and current screen bounds
        self._monitors = get_monitors()   # list of (x, y, w, h) or None
        self._current_screen = None       # (x, y, w, h) – updated on drag end & init

        self.pet_data: PetData = None
        self.load_pet(initial=True)
        self.position_window()
        self.bind_events()
        self.start_state_machine()

    # ── Pet Loading ────────────────────────────────────────────────────────
    def load_pet(self, initial=False):
        name  = self.cfg["pet"]
        scale = self.cfg["scale"]
        self.pet_data = PetData(name, scale)
        # On very first load start in DYNAMIC; on reload start in IDLE
        self._enter_state(STATE_DYNAMIC if initial else STATE_IDLE)

    def reload_pet(self):
        """Called when pet / scale / etc changes."""
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        if self._move_timer:
            self.root.after_cancel(self._move_timer)
            self._move_timer = None
        self._stop_mouse_follow_loop()
        self._flipped_cache.clear()
        self.load_pet(initial=False)
        if self.cfg.get("mouse_follow"):
            self._start_mouse_follow_loop()

    # ── State Machine ──────────────────────────────────────────────────────
    def start_state_machine(self):
        # Delay first tick by 5000ms so pet stays in DYNAMIC on startup
        self.root.after(5000, self._state_tick)
        if self.cfg.get("mouse_follow"):
            self._start_mouse_follow_loop()

    def _state_tick(self):
        """Periodically decide whether to switch state (autonomous mode only)."""
        if self.state not in (STATE_DRAG,) and not self.cfg.get("mouse_follow"):
            self._autonomous_logic()
        self.root.after(5000, self._state_tick)

    def _autonomous_logic(self):
        """Randomly switch between dynamic/idle/move."""
        pd = self.pet_data
        dw = pd.dynamic_weight
        iw = sum(pd.idle_weights)
        mw = sum(pd.move_weights)
        total = dw + iw + mw
        r = random.random() * total
        if r < dw:
            self._enter_state(STATE_DYNAMIC)
        elif r < dw + iw:
            self._enter_state(STATE_IDLE)
        else:
            self._enter_state(STATE_MOVE)
            # random direction
            angle = random.uniform(0, 2 * math.pi)
            speed = self.cfg.get("speed", 3)
            self.vx = math.cos(angle) * speed
            self.vy = math.sin(angle) * speed
            self.going_right = self.vx >= 0
            duration = random.randint(3, 8)
            self.move_target = None
            if self._move_timer:
                self.root.after_cancel(self._move_timer)
            self._move_timer = self.root.after(duration * 1000, self._stop_moving)

    def _stop_moving(self):
        if self.state == STATE_MOVE:
            self._enter_state(STATE_IDLE)

    # ── Mouse Follow High-Freq Loop ─────────────────────────────────────────
    def _start_mouse_follow_loop(self):
        """Start the high-frequency mouse follow loop (50ms interval)."""
        self._mf_near_mouse = False
        self._cancel_mf_leave_timer()
        self._mf_loop_tick()

    def _stop_mouse_follow_loop(self):
        """Stop the high-frequency mouse follow loop."""
        if self._mf_loop_id:
            self.root.after_cancel(self._mf_loop_id)
            self._mf_loop_id = None
        self._cancel_mf_leave_timer()
        self._mf_near_mouse = False

    def _cancel_mf_leave_timer(self):
        if self._mf_leave_id:
            self.root.after_cancel(self._mf_leave_id)
            self._mf_leave_id = None

    def _mf_loop_tick(self):
        """High-frequency tick: update velocity and state for mouse follow."""
        if not self.cfg.get("mouse_follow") or self.state == STATE_DRAG:
            self._mf_loop_id = None
            return

        mx = self.root.winfo_pointerx()
        my = self.root.winfo_pointery()
        pw = max(self.canvas.winfo_width(), 1)
        ph = max(self.canvas.winfo_height(), 1)
        cx = self.x + pw / 2
        cy = self.y + ph / 2
        dist = math.hypot(mx - cx, my - cy)

        near_threshold = max(pw, ph) / 2 + 10   # arrived when centre within sprite radius+10px

        if dist < near_threshold:
            # Pet has reached the mouse
            if not self._mf_near_mouse:
                # Just arrived — cancel any pending leave timer and enter dynamic
                self._mf_near_mouse = True
                self._cancel_mf_leave_timer()
                self.vx = 0.0
                self.vy = 0.0
                if self.state != STATE_DYNAMIC:
                    self._enter_state(STATE_DYNAMIC)
            else:
                # Still near — stay in dynamic, keep velocity 0
                self.vx = 0.0
                self.vy = 0.0
        else:
            # Mouse is away from pet
            if self._mf_near_mouse:
                # Just left — start 1s countdown then resume moving
                self._mf_near_mouse = False
                self._cancel_mf_leave_timer()
                self._mf_leave_id = self.root.after(1000, self._mf_leave_dynamic)
            else:
                # Already moving — update velocity towards mouse
                if self.state != STATE_MOVE:
                    self._enter_state(STATE_MOVE)
                speed = self.cfg.get("speed", 3)
                dx, dy = mx - cx, my - cy
                d = max(dist, 1)
                self.vx = dx / d * speed
                self.vy = dy / d * speed
                self.going_right = self.vx >= 0
                self.move_target = (mx, my)

        self._mf_loop_id = self.root.after(50, self._mf_loop_tick)

    def _mf_leave_dynamic(self):
        """Called 1 second after mouse left the pet — start chasing again."""
        self._mf_leave_id = None
        if self.cfg.get("mouse_follow") and self.state != STATE_DRAG:
            if self.state != STATE_MOVE:
                self._enter_state(STATE_MOVE)
            # velocity will be updated on next tick

    # ── State Entry ────────────────────────────────────────────────────────
    def _enter_state(self, state):
        self.state = state
        pd = self.pet_data
        self._current_move_key = None
        if state == STATE_DYNAMIC:
            self.current_frames = pd.dynamic_frames or pd.pick_idle()
        elif state == STATE_IDLE:
            self.current_frames = pd.pick_idle()
            self.vx = self.vy = 0
        elif state == STATE_MOVE:
            move_count = len(pd.move_variants)
            if not pd.move_variants:
                self.current_frames = pd.dynamic_frames or pd.pick_idle()
            else:
                idx = random.choices(range(move_count), weights=pd.move_weights, k=1)[0]
                self.current_frames = pd.move_variants[idx]
                # determine flip.json key for this variant
                self._current_move_key = "move" if move_count == 1 else f"move{idx + 1}"
        elif state == STATE_DRAG:
            self.current_frames = pd.drag_frames or pd.dynamic_frames or pd.pick_idle()
        self._frame_idx = 0
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._animate()

    # ── Animation ──────────────────────────────────────────────────────────
    def _get_flipped_frames(self, key):
        """Return (and cache) horizontally-flipped PhotoImages for a move variant."""
        if key not in self._flipped_cache:
            flipped = []
            for photo, duration, pil_img in self.current_frames:
                f_flip = pil_img.transpose(Image.FLIP_LEFT_RIGHT)
                flipped.append((ImageTk.PhotoImage(f_flip), duration))
            self._flipped_cache[key] = flipped
        return self._flipped_cache[key]

    def _animate(self):
        if not self.current_frames:
            self._after_id = self.root.after(100, self._animate)
            return
        idx = self._frame_idx % len(self.current_frames)

        # Determine whether to show flipped frame
        need_flip = (
            self.state == STATE_MOVE
            and self._current_move_key is not None
            and self.pet_data.should_flip(self._current_move_key, self.going_right)
        )

        if need_flip:
            frames = self._get_flipped_frames(self._current_move_key)
            photo, duration = frames[idx % len(frames)]
        else:
            photo, duration, *_ = self.current_frames[idx]

        w = photo.width()
        h = photo.height()
        self.canvas.config(width=w, height=h)
        self.canvas.itemconfig(self.img_item, image=photo)
        self._frame_idx = (idx + 1) % len(self.current_frames)
        self._after_id = self.root.after(duration, self._animate)

    # ── Movement Loop ──────────────────────────────────────────────────────
    def _movement_loop(self):
        if self.state == STATE_MOVE:
            pw = max(self.canvas.winfo_width(), 1)
            ph = max(self.canvas.winfo_height(), 1)

            self.x += self.vx
            self.y += self.vy

            # Get current screen bounds for bouncing
            sx, sy, sw, sh = self._get_current_screen()

            # Bounce off current screen edges
            if self.x < sx:
                self.x = sx; self.vx = abs(self.vx); self.going_right = True
            if self.x + pw > sx + sw:
                self.x = sx + sw - pw; self.vx = -abs(self.vx); self.going_right = False
            if self.y < sy:
                self.y = sy; self.vy = abs(self.vy)
            if self.y + ph > sy + sh:
                self.y = sy + sh - ph; self.vy = -abs(self.vy)

            self.position_window()
        self.root.after(16, self._movement_loop)

    # ── Window Helpers ─────────────────────────────────────────────────────
    def _update_current_screen(self):
        """Detect which screen the pet is currently on and cache it."""
        pw = max(self.canvas.winfo_width(), 1)
        ph = max(self.canvas.winfo_height(), 1)
        cx = int(self.x + pw / 2)
        cy = int(self.y + ph / 2)
        if self._monitors:
            self._current_screen = get_screen_for_point(cx, cy, self._monitors)
        else:
            # Fallback: use tkinter primary screen
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self._current_screen = (0, 0, sw, sh)

    def _get_current_screen(self):
        """Return current screen bounds, initialising if necessary."""
        if self._current_screen is None:
            self._update_current_screen()
        if self._current_screen is None:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            return (0, 0, sw, sh)
        return self._current_screen

    def position_window(self):
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")

    # ── Drag Bindings ──────────────────────────────────────────────────────
    def bind_events(self):
        self.canvas.bind("<ButtonPress-1>",   self._on_drag_start)
        self.canvas.bind("<B1-Motion>",       self._on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<ButtonPress-3>",   self._on_right_click)

    def _build_context_menu(self):
        """Build a tk.Menu that mirrors the system tray menu."""
        app = self.app
        cfg = self.cfg
        menu = tk.Menu(self.root, tearoff=0, font=("Microsoft YaHei UI", 10))

        # --- 切换桌宠 ---
        pet_menu = tk.Menu(menu, tearoff=0, font=("Microsoft YaHei UI", 10))
        for p in app._get_available_pets():
            pet_menu.add_command(
                label=("✓ " if p == cfg["pet"] else "   ") + p,
                command=lambda n=p: self.root.after(0, lambda: self.set_pet(n))
            )
        menu.add_cascade(label="切换桌宠", menu=pet_menu)

        # --- 桌宠大小 ---
        scale_menu = tk.Menu(menu, tearoff=0, font=("Microsoft YaHei UI", 10))
        for v in [round(x * 0.1, 1) for x in range(1, 21)]:
            scale_menu.add_command(
                label=("✓ " if abs(cfg["scale"] - v) < 0.05 else "   ") + f"x{v:.1f}",
                command=lambda val=v: self.root.after(0, lambda: self.set_scale(val))
            )
        menu.add_cascade(label="桌宠大小", menu=scale_menu)

        # --- 透明度 ---
        opacity_menu = tk.Menu(menu, tearoff=0, font=("Microsoft YaHei UI", 10))
        for v in [round(x * 0.1, 1) for x in range(1, 11)]:
            opacity_menu.add_command(
                label=("✓ " if abs(cfg["opacity"] - v) < 0.05 else "   ") + f"{int(v*100)}%",
                command=lambda val=v: self.root.after(0, lambda: self.set_opacity(val))
            )
        menu.add_cascade(label="透明度", menu=opacity_menu)

        # --- 速度 ---
        speed_menu = tk.Menu(menu, tearoff=0, font=("Microsoft YaHei UI", 10))
        for s in range(1, 11):
            speed_menu.add_command(
                label=("✓ " if cfg["speed"] == s else "   ") + f"速度 {s}",
                command=lambda val=s: self.root.after(0, lambda: self.set_speed(val))
            )
        menu.add_cascade(label="速度", menu=speed_menu)

        menu.add_separator()

        mf = cfg.get("mouse_follow", False)
        menu.add_command(
            label=("✓ " if mf else "   ") + "鼠标跟随",
            command=lambda: self.root.after(0, lambda: self.set_mouse_follow(not self.cfg.get("mouse_follow", False)))
        )

        aot = cfg.get("always_on_top", True)
        menu.add_command(
            label=("✓ " if aot else "   ") + "最上层显示",
            command=lambda: self.root.after(0, lambda: self.set_always_on_top(not self.cfg.get("always_on_top", True)))
        )

        menu.add_separator()

        menu.add_command(label="   调整状态权重",
                         command=lambda: self.root.after(0, lambda: WeightEditorDialog(self.root, self)))
        menu.add_command(label="   调整运动方向反转",
                         command=lambda: self.root.after(0, lambda: FlipEditorDialog(self.root, self)))
        menu.add_command(label="   创建桌宠",
                         command=lambda: self.root.after(0, lambda: PetCreatorDialog(self.root)))
        menu.add_command(label="   关于",
                         command=lambda: self.root.after(0, lambda: AboutDialog(self.root)))

        menu.add_separator()
        menu.add_command(label="   退出",
                         command=lambda: self.root.after(0, self.app._do_quit))

        return menu

    def _on_right_click(self, event):
        menu = self._build_context_menu()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_drag_start(self, event):
        self.prev_state = self.state
        self._drag_ox = event.x_root - self.x
        self._drag_oy = event.y_root - self.y
        # pause mouse follow loop during drag
        if self._mf_loop_id:
            self.root.after_cancel(self._mf_loop_id)
            self._mf_loop_id = None
        self._cancel_mf_leave_timer()
        self._enter_state(STATE_DRAG)

    def _on_drag_motion(self, event):
        self.x = event.x_root - self._drag_ox
        self.y = event.y_root - self._drag_oy
        self.position_window()

    def _on_drag_end(self, event):
        # Update which screen the pet is now on (user may have dragged to another monitor)
        self._update_current_screen()
        self._enter_state(self.prev_state if self.prev_state != STATE_DRAG else STATE_IDLE)
        # resume mouse follow loop after drag
        if self.cfg.get("mouse_follow"):
            self._mf_near_mouse = False
            self._mf_loop_tick()

    # ── Public API ─────────────────────────────────────────────────────────
    def set_pet(self, name):
        self.cfg["pet"] = name
        save_config(self.cfg)
        self.reload_pet()

    def set_scale(self, scale):
        self.cfg["scale"] = scale
        save_config(self.cfg)
        self.reload_pet()

    def set_opacity(self, opacity):
        self.cfg["opacity"] = opacity
        save_config(self.cfg)
        self.root.attributes("-alpha", opacity)

    def set_speed(self, speed):
        self.cfg["speed"] = speed
        save_config(self.cfg)

    def set_mouse_follow(self, val):
        self.cfg["mouse_follow"] = val
        save_config(self.cfg)
        if val:
            self._start_mouse_follow_loop()
        else:
            self._stop_mouse_follow_loop()
            if self.state in (STATE_MOVE, STATE_DYNAMIC):
                self._enter_state(STATE_IDLE)

    def set_always_on_top(self, val):
        self.cfg["always_on_top"] = val
        save_config(self.cfg)
        self.root.attributes("-topmost", val)

    def save_position(self):
        self.cfg["x"] = int(self.x)
        self.cfg["y"] = int(self.y)
        save_config(self.cfg)

    def run(self):
        self._movement_loop()
        # Initialise current screen after window is mapped (canvas has real size)
        self.root.after(100, self._update_current_screen)
        self.root.mainloop()

    def destroy(self):
        self.save_position()
        self.root.destroy()


# ── Pet Creator Dialog ────────────────────────────────────────────────────────
class PetCreatorDialog:
    def __init__(self, parent_root):
        self.win = tk.Toplevel(parent_root)
        self.win.title("创建桌宠")
        set_window_icon(self.win)
        self.win.resizable(False, False)
        self.win.grab_set()

        self._files = {
            "icon":    tk.StringVar(),
            "dynamic": tk.StringVar(),
            "drag":    tk.StringVar(),
        }
        self._idle_entries  = []
        self._move_entries  = []

        self._build_ui()

    def _build_ui(self):
        win = self.win
        pad = {"padx": 8, "pady": 4}

        # ── Name ──────────────────────────────────────────────────────────
        tk.Label(win, text="桌宠名:").grid(row=0, column=0, sticky="e", **pad)
        self.name_var = tk.StringVar()
        tk.Entry(win, textvariable=self.name_var, width=24).grid(row=0, column=1, columnspan=2, sticky="w", **pad)

        # ── Icon ──────────────────────────────────────────────────────────
        tk.Label(win, text="桌宠图标(.ico):").grid(row=1, column=0, sticky="e", **pad)
        tk.Entry(win, textvariable=self._files["icon"], width=24).grid(row=1, column=1, **pad)
        tk.Button(win, text="浏览", command=lambda: self._browse("icon", [("ICO","*.ico")])).grid(row=1, column=2, **pad)

        # ── Dynamic ───────────────────────────────────────────────────────
        tk.Label(win, text="动感状态(.gif):").grid(row=2, column=0, sticky="e", **pad)
        tk.Entry(win, textvariable=self._files["dynamic"], width=24).grid(row=2, column=1, **pad)
        tk.Button(win, text="浏览", command=lambda: self._browse("dynamic", [("GIF","*.gif")])).grid(row=2, column=2, **pad)
        tk.Label(win, text="权重:").grid(row=2, column=3, **pad)
        self.dyn_weight = tk.IntVar(value=3)
        tk.Spinbox(win, from_=1, to=99, textvariable=self.dyn_weight, width=4).grid(row=2, column=4, **pad)

        # ── Drag ──────────────────────────────────────────────────────────
        tk.Label(win, text="拖拽状态(.gif):").grid(row=3, column=0, sticky="e", **pad)
        tk.Entry(win, textvariable=self._files["drag"], width=24).grid(row=3, column=1, **pad)
        tk.Button(win, text="浏览", command=lambda: self._browse("drag", [("GIF","*.gif")])).grid(row=3, column=2, **pad)

        # ── Idle ──────────────────────────────────────────────────────────
        tk.Label(win, text="─── 非移动状态(idle) ───").grid(row=4, column=0, columnspan=5, **pad)
        self._idle_frame = tk.Frame(win)
        self._idle_frame.grid(row=5, column=0, columnspan=5, **pad)
        self._add_idle_row()
        tk.Button(win, text="+ 添加idle图", command=self._add_idle_row).grid(row=6, column=0, columnspan=2, **pad)

        # ── Move ──────────────────────────────────────────────────────────
        tk.Label(win, text="─── 移动状态(move) ───").grid(row=7, column=0, columnspan=5, **pad)
        self._move_frame = tk.Frame(win)
        self._move_frame.grid(row=8, column=0, columnspan=5, **pad)
        self._add_move_row()
        tk.Button(win, text="+ 添加move图", command=self._add_move_row).grid(row=9, column=0, columnspan=2, **pad)

        # ── Buttons ───────────────────────────────────────────────────────
        tk.Button(win, text="保存", command=self._save, bg="#4caf50", fg="white").grid(row=10, column=3, **pad)
        tk.Button(win, text="取消", command=self.win.destroy).grid(row=10, column=4, **pad)

    def _browse(self, key, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self._files[key].set(path)

    def _browse_var(self, var, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            var.set(path)

    def _add_idle_row(self):
        f = self._idle_frame
        row = len(self._idle_entries)
        path_var   = tk.StringVar()
        weight_var = tk.IntVar(value=2)
        tk.Label(f, text=f"idle {row+1}:").grid(row=row, column=0)
        tk.Entry(f, textvariable=path_var, width=24).grid(row=row, column=1)
        tk.Button(f, text="浏览", command=lambda v=path_var: self._browse_var(v, [("GIF","*.gif")])).grid(row=row, column=2)
        tk.Label(f, text="权重:").grid(row=row, column=3)
        tk.Spinbox(f, from_=1, to=99, textvariable=weight_var, width=4).grid(row=row, column=4)
        self._idle_entries.append((path_var, weight_var))

    def _add_move_row(self):
        f = self._move_frame
        row = len(self._move_entries)
        path_var    = tk.StringVar()
        weight_var  = tk.IntVar(value=1)
        flip_var    = tk.BooleanVar(value=False)
        dir_var     = tk.StringVar(value="left")
        tk.Label(f, text=f"move {row+1}:").grid(row=row, column=0)
        tk.Entry(f, textvariable=path_var, width=22).grid(row=row, column=1)
        tk.Button(f, text="浏览", command=lambda v=path_var: self._browse_var(v, [("GIF","*.gif")])).grid(row=row, column=2)
        tk.Label(f, text="权重:").grid(row=row, column=3)
        tk.Spinbox(f, from_=1, to=99, textvariable=weight_var, width=4).grid(row=row, column=4)
        tk.Checkbutton(f, text="方向反转", variable=flip_var).grid(row=row, column=5)
        tk.Label(f, text="默认方向:").grid(row=row, column=6)
        ttk.Combobox(f, textvariable=dir_var, values=["left","right"], width=5, state="readonly").grid(row=row, column=7)
        self._move_entries.append((path_var, weight_var, flip_var, dir_var))

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("错误", "请填写桌宠名"); return

        pet_dir = os.path.join(PETS_DIR, name)
        os.makedirs(pet_dir, exist_ok=True)

        def copy(src, dst):
            if src and os.path.exists(src):
                shutil.copy2(src, dst)

        # icon
        copy(self._files["icon"].get(), os.path.join(pet_dir, f"{name}.ico"))
        # dynamic
        copy(self._files["dynamic"].get(), os.path.join(pet_dir, f"{name}.gif"))
        # drag
        copy(self._files["drag"].get(), os.path.join(pet_dir, "drag.gif"))

        # idle
        idle_weights = {}
        valid_idle = [(p.get(), w.get()) for p, w in self._idle_entries if p.get() and os.path.exists(p.get())]
        if len(valid_idle) == 1:
            copy(valid_idle[0][0], os.path.join(pet_dir, "idle.gif"))
            idle_weights = {"idle_weight": [valid_idle[0][1]]}
        else:
            for i, (p, w) in enumerate(valid_idle, 1):
                copy(p, os.path.join(pet_dir, f"idle{i}.gif"))
            idle_weights = {"idle_weight": [w for _, w in valid_idle]}

        # move
        move_weights = {}
        flip_info    = {}
        valid_move = [(p.get(), w.get(), fl.get(), dr.get())
                      for p, w, fl, dr in self._move_entries if p.get() and os.path.exists(p.get())]
        if len(valid_move) == 1:
            copy(valid_move[0][0], os.path.join(pet_dir, "move.gif"))
            move_weights = {"move_weight": [valid_move[0][1]]}
            if valid_move[0][2]:
                flip_info["move"] = {"enabled": True, "default_dir": valid_move[0][3]}
        else:
            for i, (p, w, fl, dr) in enumerate(valid_move, 1):
                copy(p, os.path.join(pet_dir, f"move{i}.gif"))
                if fl:
                    flip_info[f"move{i}"] = {"enabled": True, "default_dir": dr}
            move_weights = {"move_weight": [w for _, w, *_ in valid_move]}

        # weights.json
        weights = {
            "dynamic_weight": self.dyn_weight.get(),
            **idle_weights,
            **move_weights,
        }
        with open(os.path.join(pet_dir, "weights.json"), "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=2)

        # flip.json
        if flip_info:
            with open(os.path.join(pet_dir, "flip.json"), "w", encoding="utf-8") as f:
                json.dump(flip_info, f, indent=2)

        messagebox.showinfo("成功", f"桌宠 '{name}' 已保存！")
        self.win.destroy()


# ── Weight Editor Dialog ──────────────────────────────────────────────────────
class WeightEditorDialog:
    """
    Dialog for editing state weights of the current pet.
    Edits:
      - dynamic_weight  (single int)
      - idle_weight     (list of ints, one per idle variant)
      - move_weight     (list of ints, one per move variant)
    Writes changes back to Pets/<name>/weights.json and hot-reloads the pet.
    """

    def __init__(self, parent_root, pet_win: "PetWindow"):
        self.pet_win = pet_win
        self.win = tk.Toplevel(parent_root)
        self.win.title("调整状态权重")
        set_window_icon(self.win)
        self.win.resizable(False, False)
        self.win.grab_set()
        self._build_ui()

    def _build_ui(self):
        win  = self.win
        pd   = self.pet_win.pet_data
        pad  = {"padx": 10, "pady": 5}

        # ── Title ─────────────────────────────────────────────────────────
        tk.Label(win, text=f"桌宠：{pd.name}", font=_FONT_BOLD).grid(
            row=0, column=0, columnspan=3, pady=(10, 4))

        tk.Label(win, text="说明：权重为正整数，值越大该状态出现概率越高。",
                 fg="gray", font=_FONT_SMALL).grid(row=1, column=0, columnspan=3, padx=10, pady=(0, 8))

        row = 2

        # ── Dynamic weight ────────────────────────────────────────────────
        tk.Label(win, text="动感状态 权重：", anchor="e").grid(row=row, column=0, sticky="e", **pad)
        self._dyn_var = tk.IntVar(value=pd.dynamic_weight)
        tk.Spinbox(win, from_=1, to=999, textvariable=self._dyn_var, width=6).grid(
            row=row, column=1, sticky="w", **pad)
        row += 1

        # ── Separator ─────────────────────────────────────────────────────
        ttk.Separator(win, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=10, pady=4)
        row += 1

        # ── Idle weights ──────────────────────────────────────────────────
        self._idle_vars = []
        idle_count = len(pd.idle_variants)
        if idle_count == 0:
            tk.Label(win, text="非移动状态：（无图）", fg="gray").grid(
                row=row, column=0, columnspan=3, **pad)
            row += 1
        elif idle_count == 1:
            tk.Label(win, text="非移动状态 权重：", anchor="e", font=_FONT_NORMAL).grid(
                row=row, column=0, sticky="e", **pad)
            v = tk.IntVar(value=pd.idle_weights[0] if pd.idle_weights else 2)
            tk.Spinbox(win, from_=1, to=999, textvariable=v, width=6, font=_FONT_NORMAL).grid(
                row=row, column=1, sticky="w", **pad)
            self._idle_vars.append(v)
            row += 1
        else:
            tk.Label(win, text="非移动状态（多图）：", font=_FONT_BOLD).grid(
                row=row, column=0, columnspan=3, sticky="w", padx=10)
            row += 1
            for i in range(idle_count):
                tk.Label(win, text=f"  idle{i+1} 权重：", anchor="e").grid(
                    row=row, column=0, sticky="e", **pad)
                w_val = pd.idle_weights[i] if i < len(pd.idle_weights) else 2
                v = tk.IntVar(value=w_val)
                tk.Spinbox(win, from_=1, to=999, textvariable=v, width=6).grid(
                    row=row, column=1, sticky="w", **pad)
                self._idle_vars.append(v)
                row += 1

        # ── Separator ─────────────────────────────────────────────────────
        ttk.Separator(win, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=10, pady=4)
        row += 1

        # ── Move weights ──────────────────────────────────────────────────
        self._move_vars = []
        move_count = len(pd.move_variants)
        if move_count == 0:
            tk.Label(win, text="移动状态：（无图）", fg="gray").grid(
                row=row, column=0, columnspan=3, **pad)
            row += 1
        elif move_count == 1:
            tk.Label(win, text="移动状态 权重：", anchor="e", font=_FONT_NORMAL).grid(
                row=row, column=0, sticky="e", **pad)
            v = tk.IntVar(value=pd.move_weights[0] if pd.move_weights else 1)
            tk.Spinbox(win, from_=1, to=999, textvariable=v, width=6, font=_FONT_NORMAL).grid(
                row=row, column=1, sticky="w", **pad)
            self._move_vars.append(v)
            row += 1
        else:
            tk.Label(win, text="移动状态（多图）：", font=_FONT_BOLD).grid(
                row=row, column=0, columnspan=3, sticky="w", padx=10)
            row += 1
            for i in range(move_count):
                tk.Label(win, text=f"  move{i+1} 权重：", anchor="e").grid(
                    row=row, column=0, sticky="e", **pad)
                w_val = pd.move_weights[i] if i < len(pd.move_weights) else 1
                v = tk.IntVar(value=w_val)
                tk.Spinbox(win, from_=1, to=999, textvariable=v, width=6).grid(
                    row=row, column=1, sticky="w", **pad)
                self._move_vars.append(v)
                row += 1

        # ── Preview label ─────────────────────────────────────────────────
        self._preview_label = tk.Label(win, text="", fg="#555", font=("Courier", 8))
        self._preview_label.grid(row=row, column=0, columnspan=3, padx=10, pady=(4, 0))
        row += 1
        self._update_preview()

        # bind all spinboxes to refresh preview
        for var in [self._dyn_var] + self._idle_vars + self._move_vars:
            var.trace_add("write", lambda *_: self._update_preview())

        # ── Buttons ───────────────────────────────────────────────────────
        btn_frame = tk.Frame(win)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=10)
        tk.Button(btn_frame, text="保存并应用", bg="#4caf50", fg="white",
                  command=self._save).pack(side="left", padx=8)
        tk.Button(btn_frame, text="取消",
                  command=self.win.destroy).pack(side="left", padx=8)

    def _safe_int(self, var, fallback=1):
        try:
            v = var.get()
            return max(1, int(v))
        except Exception:
            return fallback

    def _update_preview(self):
        """Show approximate probabilities."""
        dw = self._safe_int(self._dyn_var)
        iw = sum(self._safe_int(v) for v in self._idle_vars) if self._idle_vars else 0
        mw = sum(self._safe_int(v) for v in self._move_vars) if self._move_vars else 0
        total = dw + iw + mw
        if total == 0:
            self._preview_label.config(text="")
            return
        lines = [
            f"动感 {dw/total*100:.1f}%",
            f"非移动 {iw/total*100:.1f}%",
            f"移动 {mw/total*100:.1f}%",
        ]
        self._preview_label.config(text="  概率预览：" + "  |  ".join(lines))

    def _save(self):
        pd   = self.pet_win.pet_data
        path = os.path.join(pd.dir, "weights.json")

        # read existing to preserve any extra keys
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        existing["dynamic_weight"] = self._safe_int(self._dyn_var)
        if self._idle_vars:
            existing["idle_weight"] = [self._safe_int(v) for v in self._idle_vars]
        if self._move_vars:
            existing["move_weight"] = [self._safe_int(v) for v in self._move_vars]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        # hot-reload the pet so new weights take effect immediately
        self.pet_win.reload_pet()
        messagebox.showinfo("成功", "权重已保存并应用！", parent=self.win)
        self.win.destroy()


# ── Flip Editor Dialog ────────────────────────────────────────────────────────
class FlipEditorDialog:
    """
    Dialog for editing move-direction flip settings of the current pet.

    For every move variant (move.gif / move1.gif / move2.gif …) the user can:
      • Toggle "启用方向反转" on/off
      • Choose "默认朝向方向": 左 or 右
          默认方向=左 → 向左运动时不翻转，向右运动时翻转
          默认方向=右 → 向右运动时不翻转，向左运动时翻转

    Settings are written to Pets/<name>/flip.json and the pet is hot-reloaded.
    """

    def __init__(self, parent_root, pet_win: "PetWindow"):
        self.pet_win = pet_win
        self.win = tk.Toplevel(parent_root)
        self.win.title("调整运动方向反转")
        set_window_icon(self.win)
        self.win.resizable(False, False)
        self.win.grab_set()
        self._rows: list[dict] = []   # [{key, enabled_var, dir_var}, …]
        self._build_ui()

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _variant_key(index: int, total: int) -> str:
        """Return the flip.json key for a move variant."""
        return "move" if total == 1 else f"move{index + 1}"

    # ── build ─────────────────────────────────────────────────────────────────
    def _build_ui(self):
        win = self.win
        pd  = self.pet_win.pet_data
        pad = {"padx": 10, "pady": 5}

        # ── header ────────────────────────────────────────────────────────
        tk.Label(win, text=f"桌宠：{pd.name}",
                 font=("Helvetica", 12, "bold")).grid(
            row=0, column=0, columnspan=4, pady=(12, 2))

        hint = (
            '说明：启用后，桌宠向"非默认方向"运动时图片会水平翻转。\n'
            '  默认方向=左 → 向左走不翻转，向右走翻转\n'
            '  默认方向=右 → 向右走不翻转，向左走翻转'
        )
        tk.Label(win, text=hint, fg="#555", justify="left",
                 font=("Helvetica", 8)).grid(
            row=1, column=0, columnspan=4, padx=12, pady=(0, 8), sticky="w")

        move_count = len(pd.move_variants)

        if move_count == 0:
            tk.Label(win, text="当前桌宠没有移动状态图，无法配置。",
                     fg="gray").grid(row=2, column=0, columnspan=4, **pad)
            tk.Button(win, text="关闭", command=self.win.destroy).grid(
                row=3, column=0, columnspan=4, pady=10)
            return

        # ── column headers ────────────────────────────────────────────────
        tk.Label(win, text="图片",       font=("Helvetica", 9, "bold"), width=10).grid(row=2, column=0, **pad)
        tk.Label(win, text="启用反转",   font=("Helvetica", 9, "bold")).grid(row=2, column=1, **pad)
        tk.Label(win, text="默认朝向",   font=("Helvetica", 9, "bold")).grid(row=2, column=2, **pad)
        tk.Label(win, text="当前效果预览", font=("Helvetica", 9, "bold")).grid(row=2, column=3, padx=(0, 12))

        ttk.Separator(win, orient="horizontal").grid(
            row=3, column=0, columnspan=4, sticky="ew", padx=8, pady=2)

        # ── one row per move variant ──────────────────────────────────────
        for i in range(move_count):
            key = self._variant_key(i, move_count)
            existing = pd.move_flip_info.get(key, {})

            enabled_var = tk.BooleanVar(value=existing.get("enabled", False))
            dir_var     = tk.StringVar(value=existing.get("default_dir", "left"))

            label_text = "move.gif" if move_count == 1 else f"move{i+1}.gif"
            r = 4 + i

            tk.Label(win, text=label_text, anchor="e").grid(row=r, column=0, sticky="e", **pad)

            cb = tk.Checkbutton(win, variable=enabled_var,
                                command=self._make_row_refresh(i))
            cb.grid(row=r, column=1, **pad)

            dir_combo = ttk.Combobox(win, textvariable=dir_var,
                                     values=["left", "right"],
                                     width=6, state="readonly")
            dir_combo.grid(row=r, column=2, **pad)
            dir_combo.bind("<<ComboboxSelected>>", lambda e, idx=i: self._refresh_preview(idx))

            preview_lbl = tk.Label(win, text="", fg="#337", width=22, anchor="w",
                                   font=("Helvetica", 8))
            preview_lbl.grid(row=r, column=3, padx=(0, 12))

            self._rows.append({
                "key":         key,
                "enabled_var": enabled_var,
                "dir_var":     dir_var,
                "preview_lbl": preview_lbl,
            })
            self._refresh_preview(i)

        # ── buttons ───────────────────────────────────────────────────────
        sep_row = 4 + move_count
        ttk.Separator(win, orient="horizontal").grid(
            row=sep_row, column=0, columnspan=4, sticky="ew", padx=8, pady=(8, 0))

        btn_frame = tk.Frame(win)
        btn_frame.grid(row=sep_row + 1, column=0, columnspan=4, pady=10)
        tk.Button(btn_frame, text="保存并应用", bg="#4caf50", fg="white",
                  command=self._save).pack(side="left", padx=8)
        tk.Button(btn_frame, text="取消",
                  command=self.win.destroy).pack(side="left", padx=8)

    # ── preview ───────────────────────────────────────────────────────────────
    def _make_row_refresh(self, idx):
        return lambda: self._refresh_preview(idx)

    def _refresh_preview(self, idx):
        row      = self._rows[idx]
        enabled  = row["enabled_var"].get()
        default  = row["dir_var"].get()

        if not enabled:
            text = "⬜ 未启用（始终不翻转）"
        else:
            if default == "left":
                text = "← 左走正常  |  → 右走翻转"
            else:
                text = "→ 右走正常  |  ← 左走翻转"

        row["preview_lbl"].config(text=text)

    # ── save ──────────────────────────────────────────────────────────────────
    def _save(self):
        pd   = self.pet_win.pet_data
        path = os.path.join(pd.dir, "flip.json")

        # read existing (preserve unknown keys / comments)
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        # remove stale _comment key if present
        existing.pop("_comment", None)

        for row in self._rows:
            key     = row["key"]
            enabled = row["enabled_var"].get()
            default = row["dir_var"].get()
            if enabled:
                existing[key] = {"enabled": True, "default_dir": default}
            else:
                # keep the entry but mark disabled (so UI re-opens correctly)
                existing[key] = {"enabled": False, "default_dir": default}

        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        # hot-reload so changes take effect immediately
        self.pet_win.reload_pet()
        messagebox.showinfo("成功", "运动方向反转设置已保存并应用！", parent=self.win)
        self.win.destroy()


# ── About Dialog ──────────────────────────────────────────────────────────────
class AboutDialog:
    def __init__(self, parent_root):
        win = tk.Toplevel(parent_root)
        win.title(f"关于 {APP_NAME}")
        set_window_icon(win)
        win.resizable(False, False)
        win.grab_set()

        pad = {"padx": 16, "pady": 6}

        tk.Label(win, text=APP_NAME, font=_FONT_LARGE).pack(**pad)
        tk.Label(win, text=f"版本: {VERSION}", font=_FONT_NORMAL).pack(**pad)
        tk.Label(win, text=f"作者: {AUTHOR}  ({AUTHOR_EMAIL})", font=_FONT_NORMAL).pack(**pad)

        link = tk.Label(win, text=GITHUB_URL, fg="blue", cursor="hand2", font=_FONT_NORMAL)
        link.pack(**pad)
        link.bind("<Button-1>", lambda e: self._open_url(GITHUB_URL))

        tk.Button(win, text="检查更新", font=_FONT_NORMAL, command=lambda: self._check_update(win)).pack(pady=4)
        tk.Button(win, text="关闭", font=_FONT_NORMAL, command=win.destroy).pack(pady=8)

    @staticmethod
    def _open_url(url):
        import webbrowser
        webbrowser.open(url)

    @staticmethod
    def _check_update(win):
        messagebox.showinfo("更新", f"请访问 GitHub 获取最新版本:\n{GITHUB_URL}", parent=win)


# ── System Tray App ───────────────────────────────────────────────────────────
class TrayApp:
    def __init__(self):
        self.cfg = load_config()
        self.pet_win: PetWindow = None
        self.tray: pystray.Icon = None

    def _get_available_pets(self):
        if not os.path.isdir(PETS_DIR):
            return []
        return [d for d in os.listdir(PETS_DIR) if os.path.isdir(os.path.join(PETS_DIR, d))]

    def _pet_submenu(self):
        pets = self._get_available_pets()
        cur  = self.cfg["pet"]
        items = []
        for p in pets:
            name = p
            checked = (p == cur)
            items.append(item(name, self._make_pet_setter(name), checked=lambda _, n=name: self.cfg["pet"] == n))
        return Menu(*items)

    def _make_pet_setter(self, name):
        def fn(icon, menu_item):
            self.cfg["pet"] = name
            if self.pet_win:
                self.pet_win.root.after(0, lambda: self.pet_win.set_pet(name))
        return fn

    def _scale_submenu(self):
        items = []
        for v in [round(x * 0.1, 1) for x in range(1, 21)]:
            val = v
            items.append(item(f"x{val:.1f}", self._make_scale_setter(val),
                              checked=lambda _, v=val: abs(self.cfg["scale"] - v) < 0.05))
        return Menu(*items)

    def _make_scale_setter(self, val):
        def fn(icon, mi):
            if self.pet_win:
                self.pet_win.root.after(0, lambda: self.pet_win.set_scale(val))
        return fn

    def _opacity_submenu(self):
        items = []
        for v in [round(x * 0.1, 1) for x in range(1, 11)]:
            val = v
            items.append(item(f"{int(val*100)}%", self._make_opacity_setter(val),
                              checked=lambda _, v=val: abs(self.cfg["opacity"] - v) < 0.05))
        return Menu(*items)

    def _make_opacity_setter(self, val):
        def fn(icon, mi):
            if self.pet_win:
                self.pet_win.root.after(0, lambda: self.pet_win.set_opacity(val))
        return fn

    def _speed_submenu(self):
        speeds = list(range(1, 11))
        items = []
        for s in speeds:
            sp = s
            items.append(item(f"速度 {sp}", self._make_speed_setter(sp),
                              checked=lambda _, v=sp: self.cfg["speed"] == v))
        return Menu(*items)

    def _make_speed_setter(self, val):
        def fn(icon, mi):
            if self.pet_win:
                self.pet_win.root.after(0, lambda: self.pet_win.set_speed(val))
        return fn

    def _toggle_mouse_follow(self, icon, mi):
        new_val = not self.cfg.get("mouse_follow", False)
        self.cfg["mouse_follow"] = new_val
        if self.pet_win:
            self.pet_win.root.after(0, lambda: self.pet_win.set_mouse_follow(new_val))

    def _toggle_always_on_top(self, icon, mi):
        new_val = not self.cfg.get("always_on_top", True)
        self.cfg["always_on_top"] = new_val
        if self.pet_win:
            self.pet_win.root.after(0, lambda: self.pet_win.set_always_on_top(new_val))

    def _open_weight_editor(self, icon, mi):
        if self.pet_win:
            self.pet_win.root.after(0, lambda: WeightEditorDialog(self.pet_win.root, self.pet_win))

    def _open_flip_editor(self, icon, mi):
        if self.pet_win:
            self.pet_win.root.after(0, lambda: FlipEditorDialog(self.pet_win.root, self.pet_win))

    def _open_creator(self, icon, mi):
        if self.pet_win:
            self.pet_win.root.after(0, lambda: PetCreatorDialog(self.pet_win.root))

    def _open_about(self, icon, mi):
        if self.pet_win:
            self.pet_win.root.after(0, lambda: AboutDialog(self.pet_win.root))

    def _quit(self, icon, mi):
        if self.pet_win:
            self.pet_win.root.after(0, self._do_quit)

    def _do_quit(self):
        if self.pet_win:
            self.pet_win.save_position()
            self.pet_win.root.destroy()
        if self.tray:
            self.tray.stop()

    def _build_menu(self):
        return Menu(
            item("切换桌宠",    Menu(self._pet_submenu)),
            item("桌宠大小",    Menu(self._scale_submenu)),
            item("透明度",      Menu(self._opacity_submenu)),
            item("速度",        Menu(self._speed_submenu)),
            item("鼠标跟随",    self._toggle_mouse_follow,
                 checked=lambda _: self.cfg.get("mouse_follow", False)),
            item("最上层显示",  self._toggle_always_on_top,
                 checked=lambda _: self.cfg.get("always_on_top", True)),
            Menu.SEPARATOR,
            item("调整状态权重",     self._open_weight_editor),
            item("调整运动方向反转", self._open_flip_editor),
            item("创建桌宠",         self._open_creator),
            item("关于",        self._open_about),
            Menu.SEPARATOR,
            item("退出",        self._quit),
        )

    def _load_tray_icon(self):
        if os.path.exists(APP_ICO):
            try:
                return Image.open(APP_ICO).convert("RGBA")
            except Exception:
                pass
        # fallback: simple colored square
        img = Image.new("RGBA", (64, 64), (100, 180, 255, 255))
        return img

    def run(self):
        # Start tray in background thread
        tray_img = self._load_tray_icon()
        self.tray = pystray.Icon(APP_NAME, tray_img, APP_NAME, menu=self._build_menu())

        tray_thread = threading.Thread(target=self.tray.run, daemon=True)
        tray_thread.start()

        # Build pet window in main thread (tkinter requirement)
        self.pet_win = PetWindow(self)
        self.pet_win.run()


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = TrayApp()
    app.run()
