# core.py
import os
import random
import tkinter as tk
from PIL import Image, ImageTk
from glob import glob
from constants import PET_ROOT, DEFAULT_PET

class PetCore:
    def __init__(self, root):
        self.root = root
        self.pet_name = DEFAULT_PET
        self.scale = 1.0
        self.alpha = 1.0
        self.mouse_through = False
        self.is_moving = True
        self.follow_mouse = False
        self.dragging = False
        self.prev_state = 'idle'  # 'idle' or 'move'

        self.idle_paths = []
        self.move_paths = []
        self.drag_paths = []

        self.current_frames = []
        self.frame_index = 0
        self.after_id = None

        self.load_pet(self.pet_name)
        self.setup_label()
        self.play_by_state('idle')

    def setup_label(self):
        self.label = tk.Label(self.root, bg='black', bd=0)
        self.label.pack()

        self.label.bind("<Button-1>", self.on_click)
        self.label.bind("<B1-Motion>", self.on_drag)
        self.label.bind("<ButtonRelease-1>", self.on_release)

    def on_click(self, event):
        self.start_x = event.x
        self.start_y = event.y

    def on_drag(self, event):
        if not self.dragging:
            self.dragging = True
            self.prev_state = 'move' if self.is_moving else 'idle'
            self.is_moving = False
            self.follow_mouse = False
            self.play_drag()

        x = self.root.winfo_x() + event.x - self.start_x
        y = self.root.winfo_y() + event.y - self.start_y
        self.root.geometry(f"+{x}+{y}")

    def on_release(self, _):
        if self.dragging:
            self.dragging = False
            self.is_moving = (self.prev_state == 'move')
            self.play_by_state(self.prev_state)

    def load_pet(self, name):
        pet_dir = os.path.join(PET_ROOT, name)
        if not os.path.isdir(pet_dir):
            raise FileNotFoundError(f"Pet folder '{pet_dir}' not found!")

        self.pet_name = name
        self.idle_paths = sorted(glob(os.path.join(pet_dir, "idle*.gif")))
        self.move_paths = sorted(glob(os.path.join(pet_dir, "move*.gif")))
        self.drag_paths = sorted(glob(os.path.join(pet_dir, "drag*.gif")))

        if not self.idle_paths:
            raise FileNotFoundError(f"No idle*.gif in {pet_dir}")

    def get_random_path(self, paths):
        return random.choice(paths) if paths else self.idle_paths[0]

    def load_gif_frames(self, path):
        frames = []
        img = Image.open(path)
        try:
            while True:
                frame = img.copy().convert("RGBA")
                # 缩放
                w, h = frame.size
                new_w = int(w * self.scale)
                new_h = int(h * self.scale)
                if new_w > 0 and new_h > 0:
                    frame = frame.resize((new_w, new_h), Image.LANCZOS)
                frames.append(ImageTk.PhotoImage(frame))
                img.seek(len(frames))
        except EOFError:
            pass
        return frames

    def play_gif(self, path, delay=100):
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.current_frames = self.load_gif_frames(path)
        self.frame_index = 0
        self._animate(delay)

    def _animate(self, delay):
        if not self.current_frames:
            return
        self.label.config(image=self.current_frames[self.frame_index])
        self.frame_index = (self.frame_index + 1) % len(self.current_frames)
        self.after_id = self.root.after(delay, lambda: self._animate(delay))

    def play_idle(self):
        path = self.get_random_path(self.idle_paths)
        self.play_gif(path, delay=100)

    def play_move(self):
        path = self.get_random_path(self.move_paths) if self.move_paths else self.idle_paths[0]
        self.play_gif(path, delay=80)

    def play_drag(self):
        path = self.get_random_path(self.drag_paths) if self.drag_paths else self.idle_paths[0]
        self.play_gif(path, delay=100)

    def play_by_state(self, state):
        if state == 'idle':
            self.play_idle()
        elif state == 'move':
            self.play_move()

    def update_position(self):
        if self.dragging:
            pass
        elif self.follow_mouse:
            mx, my = self.root.winfo_pointerx(), self.root.winfo_pointery()
            cx, cy = self.root.winfo_x(), self.root.winfo_y()
            nx = cx + int((mx - cx - 50) * 0.08)
            ny = cy + int((my - cy - 50) * 0.08)
            self.root.geometry(f"+{nx}+{ny}")
        elif self.is_moving:
            sw = self.root.winfo_vrootwidth()   # 虚拟屏幕宽（多显示器）
            sh = self.root.winfo_vrootheight()  # 虚拟屏幕高
            x = random.randint(0, max(0, sw - 200))
            y = random.randint(0, max(0, sh - 200))
            self.root.geometry(f"+{x}+{y}")
            self.play_move()
            self.root.after(2500, self.play_idle)

        self.root.after(100, self.update_position)

    # === 外部接口 ===
    def set_scale(self, scale):
        self.scale = float(scale)
        self.play_by_state(self.prev_state if not self.dragging else 'drag')

    def set_alpha(self, alpha):
        self.alpha = float(alpha)

    def toggle_mouse_through(self, enable):
        self.mouse_through = bool(enable)

    def switch_pet(self, name):
        self.load_pet(name)
        self.play_by_state('idle')

    def toggle_movement(self, enable):
        self.is_moving = bool(enable)
        if not enable:
            self.play_idle()

    def toggle_follow_mouse(self, enable):
        self.follow_mouse = bool(enable)
        if enable:
            self.is_moving = False