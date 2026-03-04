"""
Desktop Hachimi – main entry point v1.2.0
Refactored: frontend/backend separation for Windows / Linux (KDE) / macOS support.
  core/            – pure logic (config, gif loading, pet data)
  compat/          – OS-specific helpers (autostart, DPI awareness, trash)
  ui/              – all tkinter UI (pet window, dialogs, music player)
  ui/theme.py      – centralized UI color palette & style constants
  Language/        – zh.json / en.json language strings
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
from core.i18n import init as i18n_init, get as _t, current as lang_current, AVAILABLE_LANGS
from compat.autostart import get_autostart, set_autostart
from compat.dpi import enable_dpi_awareness, get_monitors
from compat.trash import move_to_trash
from ui.helpers import set_window_icon, load_ico_image, get_screen_for_point
from ui.music_player import MusicPlayerDialog, MusicPlayer
import ui.theme as T

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

        self.state              = STATE_IDLE
        self.prev_state         = STATE_IDLE
        self._frame_idx         = 0
        self._after_id          = None
        self.current_frames     = []
        self._current_move_key  = None
        self._flipped_cache     = {}
        self.vx, self.vy        = 0.0, 0.0
        self.going_right        = True
        self.move_target        = None
        self._move_timer        = None
        self._mf_loop_id        = None
        self._mf_leave_id       = None
        self._mf_near_mouse     = False
        self._drag_ox = self._drag_oy = 0
        self.x = float(self.cfg.get("x", 100))
        self.y = float(self.cfg.get("y", 100))
        self._monitors       = get_monitors()
        self._current_screen = None
        self._music_player   = None
        self._music_dialog   = None
        self.pet_data: PetData = None
        self._music_was_playing: bool = False
        self._music_lock: bool = False

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
        self.root.after(500,  self._music_state_tick)
        if self.cfg.get("mouse_follow"):
            self._start_mouse_follow_loop()

    def _music_state_tick(self):
        player = self._music_player
        is_playing = bool(player and player.playing)
        if is_playing:
            if not self._music_lock:
                self._music_lock = True
            if self.state != STATE_DYNAMIC and self.state != STATE_DRAG:
                self._enter_state(STATE_DYNAMIC)
        else:
            if self._music_lock:
                self._music_lock = False
                if self.state != STATE_DRAG:
                    self._autonomous_logic()
        self._music_was_playing = is_playing
        self.root.after(500, self._music_state_tick)

    def _state_tick(self):
        if self.state != STATE_DRAG and not self.cfg.get("mouse_follow"):
            if not self._music_lock:
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
            if self.x < sx:            self.x = sx;       self.vx = abs(self.vx);  self.going_right = True
            if self.x + pw > sx + sw:  self.x = sx+sw-pw; self.vx = -abs(self.vx); self.going_right = False
            if self.y < sy:            self.y = sy;        self.vy = abs(self.vy)
            if self.y + ph > sy + sh:  self.y = sy+sh-ph;  self.vy = -abs(self.vy)
            self.position_window()
        self.root.after(16, self._movement_loop)

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
    def _on_right_click(self, event):
        self._show_context_menu(event.x_root, event.y_root)

    def _show_context_menu(self, x, y):
        cfg = self.cfg
        if hasattr(self, '_ctx_win') and self._ctx_win:
            try: self._ctx_win.destroy()
            except Exception: pass
            self._ctx_win = None

        win = tk.Toplevel(self.root)
        self._ctx_win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=T.SHADOW)

        outer = tk.Frame(win, bg=T.SHADOW, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        frame = tk.Frame(outer, bg=T.BG, padx=0, pady=4)
        frame.pack(fill="both", expand=True)

        def close_menu(event=None):
            try: win.destroy()
            except Exception: pass
            self._ctx_win = None

        def run_cmd(fn):
            close_menu()
            self.root.after(10, fn)

        def make_item(parent, label, command=None, checked=None, is_sep=False, indent=0):
            if is_sep:
                tk.Frame(parent, bg=T.SEP, height=1).pack(fill="x", padx=10, pady=2)
                return
            row = tk.Frame(parent, bg=T.BG, cursor="hand2" if command else "")
            row.pack(fill="x")
            ck_text = "✦" if checked else "  "
            ck_color = T.CHECK if checked else T.BG
            ck = tk.Label(row, text=ck_text, bg=T.BG, fg=ck_color,
                          font=("Microsoft YaHei UI", 9, "bold"), width=2, anchor="center")
            ck.pack(side="left", padx=(6, 0))
            lbl = tk.Label(row, text=label, bg=T.BG, fg=T.TEXT,
                           font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=4)
            lbl.pack(side="left", fill="x", expand=True, padx=indent)
            arrow_lbl = None
            if command is None and not is_sep:
                arrow_lbl = tk.Label(row, text="▸", bg=T.BG, fg=T.PINK,
                                     font=("Microsoft YaHei UI", 9), padx=4)
                arrow_lbl.pack(side="right")
            def on_enter(e, r=row, ck_w=ck, l=lbl, aw=arrow_lbl):
                r.config(bg=T.HOVER_BG); ck_w.config(bg=T.HOVER_BG); l.config(bg=T.HOVER_BG)
                if aw: aw.config(bg=T.HOVER_BG)
            def on_leave(e, r=row, ck_w=ck, l=lbl, aw=arrow_lbl):
                r.config(bg=T.BG); ck_w.config(bg=T.BG); l.config(bg=T.BG)
                if aw: aw.config(bg=T.BG)
            for w in (row, ck, lbl):
                w.bind("<Enter>", on_enter); w.bind("<Leave>", on_leave)
                if command: w.bind("<Button-1>", lambda e, fn=command: run_cmd(fn))
            if arrow_lbl:
                arrow_lbl.bind("<Enter>", on_enter); arrow_lbl.bind("<Leave>", on_leave)
            return row

        _any_sub_open = [False]  # 共享标志：是否有子菜单正在显示

        def make_submenu_item(parent, label, build_sub_fn):
            row = tk.Frame(parent, bg=T.BG, cursor="hand2")
            row.pack(fill="x")
            ck = tk.Label(row, text="  ", bg=T.BG, fg=T.BG,
                          font=("Microsoft YaHei UI", 9, "bold"), width=2, anchor="center")
            ck.pack(side="left", padx=(6, 0))
            lbl = tk.Label(row, text=label, bg=T.BG, fg=T.TEXT,
                           font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=4)
            lbl.pack(side="left", fill="x", expand=True)
            arrow = tk.Label(row, text="▸", bg=T.BG, fg=T.PINK,
                             font=("Microsoft YaHei UI", 9), padx=4)
            arrow.pack(side="right")
            _sub_win  = [None]
            _close_id = [None]   # pending after-id for delayed close

            def _cancel_close():
                if _close_id[0]:
                    try: self.root.after_cancel(_close_id[0])
                    except Exception: pass
                    _close_id[0] = None

            def close_sub():
                _cancel_close()
                if _sub_win[0]:
                    try: _sub_win[0].destroy()
                    except: pass
                    _sub_win[0] = None
                _any_sub_open[0] = False

            def _mouse_inside_sub():
                """Return True if the pointer is currently over the sub-window."""
                s = _sub_win[0]
                if not s:
                    return False
                try:
                    px = s.winfo_pointerx()
                    py = s.winfo_pointery()
                    sx2 = s.winfo_rootx()
                    sy2 = s.winfo_rooty()
                    sw2 = s.winfo_width()
                    sh2 = s.winfo_height()
                    return sx2 <= px <= sx2 + sw2 and sy2 <= py <= sy2 + sh2
                except Exception:
                    return False

            def _delayed_close():
                _close_id[0] = None
                if not _mouse_inside_sub():
                    close_sub()

            def open_sub(e, r=row):
                _cancel_close()
                close_sub()
                _any_sub_open[0] = True
                sx = win.winfo_x() + win.winfo_width()
                sy = win.winfo_y() + r.winfo_y()
                sub = tk.Toplevel(self.root)
                _sub_win[0] = sub
                sub.overrideredirect(True)
                sub.attributes("-topmost", True)
                sub.configure(bg=T.SHADOW)
                outer_s = tk.Frame(sub, bg=T.SHADOW, padx=1, pady=1)
                outer_s.pack(fill="both", expand=True)
                sf = tk.Frame(outer_s, bg=T.BG, padx=0, pady=4)
                sf.pack(fill="both", expand=True)
                build_sub_fn(sf, sub, close_sub)
                sub.update_idletasks()
                sw_w = sub.winfo_reqwidth(); sh_h = sub.winfo_reqheight()
                screen_w = self.root.winfo_screenwidth(); screen_h = self.root.winfo_screenheight()
                if sx + sw_w > screen_w: sx = win.winfo_x() - sw_w
                if sy + sh_h > screen_h: sy = screen_h - sh_h
                sub.geometry(f"+{sx}+{sy}"); sub.lift()
                # Close sub when pointer leaves it (with small grace delay)
                sub.bind("<Leave>", lambda e: _schedule_close())

            def _schedule_close():
                _cancel_close()
                _close_id[0] = self.root.after(120, _delayed_close)

            def on_enter(e, r=row, widgets=(ck, lbl, arrow)):
                _cancel_close()          # mouse came back – cancel any pending close
                r.config(bg=T.HOVER_BG)
                for w in widgets: w.config(bg=T.HOVER_BG)
                open_sub(e, r)

            def on_leave(e, r=row, widgets=(ck, lbl, arrow)):
                r.config(bg=T.BG)
                for w in widgets: w.config(bg=T.BG)
                _schedule_close()        # start a short timer; cancel if mouse enters sub

            for w in (row, ck, lbl, arrow):
                w.bind("<Enter>", on_enter); w.bind("<Leave>", on_leave)

        # Header
        header = tk.Frame(frame, bg=T.HEADER_BG)
        header.pack(fill="x", padx=0, pady=(0, 4))
        tk.Label(header, text="🐾  Desktop Hachimi", bg=T.HEADER_BG,
                 fg=T.WHITE, font=("Microsoft YaHei UI", 10, "bold"),
                 padx=12, pady=6).pack(side="left")

        def _build_simple_sub(items_fn, sf, sub, close_sub_fn):
            for p, is_cur, cmd in items_fn():
                r = tk.Frame(sf, bg=T.BG, cursor="hand2"); r.pack(fill="x")
                ck_t = "✦" if is_cur else "  "; ck_c = T.CHECK if is_cur else T.BG
                ck_l = tk.Label(r, text=ck_t, bg=T.BG, fg=ck_c,
                                font=("Microsoft YaHei UI", 9, "bold"), width=2)
                ck_l.pack(side="left", padx=(6,0))
                tl = tk.Label(r, text=p, bg=T.BG, fg=T.TEXT,
                              font=("Microsoft YaHei UI", 10), anchor="w", padx=4, pady=4)
                tl.pack(side="left", fill="x", expand=True)
                def _on_e(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=T.HOVER_BG); cc.config(bg=T.HOVER_BG); tt.config(bg=T.HOVER_BG)
                def _on_l(e, rr=r, cc=ck_l, tt=tl): rr.config(bg=T.BG); cc.config(bg=T.BG); tt.config(bg=T.BG)
                def _sub_item_click(e, c=cmd, cf=close_sub_fn):
                    try: cf()
                    except Exception: pass
                    try: close_menu()
                    except Exception: pass
                    self.root.after(10, c)
                for w in (r, ck_l, tl):
                    w.bind("<Enter>", _on_e); w.bind("<Leave>", _on_l)
                    w.bind("<Button-1>", _sub_item_click)

        def build_pet_sub(sf, sub, csf):
            _build_simple_sub(
                lambda: [(p, p == cfg["pet"], lambda n=p: self.set_pet(n)) for p in get_available_pets()],
                sf, sub, csf)

        def build_del_sub(sf, sub, csf):
            for p in get_available_pets():
                r = tk.Frame(sf, bg=T.BG, cursor="hand2"); r.pack(fill="x")
                tl = tk.Label(r, text=p, bg=T.BG, fg="#c0394e",
                              font=("Microsoft YaHei UI", 10), anchor="w", padx=16, pady=4)
                tl.pack(side="left", fill="x", expand=True)
                def _on_e(e, rr=r, tt=tl): rr.config(bg=T.HOVER_BG); tt.config(bg=T.HOVER_BG)
                def _on_l(e, rr=r, tt=tl): rr.config(bg=T.BG); tt.config(bg=T.BG)
                def _del_click(e, n=p, cf=csf):
                    try: cf()
                    except Exception: pass
                    try: close_menu()
                    except Exception: pass
                    self.root.after(10, lambda name=n: self._delete_pet(name))
                for w in (r, tl): w.bind("<Enter>", _on_e); w.bind("<Leave>", _on_l)
                r.bind("<Button-1>", _del_click)
                tl.bind("<Button-1>", _del_click)

        def build_scale_sub(sf, sub, csf):
            _build_simple_sub(
                lambda: [(f"x{v:.1f}", abs(cfg["scale"]-v) < 0.05, lambda val=v: self.set_scale(val))
                         for v in [round(x*0.1,1) for x in range(1,21)]],
                sf, sub, csf)

        def build_opacity_sub(sf, sub, csf):
            _build_simple_sub(
                lambda: [(f"{int(v*100)}%", abs(cfg["opacity"]-v) < 0.05, lambda val=v: self.set_opacity(val))
                         for v in [round(x*0.1,1) for x in range(1,11)]],
                sf, sub, csf)

        def build_speed_sub(sf, sub, csf):
            _build_simple_sub(
                lambda: [(_t("menu_speed_item", s=s), cfg["speed"] == s, lambda val=s: self.set_speed(val))
                         for s in range(1,11)],
                sf, sub, csf)

        def build_lang_sub(sf, sub, csf):
            _build_simple_sub(
                lambda: [(label, lang_current() == code,
                          lambda c=code: self.set_language(c))
                         for code, label in AVAILABLE_LANGS.items()],
                sf, sub, csf)

        make_submenu_item(frame, _t("menu_switch_pet"), build_pet_sub)
        make_submenu_item(frame, _t("menu_delete_pet"), build_del_sub)
        make_submenu_item(frame, _t("menu_pet_size"),   build_scale_sub)
        make_submenu_item(frame, _t("menu_opacity"),    build_opacity_sub)
        make_submenu_item(frame, _t("menu_speed"),      build_speed_sub)
        make_submenu_item(frame, _t("menu_language"),   build_lang_sub)

        make_item(frame, "", is_sep=True)

        make_item(frame, _t("menu_mouse_follow"), checked=cfg.get("mouse_follow", False),
                  command=lambda: self.set_mouse_follow(not self.cfg.get("mouse_follow", False)))
        make_item(frame, _t("menu_always_on_top"), checked=cfg.get("always_on_top", True),
                  command=lambda: self.set_always_on_top(not self.cfg.get("always_on_top", True)))
        make_item(frame, _t("menu_autostart"), checked=get_autostart(),
                  command=self.app._toggle_autostart)

        make_item(frame, "", is_sep=True)

        make_item(frame, _t("menu_music_player"),    command=self._open_music_player)
        make_item(frame, _t("menu_weight_editor"),   command=lambda: WeightEditorDialog(self.root, self))
        make_item(frame, _t("menu_flip_editor"),     command=lambda: FlipEditorDialog(self.root, self))
        make_item(frame, _t("menu_create_pet"),      command=lambda: PetCreatorDialog(self.root))
        make_item(frame, _t("menu_about"),           command=lambda: AboutDialog(self.root))

        make_item(frame, "", is_sep=True)

        quit_row = tk.Frame(frame, bg=T.BG, cursor="hand2")
        quit_row.pack(fill="x", padx=0, pady=(0,2))
        ck_q = tk.Label(quit_row, text="  ", bg=T.BG, width=2, font=("Microsoft YaHei UI", 9))
        ck_q.pack(side="left", padx=(6,0))
        lbl_q = tk.Label(quit_row, text=_t("menu_quit"), bg=T.BG, fg=T.PINK,
                         font=("Microsoft YaHei UI", 10, "bold"), anchor="w", padx=4, pady=4)
        lbl_q.pack(side="left", fill="x", expand=True)
        def _on_eq(e): quit_row.config(bg=T.HOVER_BG); ck_q.config(bg=T.HOVER_BG); lbl_q.config(bg=T.HOVER_BG)
        def _on_lq(e): quit_row.config(bg=T.BG); ck_q.config(bg=T.BG); lbl_q.config(bg=T.BG)
        for w in (quit_row, ck_q, lbl_q):
            w.bind("<Enter>", _on_eq); w.bind("<Leave>", _on_lq)
            w.bind("<Button-1>", lambda e: run_cmd(self.app._do_quit))

        win.update_idletasks()
        mw_req = win.winfo_reqwidth(); mh_req = win.winfo_reqheight()
        sw_sc = self.root.winfo_screenwidth(); sh_sc = self.root.winfo_screenheight()
        mx_pos = x if x + mw_req <= sw_sc else x - mw_req
        my_pos = y if y + mh_req <= sh_sc else y - mh_req
        win.geometry(f"+{mx_pos}+{my_pos}")
        win.deiconify(); win.lift(); win.focus_set()

        def on_focus_out(e):
            try:
                # 有子菜单打开时不关闭主菜单（子菜单是self.root的子窗口，不是win的）
                if _any_sub_open[0]:
                    return
                if win.winfo_exists(): close_menu()
            except Exception: pass

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

    def _delete_pet(self, name: str):
        pets = get_available_pets()
        if len(pets) <= 1:
            messagebox.showwarning(_t("delete_pet_cannot"), _t("delete_pet_cannot_msg"), parent=self.root)
            return
        if not messagebox.askyesno(_t("delete_pet_confirm_title"),
                                   _t("delete_pet_confirm_msg", name=name),
                                   parent=self.root):
            return
        ok = move_to_trash(os.path.join(PETS_DIR, name))
        if ok:
            if self.cfg.get("pet") == name:
                remaining = [p for p in get_available_pets() if p != name]
                if remaining: self.set_pet(remaining[0])
            messagebox.showinfo(_t("delete_pet_success"), _t("delete_pet_success_msg", name=name), parent=self.root)
        else:
            messagebox.showerror(_t("delete_pet_fail"), _t("delete_pet_fail_msg"), parent=self.root)

    def set_pet(self, name):
        self.cfg["pet"] = name; save_config(self.cfg); self.reload_pet()

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

    def set_language(self, lang_code: str):
        self.cfg["language"] = lang_code; save_config(self.cfg)
        from core.i18n import init as i18n_init
        i18n_init(lang_code)

    def save_position(self):
        self.cfg["x"] = int(self.x); self.cfg["y"] = int(self.y); save_config(self.cfg)

    def run(self):
        self._movement_loop()
        self.root.after(100, self._update_current_screen)
        self.root.mainloop()

    def destroy(self):
        self.save_position(); self.root.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  Shared dialog helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_dialog_header(win, icon_text, title, subtitle=None):
    header = tk.Frame(win, bg=T.HEADER_BG)
    header.pack(fill="x")
    tk.Label(header, text=f"{icon_text}  {title}", bg=T.HEADER_BG,
             fg=T.WHITE, font=T.FONT_LARGE, padx=16, pady=10).pack(side="left")
    if subtitle:
        tk.Label(win, text=subtitle, bg=T.BG, fg=T.TEXT_LIGHT,
                 font=T.FONT_SMALL).pack(pady=(4, 0))


def _make_dialog_buttons(parent, save_cmd=None, cancel_cmd=None,
                          save_label=None, cancel_label=None):
    if save_label is None:   save_label   = _t("btn_save")
    if cancel_label is None: cancel_label = _t("btn_close")
    bf = tk.Frame(parent, bg=T.BG)
    bf.pack(pady=14)
    if save_cmd:
        tk.Button(bf, text=save_label, command=save_cmd, **T.BTN_SAVE).pack(side="left", padx=8)
    if cancel_cmd:
        tk.Button(bf, text=cancel_label, command=cancel_cmd, **T.BTN_CLOSE).pack(side="left", padx=8)
    return bf


def _styled_card(parent, **kw):
    return tk.Frame(parent, bg=T.CARD_BG, padx=16, pady=10, **kw)


def _card_label(parent, text, fg=None, font=None, **kw):
    return tk.Label(parent, text=text, bg=T.CARD_BG, fg=fg or T.TEXT,
                    font=font or T.FONT_NORMAL, **kw)


def _styled_label(parent, text, fg=None, font=None, **kw):
    return tk.Label(parent, text=text, bg=T.BG, fg=fg or T.TEXT,
                    font=font or T.FONT_NORMAL, **kw)


def _spinbox(parent, var, from_=1, to=999, width=6):
    return tk.Spinbox(parent, from_=from_, to=to, textvariable=var, width=width,
                      **T.SPINBOX_STYLE)


# ══════════════════════════════════════════════════════════════════════════════
#  Dialogs
# ══════════════════════════════════════════════════════════════════════════════

class WeightEditorDialog:
    def __init__(self, parent_root, pet_win: PetWindow):
        self.pet_win = pet_win
        self.win = tk.Toplevel(parent_root)
        self.win.title(_t("weight_editor_title"))
        self.win.configure(bg=T.BG)
        set_window_icon(self.win)
        self.win.resizable(False, False)
        self._build_ui()


    def _build_ui(self):
        win = self.win; pd = self.pet_win.pet_data
        pad = {"padx": 10, "pady": 5}

        _make_dialog_header(win, "⚖️", _t("weight_editor_title"), _t("weight_editor_subtitle", name=pd.name))

        card = _styled_card(win)
        card.pack(fill="x", padx=16, pady=(12, 4))
        _card_label(card, _t("weight_editor_hint"),
                    fg=T.TEXT_LIGHT, font=T.FONT_SMALL).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        row = 1
        _card_label(card, _t("weight_dynamic"), anchor="e").grid(row=row, column=0, sticky="e", **pad)
        self._dyn_var = tk.IntVar(value=pd.dynamic_weight)
        _spinbox(card, self._dyn_var).grid(row=row, column=1, sticky="w", **pad)
        row += 1
        tk.Frame(card, bg=T.SEP, height=1).grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=4); row += 1

        self._idle_vars = []
        idle_count = len(pd.idle_variants)
        if idle_count == 0:
            _card_label(card, _t("weight_idle_no"), fg=T.TEXT_LIGHT).grid(row=row, column=0, columnspan=3, **pad); row += 1
        elif idle_count == 1:
            _card_label(card, _t("weight_idle"), anchor="e").grid(row=row, column=0, sticky="e", **pad)
            v = tk.IntVar(value=pd.idle_weights[0] if pd.idle_weights else 2)
            _spinbox(card, v).grid(row=row, column=1, sticky="w", **pad)
            self._idle_vars.append(v); row += 1
        else:
            _card_label(card, _t("weight_idle_multi"), font=T.FONT_BOLD).grid(row=row, column=0, columnspan=3, sticky="w", padx=10); row += 1
            for i in range(idle_count):
                _card_label(card, _t("weight_idle_n", n=i+1), anchor="e").grid(row=row, column=0, sticky="e", **pad)
                v = tk.IntVar(value=pd.idle_weights[i] if i < len(pd.idle_weights) else 2)
                _spinbox(card, v).grid(row=row, column=1, sticky="w", **pad)
                self._idle_vars.append(v); row += 1

        tk.Frame(card, bg=T.SEP, height=1).grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=4); row += 1

        self._move_vars = []
        move_count = len(pd.move_variants)
        if move_count == 0:
            _card_label(card, _t("weight_move_no"), fg=T.TEXT_LIGHT).grid(row=row, column=0, columnspan=3, **pad); row += 1
        elif move_count == 1:
            _card_label(card, _t("weight_move"), anchor="e").grid(row=row, column=0, sticky="e", **pad)
            v = tk.IntVar(value=pd.move_weights[0] if pd.move_weights else 1)
            _spinbox(card, v).grid(row=row, column=1, sticky="w", **pad)
            self._move_vars.append(v); row += 1
        else:
            _card_label(card, _t("weight_move_multi"), font=T.FONT_BOLD).grid(row=row, column=0, columnspan=3, sticky="w", padx=10); row += 1
            for i in range(move_count):
                _card_label(card, _t("weight_move_n", n=i+1), anchor="e").grid(row=row, column=0, sticky="e", **pad)
                v = tk.IntVar(value=pd.move_weights[i] if i < len(pd.move_weights) else 1)
                _spinbox(card, v).grid(row=row, column=1, sticky="w", **pad)
                self._move_vars.append(v); row += 1

        self._preview_label = tk.Label(win, text="", bg=T.BG, fg=T.TEXT_LIGHT, font=T.FONT_SMALL)
        self._preview_label.pack(padx=10, pady=(6, 0))
        self._update_preview()
        for var in [self._dyn_var] + self._idle_vars + self._move_vars:
            var.trace_add("write", lambda *_: self._update_preview())

        _make_dialog_buttons(win, save_cmd=self._save, cancel_cmd=self.win.destroy)

    def _safe_int(self, var, fallback=1):
        try: return max(1, int(var.get()))
        except: return fallback

    def _update_preview(self):
        dw = self._safe_int(self._dyn_var)
        iw = sum(self._safe_int(v) for v in self._idle_vars) if self._idle_vars else 0
        mw = sum(self._safe_int(v) for v in self._move_vars) if self._move_vars else 0
        total = dw + iw + mw
        if total == 0: self._preview_label.config(text=""); return
        self._preview_label.config(text=_t("weight_preview") + "  |  ".join([
            _t("weight_preview_dynamic", p=dw/total*100),
            _t("weight_preview_idle",    p=iw/total*100),
            _t("weight_preview_move",    p=mw/total*100)]))

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
        messagebox.showinfo(_t("weight_save_ok"), _t("weight_save_ok_msg"), parent=self.win)
        self.win.destroy()


class FlipEditorDialog:
    def __init__(self, parent_root, pet_win: PetWindow):
        self.pet_win = pet_win
        self.win = tk.Toplevel(parent_root)
        self.win.title(_t("flip_editor_title"))
        self.win.configure(bg=T.BG)
        set_window_icon(self.win)
        self.win.resizable(False, False)
        self._rows: list[dict] = []
        self._build_ui()

    @staticmethod
    def _variant_key(index, total):
        return "move" if total == 1 else f"move{index+1}"

    def _build_ui(self):
        win = self.win; pd = self.pet_win.pet_data
        _make_dialog_header(win, "↔️", _t("flip_editor_title"), _t("flip_editor_subtitle", name=pd.name))

        info = tk.Frame(win, bg=T.CARD_BG, padx=14, pady=8)
        info.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(info,
            text=_t("flip_editor_hint"),
            bg=T.CARD_BG, fg=T.TEXT_LIGHT, justify="left", font=T.FONT_SMALL).pack(anchor="w")

        mc = len(pd.move_variants)
        if mc == 0:
            _styled_label(win, _t("flip_no_move"), fg=T.TEXT_LIGHT).pack(padx=16, pady=8)
            _make_dialog_buttons(win, cancel_cmd=self.win.destroy, cancel_label=_t("flip_close"))
            return

        card = _styled_card(win)
        card.pack(fill="x", padx=16, pady=4)
        pad = {"padx": 8, "pady": 5}

        for lbl, col in [(_t("flip_col_image"), 0), (_t("flip_col_enable"), 1), (_t("flip_col_dir"), 2), (_t("flip_col_preview"), 3)]:
            tk.Label(card, text=lbl, bg=T.CARD_BG, fg=T.PINK,
                     font=T.FONT_BOLD, width=(10 if col == 0 else None)).grid(row=0, column=col, **pad)
        tk.Frame(card, bg=T.SEP, height=1).grid(row=1, column=0, columnspan=4, sticky="ew", padx=4, pady=2)

        for i in range(mc):
            key = self._variant_key(i, mc)
            ex  = pd.move_flip_info.get(key, {})
            ev  = tk.BooleanVar(value=ex.get("enabled", False))
            dv  = tk.StringVar(value=ex.get("default_dir", "left"))
            r   = 2 + i
            tk.Label(card, text="move.gif" if mc == 1 else f"move{i+1}.gif",
                     bg=T.CARD_BG, fg=T.TEXT, anchor="e").grid(row=r, column=0, sticky="e", **pad)
            tk.Checkbutton(card, variable=ev, bg=T.CARD_BG, fg=T.PINK,
                           selectcolor=T.BG, activebackground=T.CARD_BG,
                           command=self._make_row_refresh(i)).grid(row=r, column=1, **pad)
            cb = ttk.Combobox(card, textvariable=dv, values=["left", "right"], width=6, state="readonly")
            cb.grid(row=r, column=2, **pad)
            cb.bind("<<ComboboxSelected>>", lambda e, idx=i: self._refresh_preview(idx))
            pl = tk.Label(card, text="", bg=T.CARD_BG, fg=T.PINK, width=24, anchor="w", font=T.FONT_SMALL)
            pl.grid(row=r, column=3, padx=(0, 8))
            self._rows.append({"key": key, "enabled_var": ev, "dir_var": dv, "preview_lbl": pl})
            self._refresh_preview(i)

        _make_dialog_buttons(win, save_cmd=self._save, cancel_cmd=self.win.destroy)

    def _make_row_refresh(self, idx):
        return lambda: self._refresh_preview(idx)

    def _refresh_preview(self, idx):
        row = self._rows[idx]; en = row["enabled_var"].get(); d = row["dir_var"].get()
        if not en:        text = _t("flip_disabled")
        elif d == "left": text = _t("flip_left")
        else:             text = _t("flip_right")
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
        messagebox.showinfo(_t("flip_save_ok"), _t("flip_save_ok_msg"), parent=self.win)
        self.win.destroy()


class PetCreatorDialog:
    def __init__(self, parent_root):
        self.win = tk.Toplevel(parent_root)
        self.win.title(_t("creator_title"))
        set_window_icon(self.win)
        self.win.configure(bg=T.BG)
        self.win.resizable(False, False)
        self._files = {"icon": tk.StringVar(), "dynamic": tk.StringVar(), "drag": tk.StringVar()}
        self._idle_entries = []; self._move_entries = []
        self._build_ui()

    def _entry(self, parent, var, width=24):
        return tk.Entry(parent, textvariable=var, width=width, **T.ENTRY_STYLE)

    def _build_ui(self):
        win = self.win; pad = {"padx": 8, "pady": 4}
        _make_dialog_header(win, "🎨", _t("creator_title"))

        card = _styled_card(win)
        card.pack(fill="x", padx=16, pady=(10, 4))
        _card_label(card, _t("creator_name")).grid(row=0, column=0, sticky="e", **pad)
        self.name_var = tk.StringVar()
        self._entry(card, self.name_var).grid(row=0, column=1, columnspan=2, sticky="w", **pad)

        for row, key, label in [(1, "icon", _t("creator_icon")), (2, "dynamic", _t("creator_dynamic")), (3, "drag", _t("creator_drag"))]:
            ext = "*.ico" if key == "icon" else "*.gif"
            _card_label(card, label).grid(row=row, column=0, sticky="e", **pad)
            self._entry(card, self._files[key]).grid(row=row, column=1, **pad)
            tk.Button(card, text=_t("creator_browse"),
                      command=lambda k=key, e=ext: self._browse(k, [(k.upper(), e)]),
                      **T.BTN_NORMAL).grid(row=row, column=2, **pad)

        _card_label(card, _t("creator_dynamic_weight")).grid(row=2, column=3, **pad)
        self.dyn_weight = tk.IntVar(value=3)
        _spinbox(card, self.dyn_weight, width=4).grid(row=2, column=4, **pad)

        tk.Label(win, text=_t("creator_idle_section"), bg=T.BG, fg=T.TEXT_LIGHT, font=T.FONT_SMALL).pack(pady=(8, 2))
        self._idle_frame = tk.Frame(win, bg=T.CARD_BG); self._idle_frame.pack(fill="x", padx=16)
        self._add_idle_row()
        tk.Button(win, text=_t("creator_add_idle"), command=self._add_idle_row, **T.BTN_NORMAL).pack(pady=4)

        tk.Label(win, text=_t("creator_move_section"), bg=T.BG, fg=T.TEXT_LIGHT, font=T.FONT_SMALL).pack(pady=(6, 2))
        self._move_frame = tk.Frame(win, bg=T.CARD_BG); self._move_frame.pack(fill="x", padx=16)
        self._add_move_row()
        tk.Button(win, text=_t("creator_add_move"), command=self._add_move_row, **T.BTN_NORMAL).pack(pady=4)

        _make_dialog_buttons(win, save_cmd=self._save, cancel_cmd=self.win.destroy, save_label=_t("creator_save"))

    def _browse(self, key, filetypes):
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p: self._files[key].set(p)

    def _browse_var(self, var, filetypes):
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p: var.set(p)

    def _add_idle_row(self):
        f = self._idle_frame; row = len(self._idle_entries)
        pv = tk.StringVar(); wv = tk.IntVar(value=2)
        tk.Label(f, text=f"idle {row+1}:", bg=T.CARD_BG, fg=T.TEXT).grid(row=row, column=0, padx=6)
        tk.Entry(f, textvariable=pv, width=24, **T.ENTRY_STYLE).grid(row=row, column=1, padx=4, pady=3)
        tk.Button(f, text=_t("creator_browse"), command=lambda v=pv: self._browse_var(v, [("GIF", "*.gif")]),
                  **T.BTN_NORMAL).grid(row=row, column=2, padx=4)
        tk.Label(f, text=_t("creator_weight"), bg=T.CARD_BG, fg=T.TEXT_LIGHT).grid(row=row, column=3, padx=4)
        _spinbox(f, wv, width=4).grid(row=row, column=4, padx=4)
        self._idle_entries.append((pv, wv))

    def _add_move_row(self):
        f = self._move_frame; row = len(self._move_entries)
        pv = tk.StringVar(); wv = tk.IntVar(value=1); fv = tk.BooleanVar(); dv = tk.StringVar(value="left")
        tk.Label(f, text=f"move {row+1}:", bg=T.CARD_BG, fg=T.TEXT).grid(row=row, column=0, padx=6)
        tk.Entry(f, textvariable=pv, width=24, **T.ENTRY_STYLE).grid(row=row, column=1, padx=4, pady=3)
        tk.Button(f, text=_t("creator_browse"), command=lambda v=pv: self._browse_var(v, [("GIF", "*.gif")]),
                  **T.BTN_NORMAL).grid(row=row, column=2, padx=4)
        tk.Label(f, text=_t("creator_weight"), bg=T.CARD_BG, fg=T.TEXT_LIGHT).grid(row=row, column=3, padx=4)
        _spinbox(f, wv, width=4).grid(row=row, column=4, padx=4)
        tk.Checkbutton(f, text=_t("creator_flip"), variable=fv, bg=T.CARD_BG, fg=T.PINK,
                       selectcolor=T.BG, activebackground=T.CARD_BG).grid(row=row, column=5, padx=4)
        ttk.Combobox(f, textvariable=dv, values=["left", "right"], width=5, state="readonly").grid(row=row, column=6, padx=4)
        self._move_entries.append((pv, wv, fv, dv))

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning(_t("creator_no_name"), _t("creator_no_name_msg"), parent=self.win); return
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
        messagebox.showinfo(_t("creator_ok"), _t("creator_ok_msg", name=name), parent=self.win)
        self.win.destroy()


class AboutDialog:
    def __init__(self, parent_root):
        self.win = tk.Toplevel(parent_root)
        win = self.win
        win.title(_t("about_title", app=APP_NAME))
        set_window_icon(win)
        win.configure(bg=T.BG)
        win.resizable(False, False)
        self._build_ui()

    def _build_ui(self):
        win = self.win
        _make_dialog_header(win, "🐾", APP_NAME)

        card = _styled_card(win)
        card.pack(fill="x", padx=20, pady=(14, 8))
        _card_label(card, _t("about_version", version=VERSION)).pack(anchor="w", pady=2)
        _card_label(card, _t("about_author", author=AUTHOR, email=AUTHOR_EMAIL), fg=T.TEXT_LIGHT).pack(anchor="w", pady=2)
        link = tk.Label(card, text=GITHUB_URL, bg=T.CARD_BG, fg=T.PINK,
                        cursor="hand2", font=T.FONT_SMALL)
        link.pack(anchor="w", pady=2)
        link.bind("<Button-1>", lambda e: self._open_url(GITHUB_URL))

        self._status_var = tk.StringVar(value="")
        self._status_lbl = tk.Label(win, textvariable=self._status_var, bg=T.BG,
                                    fg=T.TEXT_LIGHT, font=T.FONT_SMALL, wraplength=320)
        self._status_lbl.pack(padx=16, pady=(4, 0))

        self._dl_btn = tk.Button(win, text=_t("about_download"),
                                  bg=T.PINK, fg=T.WHITE, cursor="hand2", relief="flat",
                                  padx=12, font=T.FONT_NORMAL,
                                  activebackground="#c03060", activeforeground=T.WHITE,
                                  command=self._open_releases)

        bf = tk.Frame(win, bg=T.BG); bf.pack(pady=10)
        self._update_btn = tk.Button(bf, text=_t("about_check_update"),
                                      command=self._start_check_update, **T.BTN_NORMAL)
        self._update_btn.pack(side="left", padx=6)
        tk.Button(bf, text=_t("about_close"), command=win.destroy, **T.BTN_CLOSE).pack(side="left", padx=6)

    @staticmethod
    def _open_url(url):
        import webbrowser; webbrowser.open(url)

    def _open_releases(self):
        self._open_url(GITHUB_RELEASES)

    def _start_check_update(self):
        self._update_btn.config(state="disabled")
        self._status_var.set(_t("about_checking"))
        self._status_lbl.config(fg=T.TEXT_LIGHT)
        threading.Thread(target=self._do_check_update, daemon=True).start()

    def _do_check_update(self):
        result = ("error", "unknown error", "", "")
        try:
            r = fetch_latest_release()
            lt = r.get("tag_name", "").lstrip("v"); lu = r.get("html_url", GITHUB_RELEASES)
            lb = (r.get("body") or "").strip()
            lv = _version_tuple(lt); cv = _version_tuple(VERSION)
            if lv > cv:    result = ("new",    lt, lu, lb)
            elif lv == cv: result = ("latest", lt, lu, lb)
            else:          result = ("dev",    lt, lu, lb)
        except urllib.error.URLError as e: result = ("error", str(e), "", "")
        except Exception as e:             result = ("error", str(e), "", "")
        try: self.win.after(0, lambda: self._show_update_result(result))
        except: pass

    def _show_update_result(self, result):
        self._update_btn.config(state="normal"); kind = result[0]
        if kind == "new":
            _, lt, lu, lb = result
            notes = _t("about_new_notes", notes=lb[:200]) if lb else ""
            self._status_var.set(_t("about_new", latest=lt, current=VERSION, notes=notes))
            self._status_lbl.config(fg=T.PINK); self._dl_btn.pack(pady=(0, 6))
        elif kind == "latest":
            self._status_var.set(_t("about_latest", version=VERSION))
            self._status_lbl.config(fg=T.GREEN)
        elif kind == "dev":
            self._status_var.set(_t("about_dev", current=VERSION, latest=result[1]))
            self._status_lbl.config(fg=T.PINK)
        else:
            self._status_var.set(_t("about_error", error=result[1]))
            self._status_lbl.config(fg="#c03060")


# ══════════════════════════════════════════════════════════════════════════════
#  TrayApp – system tray icon  (NO right-click context menu)
# ══════════════════════════════════════════════════════════════════════════════
class TrayApp:
    """
    Manages the system tray icon.
    The tray icon has NO full right-click menu – all interactions go through
    the pet's right-click context menu instead.
    A minimal "Exit" item is kept so users can always quit even if the pet
    window is hidden or unreachable.
    """

    def __init__(self):
        self.cfg = load_config()
        self.pet_win: PetWindow = None
        self.tray: pystray.Icon = None

    def _toggle_autostart(self, icon=None, mi=None):
        cur = get_autostart(); ok = set_autostart(not cur)
        if self.pet_win:
            def _notify():
                state = _t("autostart_on") if not cur else _t("autostart_off")
                if ok: messagebox.showinfo(_t("autostart_title"), _t("autostart_msg", state=state), parent=self.pet_win.root)
                else:  messagebox.showerror(_t("autostart_title"), _t("autostart_err"), parent=self.pet_win.root)
            self.pet_win.root.after(0, _notify)

    def _do_quit(self):
        if self.pet_win:
            self.pet_win.save_position()
            self.pet_win.root.destroy()
        if self.tray:
            self.tray.stop()

    def _on_tray_activate(self, icon, item):
        """Activate (left-click / double-click): bring pet window to front."""
        if self.pet_win:
            self.pet_win.root.after(0, lambda: self.pet_win.root.lift())

    def _load_tray_icon(self):
        if os.path.exists(APP_ICO):
            try: return Image.open(APP_ICO).convert("RGBA")
            except: pass
        return Image.new("RGBA", (64, 64), (224, 69, 122, 255))

    def run(self):
        tray_img = self._load_tray_icon()
        # Minimal tray menu: only "Exit" remains.
        # All other controls are on the pet's own right-click context menu.
        minimal_menu = Menu(
            item(_t("tray_quit"),
                 lambda icon, mi: self.pet_win.root.after(0, self._do_quit))
        )
        self.tray = pystray.Icon(APP_NAME, tray_img, APP_NAME, menu=minimal_menu)
        self.tray.default_action = self._on_tray_activate
        threading.Thread(target=self.tray.run, daemon=True).start()
        self.pet_win = PetWindow(self)
        self.pet_win.run()


if __name__ == "__main__":
    cfg = load_config()
    i18n_init(cfg.get("language", "zh"))
    TrayApp().run()
