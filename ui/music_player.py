"""
ui/music_player.py – MusicPlayerDialog: pixel-art music player window.

Playback modes:  loop_all | loop_one | loop_none
Controls:        prev, play/pause, next, add, delete
Music lives in:  <BASE_DIR>/Music/

Changes:
  - Added draggable progress bar showing current playback position & time
  - Fixed: closing dialog does NOT stop music / auto-loop; a background
    thread continues to handle end-of-track logic even when the window is gone
"""

import os
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from core.config import MUSIC_DIR, FONT_NORMAL, FONT_BOLD, FONT_SMALL
from core.config import get_music_files
from ui.helpers import set_window_icon, load_ico_image
from compat.trash import move_to_trash


# ── Try to import pygame for audio ────────────────────────────────────────────
try:
    import pygame
    pygame.mixer.init()
    _PYGAME_OK = True
except Exception:
    _PYGAME_OK = False

# ── Try tkinter-based audio fallback ─────────────────────────────────────────
def _play_file_fallback(path: str):
    import sys, subprocess
    if sys.platform == "win32":
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except Exception:
            pass
    elif sys.platform == "darwin":
        subprocess.Popen(["afplay", path])
    else:
        subprocess.Popen(["aplay", path])


def _get_duration_ms(path: str) -> int:
    if not _PYGAME_OK:
        return 0
    try:
        snd = pygame.mixer.Sound(path)
        return int(snd.get_length() * 1000)
    except Exception:
        return 0


def _fmt_time(seconds: int) -> str:
    m, s = divmod(max(0, seconds), 60)
    return f"{m}:{s:02d}"


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
        x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
        x1, y2, x1, y2-r, x1, y1+r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ─────────────────────────────────────────────────────────────────────────────

class MusicPlayer:
    """Backend: state machine for music playback."""

    MODE_LOOP_ALL  = "loop_all"
    MODE_LOOP_ONE  = "loop_one"
    MODE_LOOP_NONE = "loop_none"

    def __init__(self):
        self.playlist: list     = []
        self.current_idx: int   = 0
        self.playing: bool      = False
        self.mode: str          = self.MODE_LOOP_ALL
        self._pos_ms: int       = 0
        # timing helpers for smooth progress
        self._play_start_pos_ms: int   = 0
        self._play_start_time: float   = 0.0
        self._duration_ms: int         = 0
        self._reload_playlist()

    def _reload_playlist(self):
        self.playlist = get_music_files()
        if self.current_idx >= len(self.playlist):
            self.current_idx = 0

    def play(self):
        if not self.playlist:
            return
        path = self.playlist[self.current_idx]
        if _PYGAME_OK:
            try:
                pygame.mixer.music.unload()
            except AttributeError:
                pass
            pygame.mixer.music.load(path)
            pygame.mixer.music.play(start=self._pos_ms / 1000.0)
            self._play_start_pos_ms = self._pos_ms
            self._play_start_time   = time.monotonic()
        else:
            _play_file_fallback(path)
        self.playing = True
        self._pos_ms = 0
        threading.Thread(target=self._load_duration, args=(path,), daemon=True).start()

    def _load_duration(self, path):
        self._duration_ms = _get_duration_ms(path)

    def pause(self):
        if not self.playing:
            return
        if _PYGAME_OK:
            self._pos_ms = self.get_position_ms()
            pygame.mixer.music.pause()
        self.playing = False

    def resume(self):
        if self.playing:
            return
        if _PYGAME_OK:
            pygame.mixer.music.unpause()
            self._play_start_pos_ms = self._pos_ms
            self._play_start_time   = time.monotonic()
        self.playing = True

    def stop(self):
        if _PYGAME_OK:
            pygame.mixer.music.stop()
            try:
                pygame.mixer.music.unload()
            except AttributeError:
                pass
        self.playing = False
        self._pos_ms = 0

    def seek(self, pos_ms: int):
        self._pos_ms = max(0, pos_ms)
        if self.playing:
            self.play()

    def get_position_ms(self) -> int:
        if not _PYGAME_OK or not self.playing:
            return self._pos_ms
        elapsed = (time.monotonic() - self._play_start_time) * 1000
        pos = int(self._play_start_pos_ms + elapsed)
        if self._duration_ms > 0:
            pos = min(pos, self._duration_ms)
        return pos

    def next_track(self, force_play: bool = False):
        if not self.playlist:
            return
        if self.mode == self.MODE_LOOP_ONE and not force_play:
            pass
        else:
            self.current_idx = (self.current_idx + 1) % len(self.playlist)
        self._pos_ms = 0
        if self.playing or force_play:
            self.play()

    def prev_track(self):
        if not self.playlist:
            return
        self.current_idx = (self.current_idx - 1) % len(self.playlist)
        self._pos_ms = 0
        if self.playing:
            self.play()

    def seek_to(self, idx: int):
        self.current_idx = idx % max(len(self.playlist), 1)
        self._pos_ms = 0
        if self.playing:
            self.play()

    def is_finished(self) -> bool:
        if not _PYGAME_OK:
            return False
        return self.playing and not pygame.mixer.music.get_busy()

    def toggle_mode(self):
        cycle = [self.MODE_LOOP_ALL, self.MODE_LOOP_ONE, self.MODE_LOOP_NONE]
        self.mode = cycle[(cycle.index(self.mode) + 1) % len(cycle)]

    def add_file(self, src_path: str) -> bool:
        os.makedirs(MUSIC_DIR, exist_ok=True)
        dest = os.path.join(MUSIC_DIR, os.path.basename(src_path))
        if os.path.abspath(src_path) == os.path.abspath(dest):
            return False
        import shutil
        try:
            shutil.copy2(src_path, dest)
            self._reload_playlist()
            return True
        except Exception as e:
            print(f"[WARN] add_file: {e}")
            return False

    def delete_current(self) -> bool:
        if not self.playlist:
            return False
        path = self.playlist[self.current_idx]
        self.stop()
        ok = move_to_trash(path)
        if ok:
            self._reload_playlist()
            self.current_idx = min(self.current_idx, max(len(self.playlist) - 1, 0))
        return ok

    @property
    def current_title(self) -> str:
        if not self.playlist:
            return "（无音乐）"
        return os.path.splitext(os.path.basename(self.playlist[self.current_idx]))[0]


# ── Background monitor (keeps looping after dialog closes) ───────────────────

class _BackgroundMonitor:
    """
    Daemon thread that polls is_finished() every 500 ms and handles auto-loop
    regardless of whether MusicPlayerDialog is open or not.
    """

    def __init__(self, player: MusicPlayer, root: tk.Misc):
        self.player  = player
        self.root    = root
        self._cb     = None   # UI refresh callback (set when dialog is open)
        self._active = True
        threading.Thread(target=self._run, daemon=True).start()

    def register_callback(self, cb):
        self._cb = cb

    def unregister_callback(self):
        self._cb = None

    def stop(self):
        self._active = False

    def _run(self):
        while self._active:
            time.sleep(0.5)
            p = self.player
            if p.is_finished():
                if p.mode == MusicPlayer.MODE_LOOP_ONE:
                    p.play()
                elif p.mode == MusicPlayer.MODE_LOOP_ALL:
                    p.next_track(force_play=True)
                else:
                    p.stop()
                if self._cb is not None:
                    try:
                        self.root.after(0, self._cb)
                    except Exception:
                        pass


# ── Dialog ────────────────────────────────────────────────────────────────────

class MusicPlayerDialog:
    """Pixel-art styled music player Toplevel window."""

    _BG       = "#2b1a2e"
    _CARD_BG  = "#3d2445"
    _PINK     = "#ffb6d5"
    _WHITE    = "#ffffff"
    _GRAY     = "#9c7aaa"
    _SEL_BG   = "#6b3278"
    _PB_TRACK = "#5a3865"
    _PB_FILL  = "#ffb6d5"
    _PB_THUMB = "#ffffff"

    def __init__(self, parent, player=None, monitor=None):
        self.player  = player or MusicPlayer()
        self._images = {}

        # Resolve real root for after() scheduling
        root = parent
        while isinstance(root, tk.Toplevel):
            root = root.master
        self._root = root

        self._monitor = monitor
        self._owns_monitor = monitor is None
        if self._owns_monitor:
            self._monitor = _BackgroundMonitor(self.player, self._root)

        self.win = tk.Toplevel(parent)
        self.win.title("音乐播放器")
        self.win.configure(bg=self._BG)
        self.win.resizable(False, False)
        set_window_icon(self.win)

        self._pb_dragging = False
        self._pb_drag_frac = 0.0

        self._build_ui()
        self._refresh_list()
        self._monitor.register_callback(self._refresh_controls)
        self._tick()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Icons ─────────────────────────────────────────────────────────────
    def _ico(self, name, size=24):
        if name not in self._images:
            self._images[name] = load_ico_image(name, size)
        return self._images[name]

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        win = self.win
        bg, cbg, pk, wh, gr = self._BG, self._CARD_BG, self._PINK, self._WHITE, self._GRAY

        tk.Label(win, text="♪ Desktop Hachimi 音乐播放器",
                 bg=bg, fg=pk, font=("Microsoft YaHei UI", 12, "bold")).pack(pady=(12, 4))

        # Now-playing card
        card = tk.Frame(win, bg=cbg, bd=0)
        card.pack(fill="x", padx=16, pady=4)

        self._title_var = tk.StringVar(value="──")
        tk.Label(card, textvariable=self._title_var,
                 bg=cbg, fg=wh, font=("Microsoft YaHei UI", 11, "bold"),
                 wraplength=320, justify="center").pack(pady=(10, 2))
        self._idx_var = tk.StringVar(value="0 / 0")
        tk.Label(card, textvariable=self._idx_var,
                 bg=cbg, fg=gr, font=_SZ(8)).pack(pady=(0, 4))

        # Progress bar section
        pb_outer = tk.Frame(card, bg=cbg)
        pb_outer.pack(fill="x", padx=12, pady=(0, 6))

        self._time_var = tk.StringVar(value="0:00 / 0:00")
        tk.Label(pb_outer, textvariable=self._time_var,
                 bg=cbg, fg=gr, font=_SZ(8)).pack(anchor="e", pady=(0, 2))

        self._pb = tk.Canvas(pb_outer, bg=cbg, height=18,
                             highlightthickness=0, cursor="hand2")
        self._pb.pack(fill="x", pady=(0, 4))
        self._pb.bind("<ButtonPress-1>",  self._pb_press)
        self._pb.bind("<B1-Motion>",       self._pb_drag)
        self._pb.bind("<ButtonRelease-1>", self._pb_release)
        self._pb.bind("<Configure>",       lambda _e: self._draw_pb())

        # Controls
        ctrl = tk.Frame(win, bg=bg)
        ctrl.pack(pady=8)
        kw = dict(bg=bg, bd=0, activebackground=cbg, cursor="hand2", relief="flat")

        self._mode_btn = tk.Button(ctrl, **kw, command=self._on_mode)
        self._mode_btn.grid(row=0, column=0, padx=6)

        b = tk.Button(ctrl, **kw, command=self._on_prev)
        _set_img_or_text(b, self._ico("prev.ico"), "⏮", fg=wh)
        b.grid(row=0, column=1, padx=6)

        self._pp_btn = tk.Button(ctrl, **kw, command=self._on_play_pause)
        self._pp_btn.grid(row=0, column=2, padx=6)

        b = tk.Button(ctrl, **kw, command=self._on_next)
        _set_img_or_text(b, self._ico("next.ico"), "⏭", fg=wh)
        b.grid(row=0, column=3, padx=6)

        tk.Frame(ctrl, bg=bg, width=12).grid(row=0, column=4)

        b = tk.Button(ctrl, **kw, command=self._on_add)
        _set_img_or_text(b, self._ico("music_add.ico"), "➕", fg=pk)
        b.grid(row=0, column=5, padx=4)

        b = tk.Button(ctrl, **kw, command=self._on_delete)
        _set_img_or_text(b, self._ico("music_del.ico"), "🗑", fg=pk)
        b.grid(row=0, column=6, padx=4)

        # Playlist
        lf = tk.Frame(win, bg=cbg, bd=0)
        lf.pack(fill="both", expand=True, padx=16, pady=(4, 16))
        sb = tk.Scrollbar(lf, orient="vertical")
        self._listbox = tk.Listbox(
            lf, yscrollcommand=sb.set,
            bg=cbg, fg=wh, selectbackground=self._SEL_BG, selectforeground=wh,
            font=_SZ(10), bd=0, highlightthickness=0, activestyle="none",
            width=42, height=10,
        )
        sb.config(command=self._listbox.yview)
        self._listbox.pack(side="left", fill="both", expand=True, padx=(8,0), pady=8)
        sb.pack(side="right", fill="y", pady=8)
        self._listbox.bind("<Double-Button-1>", self._on_list_dbl)
        self._refresh_controls()

    # ── Progress bar ──────────────────────────────────────────────────────
    def _draw_pb(self, override_frac=None):
        c = self._pb
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1:
            return

        p = self.player
        if override_frac is not None:
            frac = max(0.0, min(1.0, override_frac))
        elif p._duration_ms > 0:
            raw = p.get_position_ms() if p.playing else p._pos_ms
            frac = min(raw / p._duration_ms, 1.0)
        else:
            frac = 0.0

        tr, yr = 6, h // 2
        pad = tr
        usable = w - 2 * pad
        x_fill = pad + int(usable * frac)

        c.delete("all")
        _rounded_rect(c, pad, yr-3, w-pad, yr+3, 3, fill=self._PB_TRACK, outline="")
        if frac > 0:
            _rounded_rect(c, pad, yr-3, x_fill, yr+3, 3, fill=self._PB_FILL, outline="")
        c.create_oval(x_fill-tr, yr-tr, x_fill+tr, yr+tr,
                      fill=self._PB_THUMB, outline=self._PB_FILL, width=2)

        if p._duration_ms > 0:
            pos_s = int((frac * p._duration_ms) / 1000) if self._pb_dragging else int(p.get_position_ms() / 1000)
            self._time_var.set(f"{_fmt_time(pos_s)} / {_fmt_time(p._duration_ms // 1000)}")
        else:
            self._time_var.set("0:00 / 0:00")

    def _x_to_frac(self, x):
        w = self._pb.winfo_width()
        pad = 6
        usable = w - 2 * pad
        return max(0.0, min(1.0, (x - pad) / usable)) if usable > 0 else 0.0

    def _pb_press(self, e):
        self._pb_dragging = True
        self._pb_drag_frac = self._x_to_frac(e.x)
        self._draw_pb(self._pb_drag_frac)

    def _pb_drag(self, e):
        self._pb_drag_frac = self._x_to_frac(e.x)
        self._draw_pb(self._pb_drag_frac)

    def _pb_release(self, e):
        self._pb_dragging = False
        frac = self._x_to_frac(e.x)
        if self.player._duration_ms > 0:
            self.player.seek(int(frac * self.player._duration_ms))
        self._draw_pb()

    # ── Controls ──────────────────────────────────────────────────────────
    def _on_play_pause(self):
        p = self.player
        if not p.playlist:
            return
        if p.playing:
            p.pause()
        else:
            if _PYGAME_OK and pygame.mixer.music.get_busy():
                p.resume()
            else:
                p.play()
        self._refresh_controls()

    def _on_prev(self):
        self.player.prev_track(); self._refresh_controls()

    def _on_next(self):
        self.player.next_track(force_play=self.player.playing); self._refresh_controls()

    def _on_mode(self):
        self.player.toggle_mode(); self._refresh_controls()

    def _on_list_dbl(self, _e):
        sel = self._listbox.curselection()
        if sel:
            self.player.seek_to(sel[0])
            if not self.player.playing:
                self.player.playing = True
            self.player.play()
            self._refresh_controls()

    def _on_add(self):
        files = filedialog.askopenfilenames(
            parent=self.win, title="添加音乐",
            filetypes=[("音频文件", "*.mp3 *.wav *.ogg *.flac *.aac *.m4a *.wma"), ("全部文件", "*.*")]
        )
        added = sum(self.player.add_file(f) for f in files)
        if added:
            self._refresh_list()
            messagebox.showinfo("添加音乐", f"已添加 {added} 首音乐。", parent=self.win)

    def _on_delete(self):
        if not self.player.playlist:
            return
        title = self.player.current_title
        if not messagebox.askyesno("删除音乐", f"将「{title}」移至回收站？", parent=self.win):
            return
        ok = self.player.delete_current()
        if ok:
            self._refresh_list()
        else:
            messagebox.showerror("删除失败", "无法移至回收站，请手动删除。", parent=self.win)

    def _refresh_list(self):
        self.player._reload_playlist()
        lb = self._listbox
        lb.delete(0, "end")
        for path in self.player.playlist:
            lb.insert("end", "  " + os.path.splitext(os.path.basename(path))[0])
        self._refresh_controls()

    def _refresh_controls(self):
        if not self.win.winfo_exists():
            return
        p = self.player
        pp_ico = self._ico("pause.ico" if p.playing else "play.ico")
        _set_img_or_text(self._pp_btn, pp_ico, "⏸" if p.playing else "▶", fg=self._WHITE)

        m = {MusicPlayer.MODE_LOOP_ALL:"loop_all.ico", MusicPlayer.MODE_LOOP_ONE:"loop_one.ico", MusicPlayer.MODE_LOOP_NONE:"loop_none.ico"}
        mt = {MusicPlayer.MODE_LOOP_ALL:"🔁", MusicPlayer.MODE_LOOP_ONE:"🔂", MusicPlayer.MODE_LOOP_NONE:"▶ 1"}
        _set_img_or_text(self._mode_btn, self._ico(m[p.mode]), mt[p.mode], fg=self._PINK)

        self._title_var.set(p.current_title if p.playlist else "（无音乐）")
        total = len(p.playlist)
        cur   = (p.current_idx + 1) if total else 0
        self._idx_var.set(f"{cur} / {total}")

        if total:
            lb = self._listbox
            lb.selection_clear(0, "end")
            lb.selection_set(p.current_idx)
            lb.see(p.current_idx)

        if not self._pb_dragging:
            self._draw_pb()

    def _on_close(self):
        self._monitor.unregister_callback()
        self.win.destroy()

    def _tick(self):
        if not self.win.winfo_exists():
            return
        if not self._pb_dragging:
            self._draw_pb()
        self.win.after(250, self._tick)


# ── Private helpers ───────────────────────────────────────────────────────────

def _SZ(n):
    return ("Microsoft YaHei UI", n)


def _set_img_or_text(btn, image, text, fg="#ffffff"):
    if image:
        btn.config(image=image, text="", width=24, height=24, compound="center")
    else:
        btn.config(image="", text=text, fg=fg, font=("Microsoft YaHei UI", 14))
