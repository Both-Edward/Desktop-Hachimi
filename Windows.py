# Windows.py
import tkinter as tk

def apply_platform_settings(root, core):
    root.wm_attributes("-transparentcolor", "black")
    root.wm_attributes("-alpha", core.alpha)
    root.wm_attributes("-topmost", True)
    if core.mouse_through:
        # 禁用窗口以实现“穿透”（无法点击）
        root.wm_attributes("-disabled", True)
    else:
        root.wm_attributes("-disabled", False)