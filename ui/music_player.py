"""
ui/music_player.py – MusicPlayerDialog: pixel-art music player window.

Playback modes:  loop_all | loop_one | loop_none
Controls:        prev, play/pause, next, add, delete
Music lives in:  <BASE_DIR>/Music/
"""

import os
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

# ── Try tkinter-based audio fallback (playsound/winsound/afplay/aplay) ────────
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


class MusicPlayer:
    """Backend: state machine for music playback."""

    MODE_LOOP_ALL  = "loop_all"
    MODE_LOOP_ONE  = "loop_one"
    MODE_LOOP_NONE = "loop_none"

    def __init__(self):
        self.playlist: list[str] = []
        self.current_idx: int    = 0
        self.playing: bool       = False
        self.mode: str           = self.MODE_LOOP_ALL
        self._pos_ms: int        = 0     # saved position for pause/resume

        self._reload_playlist()

    def _reload_playlist(self):
        self.playlist = get_music_files()
        if self.current_idx >= len(self.playlist):
            self.current_idx = 0

    # ── Playback ──────────────────────────────────────────────────────────
    def play(self):
        if not self.playlist:
            return
        path = self.playlist[self.current_idx]
        if _PYGAME_OK:
            # Unload any previously loaded track to release its file handle
            try:
                pygame.mixer.music.unload()
            except AttributeError:
                pass
            pygame.mixer.music.load(path)
            pygame.mixer.music.play(start=self._pos_ms / 1000.0)
        else:
            _play_file_fallback(path)
        self.playing = True
        self._pos_ms = 0

    def pause(self):
        if not self.playing:
            return
        if _PYGAME_OK:
            self._pos_ms = int(pygame.mixer.music.get_pos())
            pygame.mixer.music.pause()
        self.playing = False

    def resume(self):
        if self.playing:
            return
        if _PYGAME_OK:
            pygame.mixer.music.unpause()
        self.playing = True

    def stop(self):
        if _PYGAME_OK:
            pygame.mixer.music.stop()
            # Release the file handle so the OS can delete/move the file.
            # pygame.mixer.music.unload() was added in pygame 2.0.0.
            try:
                pygame.mixer.music.unload()
            except AttributeError:
                pass   # pygame < 2.0 – no unload(), handle may stay open briefly
        self.playing = False
        self._pos_ms = 0

    def next_track(self, force_play: bool = False):
        if not self.playlist:
            return
        if self.mode == self.MODE_LOOP_ONE and not force_play:
            pass   # stay on same track
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


# ── Dialog ────────────────────────────────────────────────────────────────────

class MusicPlayerDialog:
    """Pixel-art styled music player Toplevel window."""

    _BG       = "#2b1a2e"   # deep purple-black
    _CARD_BG  = "#3d2445"
    _PINK     = "#ffb6d5"
    _WHITE    = "#ffffff"
    _GRAY     = "#9c7aaa"
    _SEL_BG   = "#6b3278"

    def __init__(self, parent: tk.Tk | tk.Toplevel, player: MusicPlayer | None = None):
        self.player = player or MusicPlayer()
        self._images: dict = {}   # keep PhotoImage refs alive

        self.win = tk.Toplevel(parent)
        self.win.title("🎵 音乐播放器")
        self.win.configure(bg=self._BG)
        self.win.resizable(False, False)
        set_window_icon(self.win)
        self.win.grab_set()

        self._build_ui()
        self._refresh_list()
        self._tick()   # start polling

    # ── Icon helpers ──────────────────────────────────────────────────────
    def _ico(self, name: str, size: int = 24) -> tk.PhotoImage | None:
        if name not in self._images:
            self._images[name] = load_ico_image(name, size)
        return self._images[name]

    # ── UI Construction ───────────────────────────────────────────────────
    def _build_ui(self):
        win = self.win
        bg  = self._BG
        cbg = self._CARD_BG
        pk  = self._PINK
        wh  = self._WHITE
        gr  = self._GRAY

        # ── Title bar ─────────────────────────────────────────────────────
        tk.Label(win, text="♪ Desktop Hachimi 音乐播放器",
                 bg=bg, fg=pk, font=("Microsoft YaHei UI", 12, "bold")).pack(pady=(12, 4))

        # ── Now-playing card ──────────────────────────────────────────────
        card = tk.Frame(win, bg=cbg, bd=0, relief="flat")
        card.pack(fill="x", padx=16, pady=4)

        self._title_var = tk.StringVar(value="──")
        tk.Label(card, textvariable=self._title_var,
                 bg=cbg, fg=wh, font=("Microsoft YaHei UI", 11, "bold"),
                 wraplength=320, justify="center").pack(pady=(10, 2))
        self._idx_var = tk.StringVar(value="0 / 0")
        tk.Label(card, textvariable=self._idx_var,
                 bg=cbg, fg=gr, font=_SZ(8)).pack(pady=(0, 8))

        # ── Control bar ───────────────────────────────────────────────────
        ctrl = tk.Frame(win, bg=bg)
        ctrl.pack(pady=8)

        btn_kw = dict(bg=bg, bd=0, activebackground=self._CARD_BG, cursor="hand2", relief="flat")

        # Mode button
        self._mode_btn = tk.Button(ctrl, **btn_kw, command=self._on_mode)
        self._mode_btn.grid(row=0, column=0, padx=6)

        # Prev
        b_prev = tk.Button(ctrl, **btn_kw, command=self._on_prev)
        _set_img_or_text(b_prev, self._ico("prev.ico"), "⏮", fg=wh)
        b_prev.grid(row=0, column=1, padx=6)

        # Play/Pause
        self._pp_btn = tk.Button(ctrl, **btn_kw, command=self._on_play_pause)
        self._pp_btn.grid(row=0, column=2, padx=6)

        # Next
        b_next = tk.Button(ctrl, **btn_kw, command=self._on_next)
        _set_img_or_text(b_next, self._ico("next.ico"), "⏭", fg=wh)
        b_next.grid(row=0, column=3, padx=6)

        # Add / Delete
        tk.Frame(ctrl, bg=bg, width=12).grid(row=0, column=4)

        b_add = tk.Button(ctrl, **btn_kw, command=self._on_add)
        _set_img_or_text(b_add, self._ico("music_add.ico"), "➕", fg=self._PINK)
        b_add.grid(row=0, column=5, padx=4)

        b_del = tk.Button(ctrl, **btn_kw, command=self._on_delete)
        _set_img_or_text(b_del, self._ico("music_del.ico"), "🗑", fg=self._PINK)
        b_del.grid(row=0, column=6, padx=4)

        # ── Playlist ──────────────────────────────────────────────────────
        list_frame = tk.Frame(win, bg=cbg, bd=0)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(4, 16))

        sb = tk.Scrollbar(list_frame, orient="vertical")
        self._listbox = tk.Listbox(
            list_frame,
            yscrollcommand=sb.set,
            bg=cbg, fg=wh,
            selectbackground=self._SEL_BG, selectforeground=wh,
            font=_SZ(10), bd=0, highlightthickness=0,
            activestyle="none",
            width=42, height=10,
        )
        sb.config(command=self._listbox.yview)
        self._listbox.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="right", fill="y", pady=8)
        self._listbox.bind("<Double-Button-1>", self._on_list_dbl)

        # Initial icon states
        self._refresh_controls()

    # ── Playback callbacks ────────────────────────────────────────────────
    def _on_play_pause(self):
        p = self.player
        if not p.playlist:
            return
        if p.playing:
            p.pause()
        else:
            if pygame.mixer.music.get_busy() if _PYGAME_OK else False:
                p.resume()
            else:
                p.play()
        self._refresh_controls()

    def _on_prev(self):
        self.player.prev_track()
        self._refresh_controls()

    def _on_next(self):
        self.player.next_track(force_play=self.player.playing)
        self._refresh_controls()

    def _on_mode(self):
        self.player.toggle_mode()
        self._refresh_controls()

    def _on_list_dbl(self, _evt):
        sel = self._listbox.curselection()
        if sel:
            self.player.seek_to(sel[0])
            if not self.player.playing:
                self.player.playing = True
            self.player.play()
            self._refresh_controls()

    # ── Add / Delete ──────────────────────────────────────────────────────
    def _on_add(self):
        files = filedialog.askopenfilenames(
            parent=self.win,
            title="添加音乐",
            filetypes=[("音频文件", "*.mp3 *.wav *.ogg *.flac *.aac *.m4a *.wma"), ("全部文件", "*.*")]
        )
        added = 0
        for f in files:
            if self.player.add_file(f):
                added += 1
        if added:
            self._refresh_list()
            messagebox.showinfo("添加音乐", f"已添加 {added} 首音乐。", parent=self.win)

    def _on_delete(self):
        if not self.player.playlist:
            return
        title = self.player.current_title
        if not messagebox.askyesno("删除音乐",
                                   f"将「{title}」移至回收站？",
                                   parent=self.win):
            return
        ok = self.player.delete_current()
        if ok:
            self._refresh_list()
        else:
            messagebox.showerror("删除失败", "无法移至回收站，请手动删除。", parent=self.win)

    # ── Refresh helpers ───────────────────────────────────────────────────
    def _refresh_list(self):
        self.player._reload_playlist()
        lb = self._listbox
        lb.delete(0, "end")
        for path in self.player.playlist:
            lb.insert("end", "  " + os.path.splitext(os.path.basename(path))[0])
        self._refresh_controls()

    def _refresh_controls(self):
        p   = self.player
        btn = self._pp_btn

        # Play/Pause icon
        pp_ico = self._ico("pause.ico" if p.playing else "play.ico")
        _set_img_or_text(btn, pp_ico, "⏸" if p.playing else "▶", fg=self._WHITE)

        # Mode icon
        mode_names = {
            MusicPlayer.MODE_LOOP_ALL:  "loop_all.ico",
            MusicPlayer.MODE_LOOP_ONE:  "loop_one.ico",
            MusicPlayer.MODE_LOOP_NONE: "loop_none.ico",
        }
        mode_texts = {
            MusicPlayer.MODE_LOOP_ALL:  "🔁",
            MusicPlayer.MODE_LOOP_ONE:  "🔂",
            MusicPlayer.MODE_LOOP_NONE: "▶ 1",
        }
        mode_ico = self._ico(mode_names[p.mode])
        _set_img_or_text(self._mode_btn, mode_ico, mode_texts[p.mode], fg=self._PINK)

        # Now-playing labels
        self._title_var.set(p.current_title if p.playlist else "（无音乐）")
        total = len(p.playlist)
        cur   = (p.current_idx + 1) if total else 0
        self._idx_var.set(f"{cur} / {total}")

        # Highlight current track
        if total:
            lb = self._listbox
            lb.selection_clear(0, "end")
            lb.selection_set(p.current_idx)
            lb.see(p.current_idx)

    # ── Polling tick ──────────────────────────────────────────────────────
    def _tick(self):
        if not self.win.winfo_exists():
            return
        p = self.player
        if p.is_finished():
            if p.mode == MusicPlayer.MODE_LOOP_ONE:
                p.play()
            elif p.mode == MusicPlayer.MODE_LOOP_ALL:
                p.next_track(force_play=True)
            else:  # LOOP_NONE
                p.stop()
                p._pos_ms = 0
            self._refresh_controls()
        self.win.after(500, self._tick)


# ── Private helpers ───────────────────────────────────────────────────────────

def _SZ(n: int):
    return ("Microsoft YaHei UI", n)


def _set_img_or_text(btn: tk.Button, image, text: str, fg: str = "#ffffff"):
    if image:
        btn.config(image=image, text="", width=24, height=24, compound="center")
    else:
        btn.config(image="", text=text, fg=fg, font=("Microsoft YaHei UI", 14))
