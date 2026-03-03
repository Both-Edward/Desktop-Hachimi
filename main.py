"""
Desktop Hachimi – main entry point v1.1.2
Refactored: frontend/backend separation for Windows / Linux (KDE) / macOS support.
  core/            – pure logic (config, gif loading, pet data)
  platform_utils/  – OS-specific helpers (autostart, DPI awareness, trash)
  ui/              – all tkinter UI (pet window, dialogs, music player)
"""

import sys
import os
import json
import random
import shutil
import math
import threading
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import pystray
from pystray import MenuItem as item, Menu

# ── Core / Platform / UI imports ─────────────────────────────────────────────
from core.config import (
    VERSION, APP_NAME, AUTHOR, AUTHOR_EMAIL, GITHUB_URL,
    PETS_DIR, ICO_DIR, MUSIC_DIR, APP_ICO,
    FONT_NORMAL, FONT_BOLD, FONT_LARGE, FONT_SMALL,
    load_config, save_config, get_available_pets,
)
from core.pet_data import PetData
from compat.autostart import get_autostart, set_autostart
from compat.dpi import enable_dpi_awareness, get_monitors
from compat.trash import move_to_trash
from ui.helpers import set_window_icon, load_ico_image, get_screen_for_point
from ui.music_player import MusicPlayerDialog, MusicPlayer

_FONT_NORMAL = FONT_NORMAL
_FONT_BOLD   = FONT_BOLD
_FONT_LARGE  = FONT_LARGE
_FONT_SMALL  = FONT_SMALL

# ── DPI ───────────────────────────────────────────────────────────────────────
enable_dpi_awareness()

# ── Pet state constants ───────────────────────────────────────────────────────
STATE_DYNAMIC = "dynamic"
STATE_IDLE    = "idle"
STATE_MOVE    = "move"
STATE_DRAG    = "drag"

# ── GitHub update helpers ─────────────────────────────────────────────────────
GITHUB_OWNER      = "Edward-EH-Holmes"
GITHUB_REPO       = "Desktop-Hachimi"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES   = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0,)


def fetch_latest_release():
    req = urllib.request.Request(
        GITHUB_API_LATEST,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": f"{APP_NAME}/{VERSION}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
#  PetWindow  – the transparent sprite overlay
# ══════════════════════════════════════════════════════════════════════════════
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

        try:
            import tkinter.font as tkfont
            tkfont.nametofont("TkDefaultFont").configure(family="Microsoft YaHei UI", size=10)
            tkfont.nametofont("TkTextFont").configure(family="Microsoft YaHei UI", size=10)
            tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=10)
        except Exception:
            pass

        if os.path.exists(APP_ICO):
            try:
                self.root.iconbitmap(APP_ICO)
            except Exception:
                pass

        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack()
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")

        # state
        self.state              = STATE_IDLE
        self.prev_state         = STATE_IDLE
        self._frame_idx         = 0
        self._after_id          = None
        self.current_frames     = []
        self._current_move_key  = None
        self._flipped_cache     = {}
        # movement
        self.vx, self.vy        = 0.0, 0.0
        self.going_right        = True
        self.move_target        = None
        self._move_timer        = None
        # mouse follow
        self._mf_loop_id        = None
        self._mf_leave_id       = None
        self._mf_near_mouse     = False
        # drag
        self._drag_ox = self._drag_oy = 0
        # position
        self.x = float(self.cfg.get("x", 100))
        self.y = float(self.cfg.get("y", 100))
        # multi-monitor
        self._monitors       = get_monitors()
        self._current_screen = None
        # music player (singleton per pet window)
        self._music_player   = None
        self._music_dialog   = None

        self.pet_data: PetData = None
        # music-driven state
        self._music_was_playing: bool = False  # tracks last known playback state
        self._music_lock: bool = False          # True while music is forcing dynamic

        self.load_pet(initial=True)
        self.position_window()
        self.bind_events()
        self.start_state_machine()

    # ── Pet Loading ────────────────────────────────────────────────────────
    def load_pet(self, initial=False):
        self.pet_data = PetData(self.cfg["pet"], self.cfg["scale"])
        self._enter_state(STATE_DYNAMIC if initial else STATE_IDLE)

    def reload_pet(self):
        for tid in (self._after_id, self._move_timer):
            if tid:
                self.root.after_cancel(tid)
        self._after_id = self._move_timer = None
        self._stop_mouse_follow_loop()
        self._flipped_cache.clear()
        self.load_pet(initial=False)
        if self.cfg.get("mouse_follow"):
            self._start_mouse_follow_loop()

    # ── State Machine ──────────────────────────────────────────────────────
    def start_state_machine(self):
        self.root.after(5000, self._state_tick)
        self.root.after(500,  self._music_state_tick)   # start music listener
        if self.cfg.get("mouse_follow"):
            self._start_mouse_follow_loop()

    def _music_state_tick(self):
        """Poll the shared MusicPlayer every 500 ms.
        • While music is playing  → force / keep STATE_DYNAMIC.
        • When music just stopped → release the lock and pick a random state.
        """
        player = self._music_player           # may be None before dialog opened
        is_playing = bool(player and player.playing)

        if is_playing:
            # Music is playing: lock pet in dynamic state
            if not self._music_lock:
                self._music_lock = True
            if self.state != STATE_DYNAMIC and self.state != STATE_DRAG:
                self._enter_state(STATE_DYNAMIC)
        else:
            if self._music_lock:
                # Music just stopped – release lock and randomise state
                self._music_lock = False
                if self.state != STATE_DRAG:
                    self._autonomous_logic()

        self._music_was_playing = is_playing
        self.root.after(500, self._music_state_tick)

    def _state_tick(self):
        if self.state != STATE_DRAG and not self.cfg.get("mouse_follow"):
            if not self._music_lock:           # don't interrupt music-driven state
                self._autonomous_logic()
        self.root.after(5000, self._state_tick)

    def _autonomous_logic(self):
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
            angle = random.uniform(0, 2 * math.pi)
            speed = self.cfg.get("speed", 3)
            self.vx, self.vy = math.cos(angle) * speed, math.sin(angle) * speed
            self.going_right = self.vx >= 0
            self.move_target = None
            if self._move_timer:
                self.root.after_cancel(self._move_timer)
            self._move_timer = self.root.after(random.randint(3, 8) * 1000, self._stop_moving)

    def _stop_moving(self):
        if self.state == STATE_MOVE:
            self._enter_state(STATE_IDLE)

    # ── Mouse Follow ──────────────────────────────────────────────────────
    def _start_mouse_follow_loop(self):
        self._mf_near_mouse = False
        self._cancel_mf_leave_timer()
        self._mf_loop_tick()

    def _stop_mouse_follow_loop(self):
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
        if not self.cfg.get("mouse_follow") or self.state == STATE_DRAG:
            self._mf_loop_id = None
            return
        mx, my = self.root.winfo_pointerx(), self.root.winfo_pointery()
        pw = max(self.canvas.winfo_width(), 1)
        ph = max(self.canvas.winfo_height(), 1)
        cx, cy = self.x + pw / 2, self.y + ph / 2
        dist = math.hypot(mx - cx, my - cy)
        near = max(pw, ph) / 2 + 10
        if dist < near:
            if not self._mf_near_mouse:
                self._mf_near_mouse = True
                self._cancel_mf_leave_timer()
                self.vx = self.vy = 0.0
                if self.state != STATE_DYNAMIC:
                    self._enter_state(STATE_DYNAMIC)
            else:
                self.vx = self.vy = 0.0
        else:
            if self._mf_near_mouse:
                self._mf_near_mouse = False
                self._cancel_mf_leave_timer()
                self._mf_leave_id = self.root.after(1000, self._mf_leave_dynamic)
            else:
                if self.state != STATE_MOVE and not self._music_lock:
                    self._enter_state(STATE_MOVE)
                speed = self.cfg.get("speed", 3)
                d = max(dist, 1)
                self.vx, self.vy = (mx - cx) / d * speed, (my - cy) / d * speed
                self.going_right = self.vx >= 0
                self.move_target = (mx, my)
        self._mf_loop_id = self.root.after(50, self._mf_loop_tick)

    def _mf_leave_dynamic(self):
        self._mf_leave_id = None
        if self.cfg.get("mouse_follow") and self.state != STATE_DRAG:
            if self.state != STATE_MOVE and not self._music_lock:
                self._enter_state(STATE_MOVE)

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
            if not pd.move_variants:
                self.current_frames = pd.dynamic_frames or pd.pick_idle()
            else:
                mc  = len(pd.move_variants)
                idx = random.choices(range(mc), weights=pd.move_weights, k=1)[0]
                self.current_frames = pd.move_variants[idx]
                self._current_move_key = "move" if mc == 1 else f"move{idx+1}"
        elif state == STATE_DRAG:
            self.current_frames = pd.drag_frames or pd.dynamic_frames or pd.pick_idle()
        self._frame_idx = 0
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._animate()

    # ── Animation ──────────────────────────────────────────────────────────
    def _get_flipped_frames(self, key):
        if key not in self._flipped_cache:
            self._flipped_cache[key] = [
                (ImageTk.PhotoImage(pil.transpose(Image.FLIP_LEFT_RIGHT)), dur)
                for _, dur, pil in self.current_frames
            ]
        return self._flipped_cache[key]

    def _animate(self):
        if not self.current_frames:
            self._after_id = self.root.after(100, self._animate)
            return
        idx = self._frame_idx % len(self.current_frames)
        need_flip = (self.state == STATE_MOVE and self._current_move_key is not None
                     and self.pet_data.should_flip(self._current_move_key, self.going_right))
        if need_flip:
            frames = self._get_flipped_frames(self._current_move_key)
            photo, duration = frames[idx % len(frames)]
        else:
            photo, duration, *_ = self.current_frames[idx]
        self.canvas.config(width=photo.width(), height=photo.height())
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
            sx, sy, sw, sh = self._get_current_screen()
            if self.x < sx:
                self.x = sx;          self.vx = abs(self.vx);  self.going_right = True
            if self.x + pw > sx + sw:
                self.x = sx+sw-pw;    self.vx = -abs(self.vx); self.going_right = False
            if self.y < sy:
                self.y = sy;          self.vy = abs(self.vy)
            if self.y + ph > sy + sh:
                self.y = sy+sh-ph;    self.vy = -abs(self.vy)
            self.position_window()
        self.root.after(16, self._movement_loop)

    # ── Screen Helpers ─────────────────────────────────────────────────────
    def _update_current_screen(self):
        pw = max(self.canvas.winfo_width(), 1)
        ph = max(self.canvas.winfo_height(), 1)
        cx, cy = int(self.x + pw/2), int(self.y + ph/2)
        if self._monitors:
            self._current_screen = get_screen_for_point(cx, cy, self._monitors)
        else:
            self._current_screen = (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())

    def _get_current_screen(self):
        if self._current_screen is None:
            self._update_current_screen()
        if self._current_screen is None:
            return (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        return self._current_screen

    def position_window(self):
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")

    # ── Events ────────────────────────────────────────────────────────────
    def bind_events(self):
        self.canvas.bind("<ButtonPress-1>",   self._on_drag_start)
        self.canvas.bind("<B1-Motion>",       self._on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<ButtonPress-3>",   self._on_right_click)

    # ── Beautiful Pink/White Context Menu ─────────────────────────────────
    # Color palette shared with dialogs
    _CM_BG        = "#fff0f5"   # soft blush white background
    _CM_HEADER_BG = "#ffb6d5"   # pink header stripe
    _CM_HOVER_BG  = "#ffe0ee"   # hover highlight
    _CM_TEXT      = "#5a1a3a"   # deep rose text
    _CM_PINK      = "#e0457a"   # accent pink
    _CM_SEP       = "#f9c6d8"   # separator line
    _CM_CHECK     = "#e0457a"   # checkmark color
    _CM_BTN_BG    = "#ffffff"   # button background
    _CM_SHADOW    = "#f0b8cc"   # subtle shadow/border

    def _on_right_click(self, event):
        """Show beautiful custom context menu."""
        self._show_context_menu(event.x_root, event.y_root)

    def _show_context_menu(self, x, y):
        """Build and display a beautiful pink/white floating context menu."""
        cfg = self.cfg

        # Destroy any existing context menu
        if hasattr(self, '_ctx_win') and self._ctx_win:
            try:
                self._ctx_win.destroy()
            except Exception:
                pass
            self._ctx_win = None

        win = tk.Toplevel(self.root)
        self._ctx_win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=self._CM_SHADOW)

        # Main frame with 1px border effect
        outer = tk.Frame(win, bg=self._CM_SHADOW, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        frame = tk.Frame(outer, bg=self._CM_BG, padx=0, pady=4)
        frame.pack(fill="both", expand=True)

        def close_menu(event=None):
            try:
                win.destroy()
            except Exception:
                pass
            self._ctx_win = None

        def run_cmd(fn):
            close_menu()
            self.root.after(10, fn)

        def make_item(parent, label, command=None, checked=None, is_sep=False,
                      is_header=False, indent=0):
            if is_sep:
                sep = tk.Frame(parent, bg=self._CM_SEP, height=1)
                sep.pack(fill="x", padx=10, pady=2)
                return

            row = tk.Frame(parent, bg=self._CM_BG, cursor="hand2" if command else "")
            row.pack(fill="x", padx=0, pady=0)

            # checkmark column
            ck_text = "✦" if checked else "  "
            ck_color = self._CM_CHECK if checked else self._CM_BG
            ck = tk.Label(row, text=ck_text, bg=self._CM_BG, fg=ck_color,
                          font=("Microsoft YaHei UI", 9, "bold"), width=2, anchor="center")
            ck.pack(side="left", padx=(6, 0))

            lbl = tk.Label(row, text=label, bg=self._CM_BG, fg=self._CM_TEXT,
                           font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=4)
            lbl.pack(side="left", fill="x", expand=True, padx=indent)

            # Arrow for submenus
            arrow_lbl = None
            if command is None and not is_sep:
                arrow_lbl = tk.Label(row, text="▸", bg=self._CM_BG, fg=self._CM_PINK,
                                     font=("Microsoft YaHei UI", 9), padx=4)
                arrow_lbl.pack(side="right")

            def on_enter(e, r=row, ck_w=ck, l=lbl, aw=arrow_lbl):
                r.config(bg=self._CM_HOVER_BG)
                ck_w.config(bg=self._CM_HOVER_BG)
                l.config(bg=self._CM_HOVER_BG)
                if aw: aw.config(bg=self._CM_HOVER_BG)

            def on_leave(e, r=row, ck_w=ck, l=lbl, aw=arrow_lbl):
                r.config(bg=self._CM_BG)
                ck_w.config(bg=self._CM_BG)
                l.config(bg=self._CM_BG)
                if aw: aw.config(bg=self._CM_BG)

            for w in (row, ck, lbl):
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
                if command:
                    w.bind("<Button-1>", lambda e, fn=command: run_cmd(fn))
            if arrow_lbl:
                arrow_lbl.bind("<Enter>", on_enter)
                arrow_lbl.bind("<Leave>", on_leave)

            return row

        def make_submenu_item(parent, label, build_sub_fn):
            """Item that opens a submenu popup on hover."""
            row = tk.Frame(parent, bg=self._CM_BG, cursor="hand2")
            row.pack(fill="x", padx=0, pady=0)

            ck = tk.Label(row, text="  ", bg=self._CM_BG, fg=self._CM_BG,
                          font=("Microsoft YaHei UI", 9, "bold"), width=2, anchor="center")
            ck.pack(side="left", padx=(6, 0))

            lbl = tk.Label(row, text=label, bg=self._CM_BG, fg=self._CM_TEXT,
                           font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=4)
            lbl.pack(side="left", fill="x", expand=True)

            arrow = tk.Label(row, text="▸", bg=self._CM_BG, fg=self._CM_PINK,
                             font=("Microsoft YaHei UI", 9), padx=4)
            arrow.pack(side="right")

            _sub_win = [None]

            def close_sub():
                if _sub_win[0]:
                    try: _sub_win[0].destroy()
                    except: pass
                    _sub_win[0] = None

            def open_sub(e, r=row):
                close_sub()
                sx = win.winfo_x() + win.winfo_width()
                sy = win.winfo_y() + r.winfo_y()
                sub = tk.Toplevel(win)
                _sub_win[0] = sub
                sub.overrideredirect(True)
                sub.attributes("-topmost", True)
                sub.configure(bg=self._CM_SHADOW)
                outer_s = tk.Frame(sub, bg=self._CM_SHADOW, padx=1, pady=1)
                outer_s.pack(fill="both", expand=True)
                sf = tk.Frame(outer_s, bg=self._CM_BG, padx=0, pady=4)
                sf.pack(fill="both", expand=True)
                build_sub_fn(sf, sub, close_sub)
                sub.update_idletasks()
                sw = sub.winfo_reqwidth()
                sh = sub.winfo_reqheight()
                # Adjust if off-screen
                screen_w = self.root.winfo_screenwidth()
                screen_h = self.root.winfo_screenheight()
                if sx + sw > screen_w:
                    sx = win.winfo_x() - sw
                if sy + sh > screen_h:
                    sy = screen_h - sh
                sub.geometry(f"+{sx}+{sy}")
                sub.lift()

                def sub_close_on_click_outside(e):
                    try:
                        if not (sub.winfo_x() <= e.x_root <= sub.winfo_x() + sub.winfo_width() and
                                sub.winfo_y() <= e.y_root <= sub.winfo_y() + sub.winfo_height()):
                            close_sub()
                    except: pass

                sub.bind("<FocusOut>", lambda e: close_sub())

            def on_enter(e, r=row, widgets=(ck, lbl, arrow)):
                r.config(bg=self._CM_HOVER_BG)
                for w in widgets: w.config(bg=self._CM_HOVER_BG)
                open_sub(e, r)

            def on_leave(e, r=row, widgets=(ck, lbl, arrow)):
                r.config(bg=self._CM_BG)
                for w in widgets: w.config(bg=self._CM_BG)

            for w in (row, ck, lbl, arrow):
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)

        # ── Menu header ──
        header = tk.Frame(frame, bg=self._CM_HEADER_BG)
        header.pack(fill="x", padx=0, pady=(0, 4))
        tk.Label(header, text="🐾  Desktop Hachimi", bg=self._CM_HEADER_BG,
                 fg="#ffffff", font=("Microsoft YaHei UI", 10, "bold"),
                 padx=12, pady=6).pack(side="left")

        # ── 切换桌宠 submenu ──
        def build_pet_sub(sf, sub, close_sub_fn):
            for p in get_available_pets():
                is_cur = (p == cfg["pet"])
                def cmd(n=p):
                    close_menu(); close_sub_fn()
                    self.root.after(10, lambda: self.set_pet(n))
                r = tk.Frame(sf, bg=self._CM_BG, cursor="hand2")
                r.pack(fill="x")
                ck_t = "✦" if is_cur else "  "
                ck_c = self._CM_CHECK if is_cur else self._CM_BG
                ck_l = tk.Label(r, text=ck_t, bg=self._CM_BG, fg=ck_c,
                                font=("Microsoft YaHei UI", 9, "bold"), width=2)
                ck_l.pack(side="left", padx=(6,0))
                tl = tk.Label(r, text=p, bg=self._CM_BG, fg=self._CM_TEXT,
                              font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=4)
                tl.pack(side="left", fill="x", expand=True)
                def _on_e(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=self._CM_HOVER_BG); cc.config(bg=self._CM_HOVER_BG); tt.config(bg=self._CM_HOVER_BG)
                def _on_l(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=self._CM_BG); cc.config(bg=self._CM_BG); tt.config(bg=self._CM_BG)
                for w in (r, ck_l, tl):
                    w.bind("<Enter>", _on_e); w.bind("<Leave>", _on_l)
                    w.bind("<Button-1>", lambda e, c=cmd: c())

        make_submenu_item(frame, "切换桌宠", build_pet_sub)

        # ── 删除桌宠 submenu ──
        def build_del_sub(sf, sub, close_sub_fn):
            for p in get_available_pets():
                def cmd(n=p):
                    close_menu(); close_sub_fn()
                    self.root.after(10, lambda: self._delete_pet(n))
                r = tk.Frame(sf, bg=self._CM_BG, cursor="hand2"); r.pack(fill="x")
                tl = tk.Label(r, text=p, bg=self._CM_BG, fg="#c0394e",
                              font=("Microsoft YaHei UI", 10), anchor="w", padx=16, pady=4)
                tl.pack(side="left", fill="x", expand=True)
                def _on_e(e, rr=r, tt=tl): rr.config(bg=self._CM_HOVER_BG); tt.config(bg=self._CM_HOVER_BG)
                def _on_l(e, rr=r, tt=tl): rr.config(bg=self._CM_BG); tt.config(bg=self._CM_BG)
                for w in (r, tl): w.bind("<Enter>", _on_e); w.bind("<Leave>", _on_l); w.bind("<Button-1>", lambda e, c=cmd: c())

        make_submenu_item(frame, "删除桌宠", build_del_sub)

        # ── 桌宠大小 submenu ──
        def build_scale_sub(sf, sub, close_sub_fn):
            for v in [round(x*0.1,1) for x in range(1,21)]:
                is_cur = abs(cfg["scale"]-v) < 0.05
                def cmd(val=v):
                    close_menu(); close_sub_fn()
                    self.root.after(10, lambda: self.set_scale(val))
                r = tk.Frame(sf, bg=self._CM_BG, cursor="hand2"); r.pack(fill="x")
                ck_t = "✦" if is_cur else "  "; ck_c = self._CM_CHECK if is_cur else self._CM_BG
                ck_l = tk.Label(r, text=ck_t, bg=self._CM_BG, fg=ck_c, font=("Microsoft YaHei UI", 9, "bold"), width=2)
                ck_l.pack(side="left", padx=(6,0))
                tl = tk.Label(r, text=f"x{v:.1f}", bg=self._CM_BG, fg=self._CM_TEXT, font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=3)
                tl.pack(side="left", fill="x", expand=True)
                def _on_e(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=self._CM_HOVER_BG); cc.config(bg=self._CM_HOVER_BG); tt.config(bg=self._CM_HOVER_BG)
                def _on_l(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=self._CM_BG); cc.config(bg=self._CM_BG); tt.config(bg=self._CM_BG)
                for w in (r, ck_l, tl): w.bind("<Enter>", _on_e); w.bind("<Leave>", _on_l); w.bind("<Button-1>", lambda e, c=cmd: c())

        make_submenu_item(frame, "桌宠大小", build_scale_sub)

        # ── 透明度 submenu ──
        def build_opacity_sub(sf, sub, close_sub_fn):
            for v in [round(x*0.1,1) for x in range(1,11)]:
                is_cur = abs(cfg["opacity"]-v) < 0.05
                def cmd(val=v):
                    close_menu(); close_sub_fn()
                    self.root.after(10, lambda: self.set_opacity(val))
                r = tk.Frame(sf, bg=self._CM_BG, cursor="hand2"); r.pack(fill="x")
                ck_t = "✦" if is_cur else "  "; ck_c = self._CM_CHECK if is_cur else self._CM_BG
                ck_l = tk.Label(r, text=ck_t, bg=self._CM_BG, fg=ck_c, font=("Microsoft YaHei UI", 9, "bold"), width=2)
                ck_l.pack(side="left", padx=(6,0))
                tl = tk.Label(r, text=f"{int(v*100)}%", bg=self._CM_BG, fg=self._CM_TEXT, font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=3)
                tl.pack(side="left", fill="x", expand=True)
                def _on_e(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=self._CM_HOVER_BG); cc.config(bg=self._CM_HOVER_BG); tt.config(bg=self._CM_HOVER_BG)
                def _on_l(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=self._CM_BG); cc.config(bg=self._CM_BG); tt.config(bg=self._CM_BG)
                for w in (r, ck_l, tl): w.bind("<Enter>", _on_e); w.bind("<Leave>", _on_l); w.bind("<Button-1>", lambda e, c=cmd: c())

        make_submenu_item(frame, "透明度", build_opacity_sub)

        # ── 速度 submenu ──
        def build_speed_sub(sf, sub, close_sub_fn):
            for s in range(1,11):
                is_cur = cfg["speed"] == s
                def cmd(val=s):
                    close_menu(); close_sub_fn()
                    self.root.after(10, lambda: self.set_speed(val))
                r = tk.Frame(sf, bg=self._CM_BG, cursor="hand2"); r.pack(fill="x")
                ck_t = "✦" if is_cur else "  "; ck_c = self._CM_CHECK if is_cur else self._CM_BG
                ck_l = tk.Label(r, text=ck_t, bg=self._CM_BG, fg=ck_c, font=("Microsoft YaHei UI", 9, "bold"), width=2)
                ck_l.pack(side="left", padx=(6,0))
                tl = tk.Label(r, text=f"速度 {s}", bg=self._CM_BG, fg=self._CM_TEXT, font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=3)
                tl.pack(side="left", fill="x", expand=True)
                def _on_e(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=self._CM_HOVER_BG); cc.config(bg=self._CM_HOVER_BG); tt.config(bg=self._CM_HOVER_BG)
                def _on_l(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=self._CM_BG); cc.config(bg=self._CM_BG); tt.config(bg=self._CM_BG)
                for w in (r, ck_l, tl): w.bind("<Enter>", _on_e); w.bind("<Leave>", _on_l); w.bind("<Button-1>", lambda e, c=cmd: c())

        make_submenu_item(frame, "速度", build_speed_sub)

        # ── Separator ──
        make_item(frame, "", is_sep=True)

        # ── Toggle items ──
        mf = cfg.get("mouse_follow", False)
        make_item(frame, "鼠标跟随", checked=mf,
                  command=lambda: self.set_mouse_follow(not self.cfg.get("mouse_follow", False)))

        aot = cfg.get("always_on_top", True)
        make_item(frame, "最上层显示", checked=aot,
                  command=lambda: self.set_always_on_top(not self.cfg.get("always_on_top", True)))

        ast = get_autostart()
        make_item(frame, "开机自启动", checked=ast,
                  command=self.app._toggle_autostart)

        # ── Separator ──
        make_item(frame, "", is_sep=True)

        # ── Actions ──
        make_item(frame, "音乐播放器",     command=self._open_music_player)
        make_item(frame, "调整状态权重",   command=lambda: WeightEditorDialog(self.root, self))
        make_item(frame, "调整运动方向反转", command=lambda: FlipEditorDialog(self.root, self))
        make_item(frame, "创建桌宠",       command=lambda: PetCreatorDialog(self.root))
        make_item(frame, "关于",           command=lambda: AboutDialog(self.root))

        # ── Separator ──
        make_item(frame, "", is_sep=True)

        # ── 退出 (pink accent) ──
        quit_row = tk.Frame(frame, bg=self._CM_BG, cursor="hand2")
        quit_row.pack(fill="x", padx=0, pady=(0,2))
        ck_q = tk.Label(quit_row, text="  ", bg=self._CM_BG, width=2,
                        font=("Microsoft YaHei UI", 9))
        ck_q.pack(side="left", padx=(6,0))
        lbl_q = tk.Label(quit_row, text="退出", bg=self._CM_BG, fg=self._CM_PINK,
                         font=("Microsoft YaHei UI", 10, "bold"), anchor="w", padx=4, pady=4)
        lbl_q.pack(side="left", fill="x", expand=True)
        def _on_eq(e): quit_row.config(bg=self._CM_HOVER_BG); ck_q.config(bg=self._CM_HOVER_BG); lbl_q.config(bg=self._CM_HOVER_BG)
        def _on_lq(e): quit_row.config(bg=self._CM_BG); ck_q.config(bg=self._CM_BG); lbl_q.config(bg=self._CM_BG)
        for w in (quit_row, ck_q, lbl_q):
            w.bind("<Enter>", _on_eq); w.bind("<Leave>", _on_lq)
            w.bind("<Button-1>", lambda e: run_cmd(self.app._do_quit))

        # ── Position menu ──
        win.update_idletasks()
        mw = win.winfo_reqwidth()
        mh = win.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        mx = x if x + mw <= sw else x - mw
        my = y if y + mh <= sh else y - mh
        win.geometry(f"+{mx}+{my}")
        win.deiconify()
        win.lift()
        win.focus_set()

        # Close on click outside
        def on_focus_out(e):
            try:
                if win.winfo_exists():
                    close_menu()
            except Exception:
                pass

        win.bind("<FocusOut>", on_focus_out)
        win.bind("<Escape>", close_menu)
        self.root.bind("<ButtonPress-1>", lambda e: close_menu(), add="+")
        self.root.bind("<ButtonPress-3>", lambda e: None, add="+")

    def _on_drag_start(self, event):
        self.prev_state = self.state
        self._drag_ox = event.x_root - self.x
        self._drag_oy = event.y_root - self.y
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
        self._update_current_screen()
        self._enter_state(self.prev_state if self.prev_state != STATE_DRAG else STATE_IDLE)
        if self.cfg.get("mouse_follow"):
            self._mf_near_mouse = False
            self._mf_loop_tick()

    # ── Music Player ───────────────────────────────────────────────────────
    def _open_music_player(self):
        if self._music_dialog is not None:
            try:
                self._music_dialog.win.lift()
                return
            except Exception:
                pass
        if self._music_player is None:
            self._music_player = MusicPlayer()
        self._music_dialog = MusicPlayerDialog(self.root, self._music_player)

    # ── Delete Pet ─────────────────────────────────────────────────────────
    def _delete_pet(self, name: str):
        pets = get_available_pets()
        if len(pets) <= 1:
            messagebox.showwarning("无法删除", "至少需要保留一个桌宠，无法删除。", parent=self.root)
            return
        if not messagebox.askyesno("删除桌宠",
                                   f"确定将桌宠「{name}」移至回收站？\n（可从回收站中恢复）",
                                   parent=self.root):
            return
        pet_path = os.path.join(PETS_DIR, name)
        ok = move_to_trash(pet_path)
        if ok:
            if self.cfg.get("pet") == name:
                remaining = [p for p in get_available_pets() if p != name]
                if remaining:
                    self.set_pet(remaining[0])
            messagebox.showinfo("删除成功", f"桌宠「{name}」已移至回收站。", parent=self.root)
        else:
            messagebox.showerror("删除失败", "无法移至回收站，请手动删除。", parent=self.root)

    # ── Public API ─────────────────────────────────────────────────────────
    def set_pet(self, name):
        self.cfg["pet"] = name;  save_config(self.cfg);  self.reload_pet()

    def set_scale(self, scale):
        self.cfg["scale"] = scale; save_config(self.cfg); self.reload_pet()

    def set_opacity(self, opacity):
        self.cfg["opacity"] = opacity; save_config(self.cfg)
        self.root.attributes("-alpha", opacity)

    def set_speed(self, speed):
        self.cfg["speed"] = speed; save_config(self.cfg)

    def set_mouse_follow(self, val):
        self.cfg["mouse_follow"] = val; save_config(self.cfg)
        if val:
            self._start_mouse_follow_loop()
        else:
            self._stop_mouse_follow_loop()
            if self.state in (STATE_MOVE, STATE_DYNAMIC):
                self._enter_state(STATE_IDLE)

    def set_always_on_top(self, val):
        self.cfg["always_on_top"] = val; save_config(self.cfg)
        self.root.attributes("-topmost", val)

    def save_position(self):
        self.cfg["x"] = int(self.x); self.cfg["y"] = int(self.y); save_config(self.cfg)

    def run(self):
        self._movement_loop()
        self.root.after(100, self._update_current_screen)
        self.root.mainloop()

    def destroy(self):
        self.save_position(); self.root.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  Dialogs
# ══════════════════════════════════════════════════════════════════════════════

class WeightEditorDialog:
    # Pink/white palette matching the pet's right-click context menu
    _BG        = "#fff0f5"   # soft blush white background
    _CARD_BG   = "#ffe0ee"   # card / section background
    _HEADER_BG = "#ffb6d5"   # pink header stripe
    _PINK      = "#e0457a"   # accent pink
    _TEXT      = "#5a1a3a"   # deep rose text
    _GRAY      = "#c47a9a"   # muted rose for hints
    _SEP       = "#f9c6d8"   # separator line
    _GREEN     = "#e0457a"   # reuse accent for save button (override below)
    _WHITE     = "#5a1a3a"   # alias – text on cards

    def __init__(self, parent_root, pet_win: PetWindow):
        self.pet_win = pet_win
        self.win = tk.Toplevel(parent_root)
        self.win.title("调整状态权重")
        self.win.configure(bg=self._BG)
        set_window_icon(self.win); self.win.resizable(False, False); 
        self._build_ui()

    def _label(self, parent, text, fg=None, font=None, **kw):
        return tk.Label(parent, text=text, bg=self._BG, fg=fg or self._TEXT,
                        font=font or _FONT_NORMAL, **kw)

    def _card_label(self, parent, text, fg=None, font=None, **kw):
        return tk.Label(parent, text=text, bg=self._CARD_BG, fg=fg or self._TEXT,
                        font=font or _FONT_NORMAL, **kw)

    def _spinbox(self, parent, var):
        return tk.Spinbox(parent, from_=1, to=999, textvariable=var, width=6,
                          bg=self._CARD_BG, fg=self._PINK, insertbackground=self._PINK,
                          buttonbackground=self._CARD_BG, relief="flat",
                          highlightthickness=1, highlightbackground=self._SEP,
                          font=_FONT_NORMAL)

    def _build_ui(self):
        win = self.win
        pd  = self.pet_win.pet_data
        pad = {"padx": 10, "pady": 5}

        # Pink header stripe (matching context menu style)
        header = tk.Frame(win, bg=self._HEADER_BG)
        header.pack(fill="x")
        tk.Label(header, text="🐾  调整状态权重", bg=self._HEADER_BG,
                 fg="#ffffff", font=("Microsoft YaHei UI", 11, "bold"),
                 padx=14, pady=8).pack(side="left")

        tk.Label(win, text=f"桌宠：{pd.name}", bg=self._BG, fg=self._GRAY,
                 font=_FONT_SMALL).pack(pady=(6, 0))

        # Card
        card = tk.Frame(win, bg=self._CARD_BG, padx=16, pady=10)
        card.pack(fill="x", padx=16, pady=(10, 4))

        self._card_label(card, "说明：权重为正整数，值越大该状态出现概率越高。",
                          fg=self._GRAY, font=_FONT_SMALL).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        row = 1
        self._card_label(card, "动感状态 权重：", anchor="e").grid(row=row, column=0, sticky="e", **pad)
        self._dyn_var = tk.IntVar(value=pd.dynamic_weight)
        self._spinbox(card, self._dyn_var).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        tk.Frame(card, bg=self._SEP, height=1).grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=4); row += 1

        self._idle_vars = []
        idle_count = len(pd.idle_variants)
        if idle_count == 0:
            self._card_label(card, "非移动状态：（无图）", fg=self._GRAY).grid(
                row=row, column=0, columnspan=3, **pad); row += 1
        elif idle_count == 1:
            self._card_label(card, "非移动状态 权重：", anchor="e").grid(row=row, column=0, sticky="e", **pad)
            v = tk.IntVar(value=pd.idle_weights[0] if pd.idle_weights else 2)
            self._spinbox(card, v).grid(row=row, column=1, sticky="w", **pad)
            self._idle_vars.append(v); row += 1
        else:
            self._card_label(card, "非移动状态（多图）：", font=_FONT_BOLD).grid(
                row=row, column=0, columnspan=3, sticky="w", padx=10); row += 1
            for i in range(idle_count):
                self._card_label(card, f"  idle{i+1} 权重：", anchor="e").grid(row=row, column=0, sticky="e", **pad)
                v = tk.IntVar(value=pd.idle_weights[i] if i < len(pd.idle_weights) else 2)
                self._spinbox(card, v).grid(row=row, column=1, sticky="w", **pad)
                self._idle_vars.append(v); row += 1

        tk.Frame(card, bg=self._SEP, height=1).grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=4); row += 1

        self._move_vars = []
        move_count = len(pd.move_variants)
        if move_count == 0:
            self._card_label(card, "移动状态：（无图）", fg=self._GRAY).grid(
                row=row, column=0, columnspan=3, **pad); row += 1
        elif move_count == 1:
            self._card_label(card, "移动状态 权重：", anchor="e").grid(row=row, column=0, sticky="e", **pad)
            v = tk.IntVar(value=pd.move_weights[0] if pd.move_weights else 1)
            self._spinbox(card, v).grid(row=row, column=1, sticky="w", **pad)
            self._move_vars.append(v); row += 1
        else:
            self._card_label(card, "移动状态（多图）：", font=_FONT_BOLD).grid(
                row=row, column=0, columnspan=3, sticky="w", padx=10); row += 1
            for i in range(move_count):
                self._card_label(card, f"  move{i+1} 权重：", anchor="e").grid(row=row, column=0, sticky="e", **pad)
                v = tk.IntVar(value=pd.move_weights[i] if i < len(pd.move_weights) else 1)
                self._spinbox(card, v).grid(row=row, column=1, sticky="w", **pad)
                self._move_vars.append(v); row += 1

        self._update_preview()
        for var in [self._dyn_var] + self._idle_vars + self._move_vars:
            var.trace_add("write", lambda *_: self._update_preview())

        self._preview_label = tk.Label(win, text="", bg=self._BG, fg=self._GRAY,
                                       font=("Microsoft YaHei UI", 8))
        self._preview_label.pack(padx=10, pady=(4, 0))

        bf = tk.Frame(win, bg=self._BG)
        bf.pack(pady=12)
        tk.Button(bf, text="保存并应用", bg=self._PINK, fg="#ffffff",
                  font=_FONT_BOLD, relief="flat", padx=12, command=self._save).pack(side="left", padx=8)
        tk.Button(bf, text="取消", bg=self._CARD_BG, fg=self._TEXT,
                  font=_FONT_NORMAL, relief="flat", padx=12, command=self.win.destroy).pack(side="left", padx=8)

    def _safe_int(self, var, fallback=1):
        try: return max(1, int(var.get()))
        except: return fallback

    def _update_preview(self):
        dw = self._safe_int(self._dyn_var)
        iw = sum(self._safe_int(v) for v in self._idle_vars) if self._idle_vars else 0
        mw = sum(self._safe_int(v) for v in self._move_vars) if self._move_vars else 0
        total = dw + iw + mw
        if total == 0:
            self._preview_label.config(text=""); return
        self._preview_label.config(text="  概率预览：" + "  |  ".join([
            f"动感 {dw/total*100:.1f}%", f"非移动 {iw/total*100:.1f}%", f"移动 {mw/total*100:.1f}%"]))

    def _save(self):
        pd = self.pet_win.pet_data; path = os.path.join(pd.dir, "weights.json")
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f: existing = json.load(f)
            except: pass
        existing["dynamic_weight"] = self._safe_int(self._dyn_var)
        if self._idle_vars: existing["idle_weight"] = [self._safe_int(v) for v in self._idle_vars]
        if self._move_vars: existing["move_weight"] = [self._safe_int(v) for v in self._move_vars]
        with open(path, "w", encoding="utf-8") as f: json.dump(existing, f, ensure_ascii=False, indent=2)
        self.pet_win.reload_pet()
        messagebox.showinfo("✅ 成功", "权重已保存并应用！", parent=self.win); self.win.destroy()


class FlipEditorDialog:
    # Pink/white palette matching the pet's right-click context menu
    _BG        = "#fff0f5"
    _CARD_BG   = "#ffe0ee"
    _HEADER_BG = "#ffb6d5"
    _PINK      = "#e0457a"
    _TEXT      = "#5a1a3a"
    _GRAY      = "#c47a9a"
    _SEP       = "#f9c6d8"
    _WHITE     = "#5a1a3a"  # alias

    def __init__(self, parent_root, pet_win: PetWindow):
        self.pet_win = pet_win
        self.win = tk.Toplevel(parent_root)
        self.win.title("调整运动方向反转")
        self.win.configure(bg=self._BG)
        set_window_icon(self.win); self.win.resizable(False, False); 
        self._rows: list[dict] = []
        self._build_ui()

    @staticmethod
    def _variant_key(index, total):
        return "move" if total == 1 else f"move{index+1}"

    def _build_ui(self):
        win = self.win; pd = self.pet_win.pet_data

        # Pink header stripe
        header = tk.Frame(win, bg=self._HEADER_BG)
        header.pack(fill="x")
        tk.Label(header, text="🐾  调整运动方向反转", bg=self._HEADER_BG,
                 fg="#ffffff", font=("Microsoft YaHei UI", 11, "bold"),
                 padx=14, pady=8).pack(side="left")

        tk.Label(win, text=f"桌宠：{pd.name}", bg=self._BG, fg=self._GRAY,
                 font=_FONT_SMALL).pack(pady=(6, 0))

        info = tk.Frame(win, bg=self._CARD_BG, padx=14, pady=8)
        info.pack(fill="x", padx=16, pady=(8, 4))
        tk.Label(info,
            text='说明：启用后，桌宠向"非默认方向"运动时图片会水平翻转。\n  默认方向=左 → 向左走不翻转，向右走翻转\n  默认方向=右 → 向右走不翻转，向左走翻转',
            bg=self._CARD_BG, fg=self._GRAY, justify="left", font=_FONT_SMALL).pack(anchor="w")

        mc = len(pd.move_variants)
        if mc == 0:
            tk.Label(win, text="当前桌宠没有移动状态图，无法配置。",
                     bg=self._BG, fg=self._GRAY).pack(padx=16, pady=8)
            tk.Button(win, text="关闭", bg=self._CARD_BG, fg=self._TEXT,
                      relief="flat", padx=12, command=self.win.destroy).pack(pady=10)
            return

        card = tk.Frame(win, bg=self._CARD_BG, padx=12, pady=10)
        card.pack(fill="x", padx=16, pady=4)
        pad = {"padx": 8, "pady": 5}

        for lbl, col in [("图片", 0), ("启用反转", 1), ("默认朝向", 2), ("当前效果预览", 3)]:
            tk.Label(card, text=lbl, bg=self._CARD_BG, fg=self._PINK,
                     font=_FONT_BOLD, width=(10 if col == 0 else None)).grid(row=0, column=col, **pad)
        tk.Frame(card, bg=self._SEP, height=1).grid(row=1, column=0, columnspan=4, sticky="ew", padx=4, pady=2)

        for i in range(mc):
            key = self._variant_key(i, mc)
            ex  = pd.move_flip_info.get(key, {})
            ev  = tk.BooleanVar(value=ex.get("enabled", False))
            dv  = tk.StringVar(value=ex.get("default_dir", "left"))
            r   = 2 + i
            tk.Label(card, text="move.gif" if mc == 1 else f"move{i+1}.gif",
                     bg=self._CARD_BG, fg=self._TEXT, anchor="e").grid(row=r, column=0, sticky="e", **pad)
            tk.Checkbutton(card, variable=ev, bg=self._CARD_BG, fg=self._PINK,
                           selectcolor=self._BG, activebackground=self._CARD_BG,
                           command=self._make_row_refresh(i)).grid(row=r, column=1, **pad)
            cb = ttk.Combobox(card, textvariable=dv, values=["left", "right"], width=6, state="readonly")
            cb.grid(row=r, column=2, **pad)
            cb.bind("<<ComboboxSelected>>", lambda e, idx=i: self._refresh_preview(idx))
            pl = tk.Label(card, text="", bg=self._CARD_BG, fg=self._PINK, width=24, anchor="w", font=_FONT_SMALL)
            pl.grid(row=r, column=3, padx=(0, 8))
            self._rows.append({"key": key, "enabled_var": ev, "dir_var": dv, "preview_lbl": pl})
            self._refresh_preview(i)

        bf = tk.Frame(win, bg=self._BG)
        bf.pack(pady=12)
        tk.Button(bf, text="保存并应用", bg=self._PINK, fg="#ffffff",
                  font=_FONT_BOLD, relief="flat", padx=12, command=self._save).pack(side="left", padx=8)
        tk.Button(bf, text="取消", bg=self._CARD_BG, fg=self._TEXT,
                  relief="flat", padx=12, command=self.win.destroy).pack(side="left", padx=8)

    def _make_row_refresh(self, idx):
        return lambda: self._refresh_preview(idx)

    def _refresh_preview(self, idx):
        row = self._rows[idx]; en = row["enabled_var"].get(); d = row["dir_var"].get()
        if not en: text = "⬜ 未启用（始终不翻转）"
        elif d == "left": text = "← 左走正常  |  → 右走翻转"
        else: text = "→ 右走正常  |  ← 左走翻转"
        row["preview_lbl"].config(text=text)

    def _save(self):
        pd = self.pet_win.pet_data; path = os.path.join(pd.dir, "flip.json")
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f: existing = json.load(f)
            except: pass
        existing.pop("_comment", None)
        for row in self._rows:
            existing[row["key"]] = {"enabled": row["enabled_var"].get(), "default_dir": row["dir_var"].get()}
        with open(path, "w", encoding="utf-8") as f: json.dump(existing, f, ensure_ascii=False, indent=2)
        self.pet_win.reload_pet()
        messagebox.showinfo("✅ 成功", "运动方向反转设置已保存并应用！", parent=self.win); self.win.destroy()


class PetCreatorDialog:
    def __init__(self, parent_root):
        self.win = tk.Toplevel(parent_root)
        self.win.title("创建桌宠"); set_window_icon(self.win)
        self.win.configure(bg=self._BG)
        self.win.resizable(False, False); 
        self._files = {"icon": tk.StringVar(), "dynamic": tk.StringVar(), "drag": tk.StringVar()}
        self._idle_entries = []; self._move_entries = []
        self._build_ui()

    _BG        = "#fff0f5"
    _CARD_BG   = "#ffe0ee"
    _HEADER_BG = "#ffb6d5"
    _PINK      = "#e0457a"
    _TEXT      = "#5a1a3a"
    _GRAY      = "#c47a9a"
    _SEP       = "#f9c6d8"
    _WHITE     = "#5a1a3a"  # alias

    def _entry(self, parent, var, width=24):
        return tk.Entry(parent, textvariable=var, width=width,
                        bg=self._CARD_BG, fg=self._TEXT, insertbackground=self._TEXT,
                        relief="flat", highlightthickness=1, highlightbackground=self._SEP)

    def _btn(self, parent, text, command, accent=False):
        if accent:
            return tk.Button(parent, text=text, command=command, bg=self._PINK, fg="#ffffff",
                             font=_FONT_BOLD, relief="flat", padx=10)
        return tk.Button(parent, text=text, command=command, bg=self._CARD_BG, fg=self._PINK,
                         relief="flat", padx=8)

    def _spinbox(self, parent, var, width=4):
        return tk.Spinbox(parent, from_=1, to=99, textvariable=var, width=width,
                          bg=self._CARD_BG, fg=self._PINK, insertbackground=self._PINK,
                          buttonbackground=self._CARD_BG, relief="flat",
                          highlightthickness=1, highlightbackground=self._SEP)

    def _label(self, parent, text, fg=None):
        return tk.Label(parent, text=text, bg=self._CARD_BG, fg=fg or self._TEXT, font=_FONT_NORMAL)

    def _build_ui(self):
        win = self.win
        pad = {"padx": 8, "pady": 4}

        # Pink header stripe
        header = tk.Frame(win, bg=self._HEADER_BG)
        header.pack(fill="x")
        tk.Label(header, text="🐾  创建桌宠", bg=self._HEADER_BG,
                 fg="#ffffff", font=("Microsoft YaHei UI", 11, "bold"),
                 padx=14, pady=8).pack(side="left")

        card = tk.Frame(win, bg=self._CARD_BG, padx=14, pady=10)
        card.pack(fill="x", padx=16, pady=(10, 4))

        self._label(card, "桌宠名:").grid(row=0, column=0, sticky="e", **pad)
        self.name_var = tk.StringVar()
        self._entry(card, self.name_var).grid(row=0, column=1, columnspan=2, sticky="w", **pad)

        for row, key, label in [(1, "icon", "桌宠图标(.ico):"), (2, "dynamic", "动感状态(.gif):"), (3, "drag", "拖拽状态(.gif):")]:
            ext = "*.ico" if key == "icon" else "*.gif"
            self._label(card, label).grid(row=row, column=0, sticky="e", **pad)
            self._entry(card, self._files[key]).grid(row=row, column=1, **pad)
            self._btn(card, "浏览", lambda k=key, e=ext: self._browse(k, [(k.upper(), e)])).grid(row=row, column=2, **pad)

        self._label(card, "动感权重:").grid(row=2, column=3, **pad)
        self.dyn_weight = tk.IntVar(value=3)
        self._spinbox(card, self.dyn_weight).grid(row=2, column=4, **pad)

        tk.Label(win, text="── 非移动状态(idle) ──", bg=self._BG, fg=self._GRAY,
                 font=_FONT_SMALL).pack(pady=(8, 2))
        self._idle_frame = tk.Frame(win, bg=self._CARD_BG)
        self._idle_frame.pack(fill="x", padx=16)
        self._add_idle_row()
        self._btn(win, "+ 添加idle图", self._add_idle_row).pack(pady=4)

        tk.Label(win, text="── 移动状态(move) ──", bg=self._BG, fg=self._GRAY,
                 font=_FONT_SMALL).pack(pady=(6, 2))
        self._move_frame = tk.Frame(win, bg=self._CARD_BG)
        self._move_frame.pack(fill="x", padx=16)
        self._add_move_row()
        self._btn(win, "+ 添加move图", self._add_move_row).pack(pady=4)

        bf = tk.Frame(win, bg=self._BG)
        bf.pack(pady=12)
        self._btn(bf, "保存", self._save, accent=True).pack(side="left", padx=8)
        self._btn(bf, "取消", self.win.destroy).pack(side="left", padx=8)

    def _browse(self, key, filetypes):
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p: self._files[key].set(p)

    def _browse_var(self, var, filetypes):
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p: var.set(p)

    def _add_idle_row(self):
        f = self._idle_frame; row = len(self._idle_entries)
        pv = tk.StringVar(); wv = tk.IntVar(value=2)
        tk.Label(f, text=f"idle {row+1}:", bg=self._CARD_BG, fg=self._TEXT).grid(row=row, column=0, padx=6)
        tk.Entry(f, textvariable=pv, width=24, bg=self._BG, fg=self._TEXT,
                 insertbackground=self._TEXT, relief="flat",
                 highlightthickness=1, highlightbackground=self._SEP).grid(row=row, column=1, padx=4, pady=3)
        tk.Button(f, text="浏览", bg=self._CARD_BG, fg=self._PINK, relief="flat",
                  command=lambda v=pv: self._browse_var(v, [("GIF", "*.gif")])).grid(row=row, column=2, padx=4)
        tk.Label(f, text="权重:", bg=self._CARD_BG, fg=self._GRAY).grid(row=row, column=3, padx=4)
        tk.Spinbox(f, from_=1, to=99, textvariable=wv, width=4,
                   bg=self._BG, fg=self._PINK, insertbackground=self._PINK,
                   buttonbackground=self._CARD_BG, relief="flat").grid(row=row, column=4, padx=4)
        self._idle_entries.append((pv, wv))

    def _add_move_row(self):
        f = self._move_frame; row = len(self._move_entries)
        pv = tk.StringVar(); wv = tk.IntVar(value=1); fv = tk.BooleanVar(); dv = tk.StringVar(value="left")
        tk.Label(f, text=f"move {row+1}:", bg=self._CARD_BG, fg=self._TEXT).grid(row=row, column=0, padx=6)
        tk.Entry(f, textvariable=pv, width=24, bg=self._BG, fg=self._TEXT,
                 insertbackground=self._TEXT, relief="flat",
                 highlightthickness=1, highlightbackground=self._SEP).grid(row=row, column=1, padx=4, pady=3)
        tk.Button(f, text="浏览", bg=self._CARD_BG, fg=self._PINK, relief="flat",
                  command=lambda v=pv: self._browse_var(v, [("GIF", "*.gif")])).grid(row=row, column=2, padx=4)
        tk.Label(f, text="权重:", bg=self._CARD_BG, fg=self._GRAY).grid(row=row, column=3, padx=4)
        tk.Spinbox(f, from_=1, to=99, textvariable=wv, width=4,
                   bg=self._BG, fg=self._PINK, insertbackground=self._PINK,
                   buttonbackground=self._CARD_BG, relief="flat").grid(row=row, column=4, padx=4)
        tk.Checkbutton(f, text="翻转", variable=fv, bg=self._CARD_BG, fg=self._PINK,
                       selectcolor=self._BG, activebackground=self._CARD_BG).grid(row=row, column=5, padx=4)
        ttk.Combobox(f, textvariable=dv, values=["left", "right"], width=5, state="readonly").grid(row=row, column=6, padx=4)
        self._move_entries.append((pv, wv, fv, dv))

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("⚠ 错误", "请输入桌宠名称！", parent=self.win); return
        pet_dir = os.path.join(PETS_DIR, name); os.makedirs(pet_dir, exist_ok=True)
        def cp(src, dst):
            if src and os.path.exists(src): shutil.copy2(src, dst)
        cp(self._files["icon"].get(), os.path.join(pet_dir, f"{name}.ico"))
        cp(self._files["dynamic"].get(), os.path.join(pet_dir, f"{name}.gif"))
        cp(self._files["drag"].get(), os.path.join(pet_dir, "drag.gif"))
        vi = [(p.get(), w.get()) for p, w in self._idle_entries if p.get() and os.path.exists(p.get())]
        if len(vi) == 1:
            cp(vi[0][0], os.path.join(pet_dir, "idle.gif")); iw = {"idle_weight": [vi[0][1]]}
        else:
            for i, (p, w) in enumerate(vi, 1): cp(p, os.path.join(pet_dir, f"idle{i}.gif"))
            iw = {"idle_weight": [w for _, w in vi]}
        vm = [(p.get(), w.get(), f.get(), d.get()) for p, w, f, d in self._move_entries if p.get() and os.path.exists(p.get())]
        fi = {}
        if len(vm) == 1:
            cp(vm[0][0], os.path.join(pet_dir, "move.gif")); mw = {"move_weight": [vm[0][1]]}
            if vm[0][2]: fi["move"] = {"enabled": True, "default_dir": vm[0][3]}
        else:
            for i, (p, w, f, d) in enumerate(vm, 1):
                cp(p, os.path.join(pet_dir, f"move{i}.gif"))
                if f: fi[f"move{i}"] = {"enabled": True, "default_dir": d}
            mw = {"move_weight": [w for _, w, *_ in vm]}
        with open(os.path.join(pet_dir, "weights.json"), "w", encoding="utf-8") as f:
            json.dump({"dynamic_weight": self.dyn_weight.get(), **iw, **mw}, f, indent=2)
        if fi:
            with open(os.path.join(pet_dir, "flip.json"), "w", encoding="utf-8") as f: json.dump(fi, f, indent=2)
        messagebox.showinfo("✅ 成功", f"桌宠 '{name}' 已保存！", parent=self.win); self.win.destroy()


class AboutDialog:
    _BG        = "#fff0f5"
    _CARD_BG   = "#ffe0ee"
    _HEADER_BG = "#ffb6d5"
    _PINK      = "#e0457a"
    _TEXT      = "#5a1a3a"
    _GRAY      = "#c47a9a"

    def __init__(self, parent_root):
        self.win = tk.Toplevel(parent_root); win = self.win
        win.title(f"关于 {APP_NAME}"); set_window_icon(win)
        win.configure(bg=self._BG); win.resizable(False, False)

        # Pink header stripe
        header = tk.Frame(win, bg=self._HEADER_BG)
        header.pack(fill="x")
        tk.Label(header, text=f"🐾  {APP_NAME}", bg=self._HEADER_BG,
                 fg="#ffffff", font=("Microsoft YaHei UI", 12, "bold"),
                 padx=14, pady=10).pack(side="left")

        card = tk.Frame(win, bg=self._CARD_BG, padx=20, pady=14)
        card.pack(fill="x", padx=20, pady=(12, 8))

        tk.Label(card, text=f"版本: {VERSION}", bg=self._CARD_BG, fg=self._TEXT,
                 font=_FONT_NORMAL).pack(anchor="w", pady=2)
        tk.Label(card, text=f"作者: {AUTHOR}  ({AUTHOR_EMAIL})", bg=self._CARD_BG, fg=self._GRAY,
                 font=_FONT_NORMAL).pack(anchor="w", pady=2)

        link = tk.Label(card, text=GITHUB_URL, bg=self._CARD_BG, fg=self._PINK,
                        cursor="hand2", font=_FONT_SMALL)
        link.pack(anchor="w", pady=2)
        link.bind("<Button-1>", lambda e: self._open_url(GITHUB_URL))

        bf = tk.Frame(win, bg=self._BG); bf.pack(pady=6)
        self._update_btn = tk.Button(bf, text="检查更新", bg=self._CARD_BG, fg=self._PINK,
                                     font=_FONT_NORMAL, relief="flat", padx=10,
                                     command=self._start_check_update)
        self._update_btn.pack(side="left", padx=6)

        self._status_var = tk.StringVar(value="")
        self._status_lbl = tk.Label(win, textvariable=self._status_var, bg=self._BG,
                                    fg=self._GRAY, font=_FONT_SMALL, wraplength=320)
        self._status_lbl.pack(padx=16, pady=(0, 4))

        self._dl_btn = tk.Button(win, text="⬇  前往下载最新版本", font=_FONT_NORMAL,
                                  bg=self._PINK, fg="#ffffff", cursor="hand2",
                                  relief="flat", padx=12, command=self._open_releases)
        tk.Button(win, text="关闭", bg=self._CARD_BG, fg=self._TEXT,
                  font=_FONT_NORMAL, relief="flat", padx=12,
                  command=win.destroy).pack(pady=10)

    @staticmethod
    def _open_url(url):
        import webbrowser; webbrowser.open(url)

    def _open_releases(self):
        self._open_url(GITHUB_RELEASES)

    def _start_check_update(self):
        self._update_btn.config(state="disabled"); self._status_var.set("正在检查更新，请稍候…"); self._status_lbl.config(fg=self._GRAY)
        threading.Thread(target=self._do_check_update, daemon=True).start()

    def _do_check_update(self):
        result = ("error","未知错误","","")
        try:
            r = fetch_latest_release(); lt = r.get("tag_name","").lstrip("v")
            lu = r.get("html_url",GITHUB_RELEASES); lb = (r.get("body") or "").strip()
            lv = _version_tuple(lt); cv = _version_tuple(VERSION)
            if lv > cv: result = ("new",lt,lu,lb)
            elif lv == cv: result = ("latest",lt,lu,lb)
            else: result = ("dev",lt,lu,lb)
        except urllib.error.URLError as e: result = ("error",str(e),"","")
        except Exception as e: result = ("error",str(e),"","")
        try: self.win.after(0, lambda: self._show_update_result(result))
        except: pass

    def _show_update_result(self, result):
        self._update_btn.config(state="normal"); kind = result[0]
        if kind == "new":
            _, lt, lu, lb = result
            self._status_var.set(f"🎉 发现新版本 v{lt}！（当前 v{VERSION}）\n" + (f"更新内容：{lb[:200]}" if lb else ""))
            self._status_lbl.config(fg=self._PINK); self._dl_btn.pack(pady=(0,6))
        elif kind == "latest":
            self._status_var.set(f"✅ 已是最新版本（v{VERSION}）"); self._status_lbl.config(fg="#4caf50")
        elif kind == "dev":
            self._status_var.set(f"🛠 当前版本（v{VERSION}）比最新发布版（v{result[1]}）更新，可能是开发版。"); self._status_lbl.config(fg=self._PINK)
        else:
            self._status_var.set(f"❌ 检查失败：{result[1]}\n请检查网络连接或访问 GitHub 手动查看。"); self._status_lbl.config(fg="#c0394e")


# ══════════════════════════════════════════════════════════════════════════════
#  TrayApp – system tray icon + orchestration
# ══════════════════════════════════════════════════════════════════════════════
class TrayApp:
    def __init__(self):
        self.cfg = load_config()
        self.pet_win: PetWindow = None
        self.tray: pystray.Icon = None

    def _pet_submenu(self):
        return Menu(*[item(p, self._make_pet_setter(p), checked=lambda _,n=p: self.cfg["pet"]==n)
                      for p in get_available_pets()])

    def _del_pet_submenu(self):
        return Menu(*[item(p, self._make_pet_deleter(p)) for p in get_available_pets()])

    def _make_pet_setter(self, name):
        def fn(icon, mi):
            self.cfg["pet"] = name
            if self.pet_win: self.pet_win.root.after(0, lambda: self.pet_win.set_pet(name))
        return fn

    def _make_pet_deleter(self, name):
        def fn(icon, mi):
            if self.pet_win: self.pet_win.root.after(0, lambda: self.pet_win._delete_pet(name))
        return fn

    def _scale_submenu(self):
        return Menu(*[item(f"x{v:.1f}", self._make_scale_setter(v),
                           checked=lambda _,v=v: abs(self.cfg["scale"]-v)<0.05)
                      for v in [round(x*0.1,1) for x in range(1,21)]])

    def _make_scale_setter(self, val):
        def fn(icon, mi):
            if self.pet_win: self.pet_win.root.after(0, lambda: self.pet_win.set_scale(val))
        return fn

    def _opacity_submenu(self):
        return Menu(*[item(f"{int(v*100)}%", self._make_opacity_setter(v),
                           checked=lambda _,v=v: abs(self.cfg["opacity"]-v)<0.05)
                      for v in [round(x*0.1,1) for x in range(1,11)]])

    def _make_opacity_setter(self, val):
        def fn(icon, mi):
            if self.pet_win: self.pet_win.root.after(0, lambda: self.pet_win.set_opacity(val))
        return fn

    def _speed_submenu(self):
        return Menu(*[item(f"速度 {s}", self._make_speed_setter(s),
                           checked=lambda _,v=s: self.cfg["speed"]==v)
                      for s in range(1,11)])

    def _make_speed_setter(self, val):
        def fn(icon, mi):
            if self.pet_win: self.pet_win.root.after(0, lambda: self.pet_win.set_speed(val))
        return fn

    def _toggle_mouse_follow(self, icon, mi):
        if self.pet_win:
            self.pet_win.root.after(0, lambda: self.pet_win.set_mouse_follow(
                not self.cfg.get("mouse_follow", False)))

    def _toggle_always_on_top(self, icon, mi):
        if self.pet_win:
            self.pet_win.root.after(0, lambda: self.pet_win.set_always_on_top(
                not self.cfg.get("always_on_top", True)))

    def _toggle_autostart(self, icon=None, mi=None):
        cur = get_autostart(); ok = set_autostart(not cur)
        if self.pet_win:
            def _n():
                if ok: messagebox.showinfo("开机自启动", f"开机自启动{'已开启' if not cur else '已关闭'}。", parent=self.pet_win.root)
                else: messagebox.showerror("开机自启动", "修改失败，请检查权限。", parent=self.pet_win.root)
            self.pet_win.root.after(0, _n)

    def _open_music_player(self, icon=None, mi=None):
        if self.pet_win: self.pet_win.root.after(0, self.pet_win._open_music_player)

    def _open_weight_editor(self, icon, mi):
        if self.pet_win: self.pet_win.root.after(0, lambda: WeightEditorDialog(self.pet_win.root, self.pet_win))

    def _open_flip_editor(self, icon, mi):
        if self.pet_win: self.pet_win.root.after(0, lambda: FlipEditorDialog(self.pet_win.root, self.pet_win))

    def _open_creator(self, icon, mi):
        if self.pet_win: self.pet_win.root.after(0, lambda: PetCreatorDialog(self.pet_win.root))

    def _open_about(self, icon, mi):
        if self.pet_win: self.pet_win.root.after(0, lambda: AboutDialog(self.pet_win.root))

    def _quit(self, icon, mi):
        if self.pet_win: self.pet_win.root.after(0, self._do_quit)

    def _do_quit(self):
        if self.pet_win: self.pet_win.save_position(); self.pet_win.root.destroy()
        if self.tray: self.tray.stop()

    def _build_menu(self):
        # System tray right-click menu is intentionally disabled.
        # All controls are available via the pet's own right-click context menu.
        return None

    def _load_tray_icon(self):
        if os.path.exists(APP_ICO):
            try: return Image.open(APP_ICO).convert("RGBA")
            except: pass
        return Image.new("RGBA", (64, 64), (100, 180, 255, 255))

    def run(self):
        tray_img = self._load_tray_icon()
        self.tray = pystray.Icon(APP_NAME, tray_img, APP_NAME, menu=self._build_menu())
        threading.Thread(target=self.tray.run, daemon=True).start()
        self.pet_win = PetWindow(self)
        self.pet_win.run()


if __name__ == "__main__":
    TrayApp().run()
