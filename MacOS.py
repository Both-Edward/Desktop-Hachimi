# MacOS.py
import tkinter as tk

def apply_platform_settings(root, core):
    root.wm_attributes("-transparentcolor", "black")
    root.wm_attributes("-alpha", core.alpha)
    root.wm_attributes("-topmost", True)
    # macOS 不支持 -disabled，穿透效果有限
    # 可考虑未来用 pyobjc 实现真正穿透