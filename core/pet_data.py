"""
core/pet_data.py – PetData: loads animation assets and weights for one pet.
Pure data model; no UI dependency.
"""

import os
import json
import random

from core.config import PETS_DIR
from core.gif_loader import load_gif_frames


class PetData:
    """Represents one pet's animation assets and weights."""

    def __init__(self, name: str, scale: float = 1.0):
        self.name  = name
        self.scale = scale
        self.dir   = os.path.join(PETS_DIR, name)
        self._load()

    def _load(self):
        s = self.scale
        d = self.dir
        n = self.name

        dynamic_path = os.path.join(d, f"{n}.gif")
        self.dynamic_frames = load_gif_frames(dynamic_path, s) if os.path.exists(dynamic_path) else []
        self.dynamic_weight = self._read_weight("dynamic_weight", 3)

        self.idle_variants = self._load_variants("idle", s)
        self.idle_weights  = self._read_multi_weight("idle_weight", len(self.idle_variants), 2)

        self.move_variants  = self._load_variants("move", s)
        self.move_weights   = self._read_multi_weight("move_weight", len(self.move_variants), 1)
        self.move_flip_info = self._load_flip_info()

        drag_path = os.path.join(d, "drag.gif")
        self.drag_frames = load_gif_frames(drag_path, s) if os.path.exists(drag_path) else []

    def _load_variants(self, prefix, scale):
        d = self.dir
        single = os.path.join(d, f"{prefix}.gif")
        if os.path.exists(single):
            frames = load_gif_frames(single, scale)
            return [frames] if frames else []
        variants = []
        i = 1
        while True:
            p = os.path.join(d, f"{prefix}{i}.gif")
            if not os.path.exists(p):
                break
            variants.append(load_gif_frames(p, scale))
            i += 1
        return variants

    def _load_flip_info(self):
        p = os.path.join(self.dir, "flip.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _read_weight(self, key, default):
        p = os.path.join(self.dir, "weights.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f).get(key, default)
            except Exception:
                pass
        return default

    def _read_multi_weight(self, key, count, default):
        p = os.path.join(self.dir, "weights.json")
        if os.path.exists(p):
            try:
                data = json.load(open(p, "r", encoding="utf-8"))
                v = data.get(key, None)
                if isinstance(v, list) and len(v) == count:
                    return v
            except Exception:
                pass
        return [default] * max(count, 1)

    def pick_idle(self):
        if not self.idle_variants:
            return self.dynamic_frames or []
        return random.choices(self.idle_variants, weights=self.idle_weights, k=1)[0]

    def pick_move(self):
        if not self.move_variants:
            return self.dynamic_frames or []
        return random.choices(self.move_variants, weights=self.move_weights, k=1)[0]

    def should_flip(self, variant_name, going_right):
        info = self.move_flip_info.get(variant_name, {})
        if not info.get("enabled", False):
            return False
        default_dir = info.get("default_dir", "left")
        return going_right if default_dir == "left" else not going_right
