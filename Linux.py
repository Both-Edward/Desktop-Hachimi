# Linux.py
import tkinter as tk

def apply_platform_settings(root, core):
    root.wm_attributes("-alpha", core.alpha)
    root.wm_attributes("-topmost", True)
    # Linux 下透明色依赖合成器（如 Picom），不设 transparentcolor