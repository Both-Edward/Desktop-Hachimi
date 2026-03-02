"""
platform_utils/dpi.py – DPI awareness helpers per platform.
"""

import sys


def enable_dpi_awareness():
    """Make the process DPI-aware on platforms that support it."""
    if sys.platform == "win32":
        _win_dpi()
    # Linux / macOS: handled by the toolkit or not needed


def _win_dpi():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_monitors():
    """
    Return list of (x, y, w, h) for each monitor.
    Tries screeninfo first; falls back per-platform.
    """
    try:
        from screeninfo import get_monitors as _gm
        return [(m.x, m.y, m.width, m.height) for m in _gm()]
    except Exception:
        pass

    if sys.platform == "win32":
        result = _win_enum_monitors()
        if result:
            return result

    return None   # caller uses tkinter fallback


def _win_enum_monitors():
    try:
        import ctypes
        import ctypes.wintypes as wt

        class RECT(ctypes.Structure):
            _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                        ("right", wt.LONG), ("bottom", wt.LONG)]

        monitors = []
        cb_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(RECT), wt.LPARAM)

        def _cb(hm, hdc, lprect, data):
            r = lprect.contents
            monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return True

        ctypes.windll.user32.EnumDisplayMonitors(None, None, cb_type(_cb), 0)
        return monitors if monitors else None
    except Exception:
        return None
