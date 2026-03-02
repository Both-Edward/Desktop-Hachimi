"""
core/gif_loader.py – GIF frame loading, with alpha-correct resizing.
No tkinter dependency; returns PIL images + durations.
"""

from PIL import Image, ImageTk, ImageSequence


def _resize_rgba_no_bleed(img_rgba, new_w, new_h):
    """
    Resize an RGBA image without black-border bleeding artefacts.
    Uses pre-multiplied alpha (alpha-weighted) resampling.
    """
    import numpy as np

    arr = np.array(img_rgba, dtype=np.float32)
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    alpha_norm = a / 255.0

    pre = _np_stack([r * alpha_norm, g * alpha_norm, b * alpha_norm, a])
    pre_img = Image.fromarray(pre, "RGBA")

    pre_resized = pre_img.resize((new_w, new_h), Image.LANCZOS)
    pre_arr     = np.array(pre_resized, dtype=np.float32)

    ra = pre_arr[..., 3] / 255.0
    out = _np_zeros_like(pre_arr)
    mask = ra > 0
    for c in range(3):
        ch = pre_arr[..., c]
        out[..., c] = _np_where(mask, _np_clip(ch / _np_where(mask, ra, 1), 0, 255), 0)
    out[..., 3] = pre_arr[..., 3]

    import numpy as np
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def _np_stack(channels):
    import numpy as np
    return np.stack(channels, axis=-1).astype(np.uint8)


def _np_zeros_like(arr):
    import numpy as np
    return np.zeros_like(arr)


def _np_where(mask, a, b):
    import numpy as np
    return np.where(mask, a, b)


def _np_clip(arr, lo, hi):
    import numpy as np
    return np.clip(arr, lo, hi)


def load_gif_frames(path: str, scale: float = 1.0) -> list:
    """
    Return list of (ImageTk.PhotoImage, duration_ms, pil_image).
    pil_image is retained so frames can be flipped on demand.
    """
    frames = []
    try:
        img = Image.open(path)
        for frame in ImageSequence.Iterator(img):
            duration = frame.info.get("duration", 100)
            f = frame.convert("RGBA")
            if scale != 1.0:
                w = max(1, int(f.width  * scale))
                h = max(1, int(f.height * scale))
                f = _resize_rgba_no_bleed(f, w, h)
            frames.append((ImageTk.PhotoImage(f), duration, f))
    except Exception as e:
        print(f"[WARN] load_gif_frames({path}): {e}")
    return frames
