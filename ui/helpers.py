"""
ui/helpers.py – Shared UI utilities (icon loading, screen helpers).
"""

import math
import tkinter as tk
from PIL import Image, ImageTk

from core.config import APP_ICO, ICO_DIR
import os


def set_window_icon(win: tk.Toplevel | tk.Tk):
    if os.path.exists(APP_ICO):
        try:
            win.iconbitmap(APP_ICO)
        except Exception:
            pass


def load_ico_image(name: str, size: int = 24) -> ImageTk.PhotoImage | None:
    """Load an .ico from ico/ and return a PhotoImage scaled to *size*."""
    path = os.path.join(ICO_DIR, name)
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA").resize((size, size), Image.NEAREST)
        return ImageTk.PhotoImage(img)
    except Exception as e:
        print(f"[WARN] load_ico_image({name}): {e}")
        return None


def get_screen_for_point(px, py, monitors):
    if not monitors:
        return None
    for mx, my, mw, mh in monitors:
        if mx <= px < mx + mw and my <= py < my + mh:
            return (mx, my, mw, mh)
    best, best_d = monitors[0], float("inf")
    for m in monitors:
        mx, my, mw, mh = m
        cx, cy = mx + mw / 2, my + mh / 2
        d = math.hypot(px - cx, py - cy)
        if d < best_d:
            best, best_d = m, d
    return best
