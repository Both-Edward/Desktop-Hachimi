"""
platform_utils/trash.py – Move files/folders to the OS recycle bin / trash.
Uses send2trash if available, with a manual fallback.
"""

import sys
import os
import shutil


def move_to_trash(path: str) -> bool:
    """
    Move *path* (file or directory) to the OS recycle bin / trash.
    Returns True on success, False on failure.
    """
    if not os.path.exists(path):
        return False
    try:
        import send2trash
        send2trash.send2trash(path)
        return True
    except ImportError:
        pass

    # Fallback per platform
    try:
        if sys.platform == "win32":
            return _win_trash(path)
        elif sys.platform == "darwin":
            return _mac_trash(path)
        else:
            return _linux_trash(path)
    except Exception as e:
        print(f"[WARN] move_to_trash({path}): {e}")
        return False


def _win_trash(path: str) -> bool:
    try:
        from ctypes import windll, wintypes, create_unicode_buffer, byref, Structure, c_int
        import ctypes

        # SHFileOperation with FO_DELETE + FOF_ALLOWUNDO
        class SHFILEOPSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hwnd",                 wintypes.HWND),
                ("wFunc",                ctypes.c_uint),
                ("pFrom",                ctypes.c_wchar_p),
                ("pTo",                  ctypes.c_wchar_p),
                ("fFlags",               ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings",         ctypes.c_void_p),
                ("lpszProgressTitle",     ctypes.c_wchar_p),
            ]

        FO_DELETE   = 0x0003
        FOF_ALLOWUNDO        = 0x0040
        FOF_NOCONFIRMATION   = 0x0010
        FOF_NOERRORUI        = 0x0400
        FOF_SILENT           = 0x0004

        op = SHFILEOPSTRUCT()
        op.wFunc  = FO_DELETE
        op.pFrom  = path + "\0"   # double-null terminated
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT

        ret = windll.shell32.SHFileOperationW(byref(op))
        return ret == 0
    except Exception:
        return False


def _mac_trash(path: str) -> bool:
    import subprocess
    abs_path = os.path.abspath(path)
    result = subprocess.run(
        ["osascript", "-e",
         f'tell application "Finder" to delete POSIX file "{abs_path}"'],
        capture_output=True
    )
    return result.returncode == 0


def _linux_trash(path: str) -> bool:
    # Try gio trash (GNOME / KDE with glib)
    import subprocess
    for cmd in [["gio", "trash", path], ["kioclient5", "move", path, "trash:/"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=5)
            if r.returncode == 0:
                return True
        except Exception:
            continue
    # Manual XDG trash spec fallback
    return _xdg_trash(path)


def _xdg_trash(path: str) -> bool:
    """Implement XDG Trash specification manually."""
    import time
    import urllib.parse

    abs_path = os.path.abspath(path)
    trash_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "Trash")
    files_dir = os.path.join(trash_dir, "files")
    info_dir  = os.path.join(trash_dir, "info")
    os.makedirs(files_dir, exist_ok=True)
    os.makedirs(info_dir, exist_ok=True)

    base = os.path.basename(abs_path)
    dest = os.path.join(files_dir, base)
    # avoid name collision
    counter = 1
    while os.path.exists(dest):
        name, ext = os.path.splitext(base)
        dest = os.path.join(files_dir, f"{name}_{counter}{ext}")
        counter += 1

    info_name = os.path.basename(dest) + ".trashinfo"
    info_path = os.path.join(info_dir, info_name)
    deletion_date = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    with open(info_path, "w") as f:
        f.write(f"[Trash Info]\nPath={abs_path}\nDeletionDate={deletion_date}\n")

    shutil.move(abs_path, dest)
    return True
