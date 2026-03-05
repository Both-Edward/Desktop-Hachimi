"""
core/i18n.py – Internationalization helper.

Language files live in ./Language/<code>.json
Supported codes: zh_CN (Simplified Chinese), zh_TW (Traditional Chinese),
                 en_US (English), ja_JP (Japanese)
The active language is stored in config.json as "language".
"""

import os
import json

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG_DIR  = os.path.join(_BASE_DIR, "Language")

# Built-in fallback so the app works even if Language/ folder is missing
_FALLBACK: dict = {}

_strings: dict = {}
_current_lang: str = "zh_CN"

AVAILABLE_LANGS = {
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "en_US": "English",
    "ja_JP": "日本語",
    "ko_KR": "한국어",
    "fr_FR": "Français",
}


def _load(lang_code: str) -> dict:
    path = os.path.join(LANG_DIR, f"{lang_code}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def init(lang_code: str = "zh_CN") -> None:
    """Load language strings. Call once at startup."""
    global _strings, _current_lang
    _current_lang = lang_code
    _strings = _load(lang_code)
    # Ensure Simplified Chinese fallback is available for missing keys
    if lang_code != "zh_CN":
        fallback = _load("zh_CN")
        for k, v in fallback.items():
            _strings.setdefault(k, v)


def get(key: str, **kwargs) -> str:
    """Return translated string, optionally formatted with kwargs."""
    text = _strings.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text


def current() -> str:
    return _current_lang
