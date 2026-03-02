"""
platform_utils/autostart.py – Autostart helpers, abstracted per platform.
Currently implements Windows registry; stubs for Linux/macOS.
"""

import sys
import os

from core.config import APP_NAME

_REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_exe_path() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
        return f'"{pythonw}" "{script}"'


def get_autostart() -> bool:
    """Return True if autostart is currently enabled."""
    if sys.platform == "win32":
        return _win_get_autostart()
    elif sys.platform == "darwin":
        return _mac_get_autostart()
    else:
        return _linux_get_autostart()


def set_autostart(enable: bool) -> bool:
    """Enable or disable autostart. Returns True on success."""
    if sys.platform == "win32":
        return _win_set_autostart(enable)
    elif sys.platform == "darwin":
        return _mac_set_autostart(enable)
    else:
        return _linux_set_autostart(enable)


# ── Windows ───────────────────────────────────────────────────────────────────

def _win_get_autostart() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _win_set_autostart(enable: bool) -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_RUN_KEY,
            0, winreg.KEY_SET_VALUE | winreg.KEY_READ
        )
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _get_exe_path())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"[WARN] set_autostart({enable}): {e}")
        return False


# ── macOS ─────────────────────────────────────────────────────────────────────

def _mac_get_autostart() -> bool:
    """Check for a LaunchAgent plist."""
    plist = _mac_plist_path()
    return os.path.exists(plist)


def _mac_set_autostart(enable: bool) -> bool:
    plist = _mac_plist_path()
    try:
        if enable:
            exe = _get_exe_path().strip('"')
            content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{APP_NAME}</string>
  <key>ProgramArguments</key>
  <array><string>{exe}</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
"""
            os.makedirs(os.path.dirname(plist), exist_ok=True)
            with open(plist, "w") as f:
                f.write(content)
        else:
            if os.path.exists(plist):
                os.remove(plist)
        return True
    except Exception as e:
        print(f"[WARN] mac set_autostart({enable}): {e}")
        return False


def _mac_plist_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, "Library", "LaunchAgents", f"com.{APP_NAME.replace(' ', '')}.plist")


# ── Linux (systemd user service) ─────────────────────────────────────────────

def _linux_get_autostart() -> bool:
    return os.path.exists(_linux_autostart_path())


def _linux_set_autostart(enable: bool) -> bool:
    path = _linux_autostart_path()
    try:
        if enable:
            exe = _get_exe_path().strip('"')
            content = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec={exe}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
        else:
            if os.path.exists(path):
                os.remove(path)
        return True
    except Exception as e:
        print(f"[WARN] linux set_autostart({enable}): {e}")
        return False


def _linux_autostart_path() -> str:
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(config_home, "autostart", f"{APP_NAME}.desktop")
