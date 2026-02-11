# main.py
import os
import sys
import tkinter as tk
from tkinter import messagebox
from constants import ICON_PATH, VERSION, APP_NAME, AUTHOR, AUTHOR_EMAIL
from core import PetCore

# 自动导入平台模块
if sys.platform == "win32":
    from Windows import apply_platform_settings
elif sys.platform == "darwin":
    from MacOS import apply_platform_settings
else:
    from Linux import apply_platform_settings

def create_context_menu(root, core):
    menu = tk.Menu(root, tearoff=0)

    # 缩放
    scale_menu = tk.Menu(menu, tearoff=0)
    for i in range(1, 21):
        s = round(i * 0.1, 1)
        scale_menu.add_command(label=str(s), command=lambda v=s: core.set_scale(v))
    menu.add_cascade(label="缩放", menu=scale_menu)

    # 透明度
    alpha_menu = tk.Menu(menu, tearoff=0)
    for i in range(1, 11):
        a = round(i * 0.1, 1)
        alpha_menu.add_command(label=str(a), command=lambda v=a: [
            core.set_alpha(v),
            apply_platform_settings(root, core)
        ])
    menu.add_cascade(label="透明度", menu=alpha_menu)

    # 鼠标穿透
    menu.add_checkbutton(
        label="鼠标穿透",
        variable=tk.BooleanVar(value=core.mouse_through),
        command=lambda: [
            core.toggle_mouse_through(not core.mouse_through),
            apply_platform_settings(root, core)
        ]
    )

    # 切换桌宠
    pet_menu = tk.Menu(menu, tearoff=0)
    pets = [d for d in os.listdir("Pets") if os.path.isdir(os.path.join("Pets", d))]
    for pet in pets:
        pet_menu.add_command(label=pet, command=lambda p=pet: core.switch_pet(p))
    menu.add_cascade(label="切换桌宠", menu=pet_menu)

    # 运动控制
    menu.add_checkbutton(
        label="开始运动",
        variable=tk.BooleanVar(value=core.is_moving),
        command=lambda: core.toggle_movement(not core.is_moving)
    )

    # 鼠标跟随
    menu.add_checkbutton(
        label="鼠标跟随",
        variable=tk.BooleanVar(value=core.follow_mouse),
        command=lambda: core.toggle_follow_mouse(not core.follow_mouse)
    )

    # 关于
    def show_about():
        msg = f"{APP_NAME} v{VERSION}\n作者: {AUTHOR}\n邮箱: {AUTHOR_EMAIL}"
        messagebox.showinfo("关于 Desktop Hachimi", msg)
    menu.add_command(label="关于", command=show_about)

    def show(e):
        menu.post(e.x_root, e.y_root)
    root.bind("<Button-3>", show)

def main():
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口

    # 设置应用图标（仅 Windows 支持 .ico）
    if os.path.exists(ICON_PATH):
        try:
            root.iconbitmap(ICON_PATH)
        except:
            pass

    core = PetCore(root)
    apply_platform_settings(root, core)
    create_context_menu(root, core)

    # 启动位置居中
    root.deiconify()
    root.geometry("+400+300")
    root.update()

    # 开始行为循环
    root.after(100, core.update_position)

    root.mainloop()

if __name__ == "__main__":
    main()