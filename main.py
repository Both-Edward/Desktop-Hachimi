import tkinter as tk
from PIL import Image, ImageTk
import itertools
import random
import os
import json
import sys
import platform
from typing import List, Tuple, Dict, Optional
import time

# 软件信息
VERSION = "1.0.0"
APP_NAME = "Desktop Hachimi"
AUTHOR = "Edward"
AUTHOR_EMAIL = "2651671851@qq.com"

# 配置常量
PET_DIR = "/Pets"
ICON_DIR = "/ico"
DEFAULT_PET = "Ameath"
SCALE_OPTIONS = [round(x * 0.1, 1) for x in range(1, 21)]  # 0.1 to 2.0
TRANSPARENCY_OPTIONS = [round(x * 0.1, 1) for x in range(1, 11)]  # 0.1 to 1.0
DEFAULT_SCALE_INDEX = 9  # 1.0x
DEFAULT_TRANSPARENCY_INDEX = 9  # 1.0

# 运动配置
SPEED_X = 2
SPEED_Y = 1.5
MOVE_INTERVAL = 50  # ms
JITTER_INTERVAL = 5
JITTER = 0.1
FOLLOW_DISTANCE = 100
FOLLOW_SPEED = 1.0

# 状态定义
STATE_MOVING = "moving"
STATE_IDLE = "idle"
STATE_DRAGGING = "dragging"
STATE_PAUSED = "paused"

# 配置文件路径
CONFIG_FILE = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~/.config")), "desktop_hachimi_config.json"
)


def load_config() -> Dict:
    """加载配置"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {
            "scale_index": DEFAULT_SCALE_INDEX,
            "transparency_index": DEFAULT_TRANSPARENCY_INDEX,
            "current_pet": DEFAULT_PET,
            "click_through": True,
            "mouse_follow": False,
            "paused": False,
        }


def save_config(config: Dict):
    """保存配置"""
    config_dir = os.path.dirname(CONFIG_FILE)
    if config_dir and not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_available_pets() -> List[str]:
    """获取可用的宠物列表"""
    pets_dir = PET_DIR
    if not os.path.exists(pets_dir):
        os.makedirs(pets_dir, exist_ok=True)
        return []
    return [d for d in os.listdir(pets_dir) if os.path.isdir(os.path.join(pets_dir, d))]


def load_gif_frames(gif_path: str, scale: float = 1.0) -> Tuple[List[ImageTk.PhotoImage], List[int], List]:
    """加载并缩放GIF，返回(frames, delays, pil_frames)"""
    photoimage_frames = []
    pil_frames = []
    delays = []
    
    if not os.path.exists(gif_path):
        # 如果文件不存在，创建一个简单的占位符
        img = Image.new('RGBA', (100, 100), color='magenta')
        photoimage_frames.append(ImageTk.PhotoImage(img))
        pil_frames.append(img)
        delays.append(100)
        return photoimage_frames, delays, pil_frames
    
    try:
        gif = Image.open(gif_path)
        frame = None
        for i in itertools.count():
            try:
                gif.seek(i)
                frame = gif.convert("RGBA")
                w, h = frame.size
                new_w, new_h = int(w * scale), int(h * scale)
                # 确保缩放后尺寸有效
                if new_w <= 0 or new_h <= 0:
                    new_w = max(1, new_w)
                    new_h = max(1, new_h)
                resized = frame.resize((new_w, new_h), Image.Resampling.LANCZOS)
                photoimage_frames.append(ImageTk.PhotoImage(resized))
                pil_frames.append(resized)
                delays.append(gif.info.get("duration", 80))
            except EOFError:
                break
        # 确保至少有一帧
        if not photoimage_frames and frame is not None:
            photoimage_frames.append(
                ImageTk.PhotoImage(frame.resize((100, 100), Image.Resampling.LANCZOS))
            )
            pil_frames.append(frame.resize((100, 100), Image.Resampling.LANCZOS))
            delays.append(80)
    except Exception as e:
        print(f"加载GIF失败: {e}")
        # 返回占位符
        img = Image.new('RGBA', (100, 100), color='magenta')
        photoimage_frames.append(ImageTk.PhotoImage(img))
        pil_frames.append(img)
        delays.append(100)
    
    return photoimage_frames, delays, pil_frames


def flip_frames(pil_frames):
    """水平翻转所有PIL Image帧，返回PhotoImage"""
    from PIL import Image
    flipped = []
    for img in pil_frames:
        flipped_img = ImageTk.PhotoImage(img.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
        flipped.append(flipped_img)
    return flipped


class DesktopPetEngine:
    """桌面宠物核心引擎"""
    
    def __init__(self, pet_name: str = DEFAULT_PET):
        self.pet_name = pet_name
        self.scale = SCALE_OPTIONS[DEFAULT_SCALE_INDEX]
        self.transparency = TRANSPARENCY_OPTIONS[DEFAULT_TRANSPARENCY_INDEX]
        self.click_through = True
        self.mouse_follow = False
        self.paused = False
        self.current_state = STATE_MOVING
        
        # 加载配置
        config = load_config()
        self.scale = SCALE_OPTIONS[config.get("scale_index", DEFAULT_SCALE_INDEX)]
        self.transparency = TRANSPARENCY_OPTIONS[config.get("transparency_index", DEFAULT_TRANSPARENCY_INDEX)]
        self.pet_name = config.get("current_pet", DEFAULT_PET)
        self.click_through = config.get("click_through", True)
        self.mouse_follow = config.get("mouse_follow", False)
        
        # 动画帧
        self.move_frames = []
        self.move_frames_left = []
        self.move_delays = []
        self.idle_gifs = []  # [(frames, delays), ...]
        self.drag_frames = []
        self.drag_delays = []
        
        self.current_frames = []
        self.current_delays = []
        self.frame_index = 0
        
        # 位置和速度
        self.x = 100
        self.y = 100
        self.vx = SPEED_X
        self.vy = SPEED_Y
        self.w = 100
        self.h = 100
        
        # 拖拽状态
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.pre_drag_state = None
        self.pre_drag_frames = None
        self.pre_drag_delays = None
        
        # 运动目标
        self.target_x = 0
        self.target_y = 0
        self.last_mouse_x = 0
        self.last_mouse_y = 0
        
        # 初始化
        self.load_pet_assets()
        self.set_initial_position()
        
    def load_pet_assets(self):
        """加载宠物资源"""
        pet_path = os.path.join(PET_DIR, self.pet_name)
        
        # 加载移动动画
        move_path = os.path.join(pet_path, "move.gif")
        self.move_frames, self.move_delays, self.move_pil_frames = load_gif_frames(move_path, self.scale)
        self.move_frames_left = flip_frames(self.move_pil_frames)
        
        # 加载空闲动画
        self.idle_gifs = []
        idle_idx = 1
        while True:
            idle_path = os.path.join(pet_path, f"idle{idle_idx}.gif" if idle_idx > 1 else "idle.gif")
            if not os.path.exists(idle_path):
                break
            frames, delays, _ = load_gif_frames(idle_path, self.scale)
            if frames:  # 确保有帧
                self.idle_gifs.append((frames, delays))
            idle_idx += 1
        
        # 如果没有idle动画，使用移动动画作为备选
        if not self.idle_gifs:
            self.idle_gifs.append((self.move_frames, self.move_delays))
        
        # 加载拖拽动画
        drag_path = os.path.join(pet_path, "drag.gif")
        self.drag_frames, self.drag_delays, _ = load_gif_frames(drag_path, self.scale)
        
        # 设置当前帧
        if not self.paused:
            self.current_frames = self.move_frames
            self.current_delays = self.move_delays
        else:
            self.current_frames, self.current_delays = random.choice(self.idle_gifs)
        
        # 更新尺寸
        if self.move_frames:
            self.w = self.move_frames[0].width()
            self.h = self.move_frames[0].height()
    
    def set_initial_position(self):
        """设置初始位置"""
        # 尝试获取屏幕尺寸
        try:
            root_temp = tk.Tk()
            root_temp.withdraw()
            screen_w = root_temp.winfo_screenwidth()
            screen_h = root_temp.winfo_screenheight()
            root_temp.destroy()
            
            self.x = random.randint(100, screen_w - self.w - 100)
            self.y = random.randint(100, screen_h - self.h - 100)
        except:
            # 默认位置
            self.x = 100
            self.y = 100
    
    def update_scale(self, scale_index: int):
        """更新缩放"""
        self.scale = SCALE_OPTIONS[scale_index]
        self.load_pet_assets()
        
        # 保存配置
        config = load_config()
        config["scale_index"] = scale_index
        save_config(config)
    
    def update_transparency(self, transparency_index: int):
        """更新透明度"""
        self.transparency = TRANSPARENCY_OPTIONS[transparency_index]
        
        # 保存配置
        config = load_config()
        config["transparency_index"] = transparency_index
        save_config(config)
    
    def toggle_click_through(self):
        """切换鼠标穿透"""
        self.click_through = not self.click_through
        
        # 保存配置
        config = load_config()
        config["click_through"] = self.click_through
        save_config(config)
    
    def toggle_mouse_follow(self):
        """切换鼠标跟随"""
        self.mouse_follow = not self.mouse_follow
        
        # 保存配置
        config = load_config()
        config["mouse_follow"] = self.mouse_follow
        save_config(config)
    
    def change_pet(self, pet_name: str):
        """更换宠物"""
        if pet_name in get_available_pets():
            self.pet_name = pet_name
            self.load_pet_assets()
            
            # 保存配置
            config = load_config()
            config["current_pet"] = pet_name
            save_config(config)
    
    def toggle_pause(self):
        """切换暂停/开始"""
        self.paused = not self.paused
        
        if self.paused:
            self.current_state = STATE_PAUSED
            # 切换到空闲动画
            frames, delays = random.choice(self.idle_gifs)
            self.current_frames = frames
            self.current_delays = delays
        else:
            self.current_state = STATE_MOVING
            # 切换到移动动画
            self.current_frames = self.move_frames if self.vx > 0 else self.move_frames_left
            self.current_delays = self.move_delays
        
        # 保存配置
        config = load_config()
        config["paused"] = self.paused
        save_config(config)
    
    def start_drag(self, event_x: int, event_y: int):
        """开始拖拽"""
        if self.click_through:
            return
        self.dragging = True
        self.drag_start_x = event_x
        self.drag_start_y = event_y
        
        # 保存当前状态
        self.pre_drag_state = self.current_state
        self.pre_drag_frames = self.current_frames
        self.pre_drag_delays = self.current_delays
        
        # 切换到拖拽动画
        self.current_state = STATE_DRAGGING
        self.current_frames = self.drag_frames
        self.current_delays = self.drag_delays
        self.frame_index = 0
    
    def update_drag(self, root_x: int, root_y: int):
        """更新拖拽位置"""
        if self.dragging:
            self.x = root_x - self.drag_start_x
            self.y = root_y - self.drag_start_y
    
    def stop_drag(self):
        """停止拖拽"""
        if self.dragging:
            self.dragging = False
            
            # 恢复之前的状态
            if self.pre_drag_state == STATE_PAUSED:
                self.toggle_pause()  # 如果之前是暂停状态，需要再次暂停
            else:
                self.current_state = self.pre_drag_state
                self.current_frames = self.pre_drag_frames or self.move_frames
                self.current_delays = self.pre_drag_delays or self.move_delays
                self.frame_index = 0
            
            # 重置拖拽状态
            self.pre_drag_state = None
            self.pre_drag_frames = None
            self.pre_drag_delays = None
    
    def get_current_frame(self) -> ImageTk.PhotoImage:
        """获取当前帧"""
        if not self.current_frames:
            # 返回占位符
            img = Image.new('RGBA', (100, 100), color='magenta')
            return ImageTk.PhotoImage(img)
        return self.current_frames[self.frame_index]
    
    def next_frame(self):
        """切换到下一帧"""
        if self.current_frames:
            self.frame_index = (self.frame_index + 1) % len(self.current_frames)
    
    def update_position(self, mouse_x: int = None, mouse_y: int = None):
        """更新位置（仅当不在拖拽状态时）"""
        if self.dragging or self.paused:
            return
        
        # 更新鼠标位置（如果提供了的话）
        if mouse_x is not None and mouse_y is not None:
            self.last_mouse_x = mouse_x
            self.last_mouse_y = mouse_y
        
        # 根据模式更新位置
        if self.mouse_follow and mouse_x is not None and mouse_y is not None:
            # 鼠标跟随模式
            dx = mouse_x - FOLLOW_DISTANCE - self.x
            dy = mouse_y - FOLLOW_DISTANCE - self.y
            dist = max(1, (dx*dx + dy*dy)**0.5)
            
            # 限制速度
            speed_factor = min(FOLLOW_SPEED, dist / 10)  # 随距离调整速度
            self.vx = (dx / dist) * speed_factor
            self.vy = (dy / dist) * speed_factor
            
            # 添加随机抖动
            if random.random() < 0.3:  # 30% 概率添加抖动
                self.vx += random.uniform(-JITTER, JITTER)
                self.vy += random.uniform(-JITTER, JITTER)
        else:
            # 自由移动模式 - 随机游走
            # 添加随机抖动
            if random.random() < 0.1:  # 10% 概率改变方向
                self.vx = random.choice([-SPEED_X, SPEED_X]) + random.uniform(-JITTER, JITTER)
                self.vy = random.choice([-SPEED_Y, SPEED_Y]) + random.uniform(-JITTER, JITTER)
            else:
                self.vx += random.uniform(-JITTER, JITTER)
                self.vy += random.uniform(-JITTER, JITTER)
        
        # 应用移动
        self.x += self.vx
        self.y += self.vy
        
        # 检查边界并反弹
        try:
            root_temp = tk.Tk()
            root_temp.withdraw()
            screen_w = root_temp.winfo_screenwidth()
            screen_h = root_temp.winfo_screenheight()
            root_temp.destroy()
            
            # 左右边界
            if self.x <= 0:
                self.x = 0
                self.vx = abs(self.vx)  # 向右反弹
                # 切换到右侧动画
                self.current_frames = self.move_frames
                self.current_delays = self.move_delays
                self.frame_index = 0
            elif self.x + self.w >= screen_w:
                self.x = screen_w - self.w
                self.vx = -abs(self.vx)  # 向左反弹
                # 切换到左侧动画
                self.current_frames = self.move_frames_left
                self.current_delays = self.move_delays
                self.frame_index = 0
            
            # 上下边界
            if self.y <= 0:
                self.y = 0
                self.vy = abs(self.vy)  # 向下反弹
            elif self.y + self.h >= screen_h:
                self.y = screen_h - self.h
                self.vy = -abs(self.vy)  # 向上反弹
        except:
            # 如果无法获取屏幕尺寸，使用默认值
            if self.x <= 0 or self.x >= 800 - self.w:
                self.vx = -self.vx
            if self.y <= 0 or self.y >= 600 - self.h:
                self.vy = -self.vy
    
    def get_position(self) -> Tuple[float, float]:
        """获取当前位置"""
        return self.x, self.y
    
    def get_size(self) -> Tuple[int, int]:
        """获取尺寸"""
        return self.w, self.h


# Windows特定实现
if platform.system() == "Windows":
    import ctypes
    from ctypes import wintypes
    import winreg
    from pystray import MenuItem
    
    # Windows API 常量
    HWND_TOPMOST = -1
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    
    class WindowsDesktopPet:
        def __init__(self):
            # 启用 Windows DPI 感知
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except:
                    pass
            
            self.root = tk.Tk()
            self.engine = DesktopPetEngine()
            
            # 设置窗口属性
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.config(bg="magenta")
            self.root.attributes("-transparentcolor", "magenta")
            self.root.attributes("-alpha", self.engine.transparency)
            
            # 创建标签显示动画
            self.label = tk.Label(self.root, bg="magenta", bd=0)
            self.label.pack()
            
            # 绑定拖拽事件
            self.label.bind("<ButtonPress-1>", self.start_drag)
            self.label.bind("<B1-Motion>", self.do_drag)
            self.label.bind("<ButtonRelease-1>", self.stop_drag)
            
            # 设置初始位置和大小
            w, h = self.engine.get_size()
            x, y = self.engine.get_position()
            self.root.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
            
            # 设置鼠标穿透
            self.set_click_through(self.engine.click_through)
            
            # 创建系统托盘
            self.create_tray_icon()
            
            # 启动动画和移动循环
            self.animate()
            self.move_loop()
        
        def set_click_through(self, enabled: bool):
            """设置鼠标穿透"""
            try:
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                
                if enabled:
                    ctypes.windll.user32.SetWindowLongW(
                        hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                    )
                else:
                    ctypes.windll.user32.SetWindowLongW(
                        hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT
                    )
            except Exception as e:
                print(f"设置鼠标穿透失败: {e}")
        
        def start_drag(self, event):
            self.engine.start_drag(event.x, event.y)
        
        def do_drag(self, event):
            self.engine.update_drag(event.x_root, event.y_root)
            w, h = self.engine.get_size()
            self.root.geometry(f"{w}x{h}+{int(self.engine.x)}+{int(self.engine.y)}")
        
        def stop_drag(self, event=None):
            self.engine.stop_drag()
        
        def animate(self):
            """动画循环"""
            frame = self.engine.get_current_frame()
            self.label.config(image=frame)
            self.engine.next_frame()
            
            delay = self.engine.current_delays[self.engine.frame_index] if self.engine.current_delays else 100
            self.root.after(delay, self.animate)
        
        def move_loop(self):
            """移动循环"""
            # 获取鼠标位置
            try:
                mouse_x = self.root.winfo_pointerx()
                mouse_y = self.root.winfo_pointery()
            except:
                mouse_x, mouse_y = None, None
            
            self.engine.update_position(mouse_x, mouse_y)
            
            # 更新窗口位置
            w, h = self.engine.get_size()
            x, y = self.engine.get_position()
            self.root.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
            
            # 确保窗口始终置顶
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW
            )
            
            self.root.after(MOVE_INTERVAL, self.move_loop)
        
        def create_tray_icon(self):
            """创建系统托盘图标"""
            try:
                import pystray
                from PIL import Image as PILImage
                
                # 尝试加载图标
                icon_path = os.path.join(ICON_DIR, "Desktop Hachimi.ico")
                if os.path.exists(icon_path):
                    icon_img = PILImage.open(icon_path).convert("RGBA").resize((64, 64))
                else:
                    # 创建默认图标
                    icon_img = PILImage.new("RGBA", (64, 64), color="blue")
                
                # 创建菜单
                menu = self.create_menu()
                self.icon = pystray.Icon("desktop_hachimi", icon_img, "Desktop Hachimi", menu)
                
                # 在新线程中运行托盘
                import threading
                tray_thread = threading.Thread(target=self.icon.run, daemon=True)
                tray_thread.start()
                
            except ImportError:
                print("pystray未安装，无法创建系统托盘")
        
        def create_menu(self):
            """创建托盘菜单"""
            import pystray
            
            # 缩放菜单
            scale_menu = pystray.Menu(*[
                pystray.MenuItem(
                    f"{scale}x",
                    lambda item, idx=i: self.on_scale_change(idx),
                    checked=lambda item, idx=i: self.engine.scale == SCALE_OPTIONS[idx]
                ) for i, scale in enumerate(SCALE_OPTIONS)
            ])
            
            # 透明度菜单
            transparency_menu = pystray.Menu(*[
                pystray.MenuItem(
                    f"{int(alpha * 100)}%",
                    lambda item, idx=i: self.on_transparency_change(idx),
                    checked=lambda item, idx=i: self.engine.transparency == TRANSPARENCY_OPTIONS[idx]
                ) for i, alpha in enumerate(TRANSPARENCY_OPTIONS)
            ])
            
            # 宠物菜单
            available_pets = get_available_pets()
            pet_menu = pystray.Menu(*[
                pystray.MenuItem(
                    pet,
                    lambda item, name=pet: self.on_pet_change(name),
                    checked=lambda item, name=pet: self.engine.pet_name == name
                ) for pet in available_pets
            ])
            
            # 主菜单
            menu = pystray.Menu(
                pystray.MenuItem("缩放", scale_menu),
                pystray.MenuItem("透明度", transparency_menu),
                pystray.MenuItem("切换宠物", pet_menu),
                pystray.MenuItem(
                    "鼠标穿透",
                    lambda item: self.on_toggle_click_through(),
                    checked=lambda item: self.engine.click_through
                ),
                pystray.MenuItem(
                    "鼠标跟随",
                    lambda item: self.on_toggle_mouse_follow(),
                    checked=lambda item: self.engine.mouse_follow
                ),
                pystray.MenuItem(
                    "暂停/开始",
                    lambda item: self.on_toggle_pause(),
                    checked=lambda item: self.engine.paused
                ),
                pystray.MenuItem("关于", lambda item: self.show_about()),
                pystray.MenuItem("退出", lambda item: self.quit_app())
            )
            
            return menu
        
        def on_scale_change(self, index):
            self.engine.update_scale(index)
            # 重新加载资源
            self.engine.load_pet_assets()
            # 重新设置窗口大小
            w, h = self.engine.get_size()
            self.root.geometry(f"{w}x{h}+{int(self.engine.x)}+{int(self.engine.y)}")
        
        def on_transparency_change(self, index):
            self.engine.update_transparency(index)
            self.root.attributes("-alpha", self.engine.transparency)
        
        def on_pet_change(self, pet_name):
            self.engine.change_pet(pet_name)
            # 重新加载资源
            self.engine.load_pet_assets()
            # 重新设置窗口大小
            w, h = self.engine.get_size()
            self.root.geometry(f"{w}x{h}+{int(self.engine.x)}+{int(self.engine.y)}")
        
        def on_toggle_click_through(self):
            self.engine.toggle_click_through()
            self.set_click_through(self.engine.click_through)
        
        def on_toggle_mouse_follow(self):
            self.engine.toggle_mouse_follow()
        
        def on_toggle_pause(self):
            self.engine.toggle_pause()
        
        def show_about(self):
            """显示关于窗口"""
            about_window = tk.Toplevel(self.root)
            about_window.title("关于 Desktop Hachimi")
            about_window.geometry("400x300")
            about_window.resizable(False, False)
            about_window.attributes("-topmost", True)
            
            # 居中显示
            about_window.update_idletasks()
            screen_w = about_window.winfo_screenwidth()
            screen_h = about_window.winfo_screenheight()
            x = (screen_w - 400) // 2
            y = (screen_h - 300) // 2
            about_window.geometry(f"+{x}+{y}")
            
            tk.Label(about_window, text=APP_NAME, font=("Arial", 16, "bold")).pack(pady=10)
            tk.Label(about_window, text=f"版本: {VERSION}").pack()
            tk.Label(about_window, text=f"作者: {AUTHOR}").pack()
            tk.Label(about_window, text=f"邮箱: {AUTHOR_EMAIL}").pack(pady=20)
            
            tk.Button(about_window, text="确定", command=about_window.destroy).pack(pady=10)
        
        def quit_app(self):
            """退出应用"""
            if hasattr(self, 'icon'):
                self.icon.stop()
            self.root.quit()
        
        def run(self):
            """运行应用"""
            self.root.mainloop()


if __name__ == "__main__":
    if platform.system() == "Windows":
        app = WindowsDesktopPet()
        app.run()
    else:
        print("此平台暂未支持，请等待后续更新")
