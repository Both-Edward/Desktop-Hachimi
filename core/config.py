"""
core/config.py – App-wide constants, config load/save, and path helpers.
"""

import os
import json

# ── App Info ──────────────────────────────────────────────────────────────────
VERSION      = "1.1.2"
APP_NAME     = "Desktop Hachimi"
AUTHOR       = "Edward"
AUTHOR_EMAIL = "lingzhanye4@gmail.com"
GITHUB_URL   = "https://github.com/Edward-EH-Holmes/Desktop-Hachimi"
GITHUB_RELEASES = "https://github.com/Edward-EH-Holmes/Desktop-Hachimi/releases"

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PETS_DIR   = os.path.join(BASE_DIR, "Pets")
ICO_DIR    = os.path.join(BASE_DIR, "ico")
MUSIC_DIR  = os.path.join(BASE_DIR, "Music")
APP_ICO    = os.path.join(ICO_DIR, "Desktop Hachimi ico.ico")
CONFIG_F   = os.path.join(BASE_DIR, "config.json")

# ── Default Config ────────────────────────────────────────────────────────────
DEFAULT_CFG = {
    "pet":           "Ameath",
    "scale":         1.0,
    "opacity":       1.0,
    "speed":         3,
    "mouse_follow":  False,
    "always_on_top": True,
    "x":             100,
    "y":             100,
}

# ── Global font tokens (used by UI layer) ─────────────────────────────────────
FONT_NORMAL = ("Microsoft YaHei UI", 10)
FONT_BOLD   = ("Microsoft YaHei UI", 10, "bold")
FONT_LARGE  = ("Microsoft YaHei UI", 13, "bold")
FONT_SMALL  = ("Microsoft YaHei UI", 9)


def load_config() -> dict:
    if os.path.exists(CONFIG_F):
        try:
            with open(CONFIG_F, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CFG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return DEFAULT_CFG.copy()


def save_config(cfg: dict) -> None:
    with open(CONFIG_F, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_available_pets() -> list[str]:
    if not os.path.isdir(PETS_DIR):
        return []
    return [d for d in os.listdir(PETS_DIR) if os.path.isdir(os.path.join(PETS_DIR, d))]


def get_music_files() -> list[str]:
    """Return list of music file paths under MUSIC_DIR."""
    os.makedirs(MUSIC_DIR, exist_ok=True)
    exts = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma"}
    result = []
    for fname in sorted(os.listdir(MUSIC_DIR)):
        if os.path.splitext(fname)[1].lower() in exts:
            result.append(os.path.join(MUSIC_DIR, fname))
    return result
