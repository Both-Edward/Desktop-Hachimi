# Choose Language

**Read this in other languages: [English](README.md), [简体中文](README_zh.md).**

---

# Desktop Hachimi - Smart Desktop Pet Companion 🐾

<div align="center">
    <img src="/ico/Desktop Hachimi ico.ico" width="150" height="150" />
</div>

Desktop Hachimi is a feature-rich desktop pet application that adds vibrancy and fun to your Windows desktop. This adorable digital companion moves freely on your desktop, responding to your interactions and bringing life to your digital workspace.

---

## Install dependencies

```bash
pip install Pillow pystray
```

> **Notice**: Python 3.8+ needed

---

## Run

```bash
python main.py
```

---

## Directory Structure

```
Desktop-Hachimi/
├── main.py
├── requirements.txt
├── config.json          ← Automatically generated and saved user settings
├── ico/
│   └── Desktop Hachimi ico.ico   ← Software icon
└── Pets/
    └── Ameath/          ← Default desktop pet folder
        ├── Ameath.ico   ← Desktop pet icon
        ├── Ameath.gif   ← Dynamic State
        ├── drag.gif     ← Drag State
        ├── idle.gif     ← Non-movement State (single image)
        │   Or idle1.gif, idle2.gif ...
        ├── move.gif     ← Movement Status (single image)
        │   Or move1.gif, move2.gif ...
        ├── weights.json ← State Weight
        └── flip.json    ← Reversed Motion Direction conDiguration (optional)
```

---

## weights.json Format Example

```json
{
  "dynamic_weight": 3,
  "idle_weight": [2],
  "move_weight": [1]
}
```

If there are multiple idle/move gifs, the length of the weight array corresponds to the number of files.

```json
{
  "dynamic_weight": 3,
  "idle_weight": [2, 3],
  "move_weight": [1, 2, 1]
}
```

---

## flip.json Format Example
```json
{
  "move": {
    "enabled": true,
    "default_dir": "left"
  },
  "move2": {
    "enabled": true,
    "default_dir": "right"
  }
}
```

When `default_dir` becomes `"left"`: moving to the left does not flip the image; moving to the right flips the image.
---

## System Tray Menu Description

Right-clicking the taskbar tray icon allows you to:

| Menu Items | Functions |
|--------|------|
| Switch Pet | Select from all pets under Pets/
| Pet Size | x0.1 ~ x2.0, increments of 0.1 |
| Transparency | 10% ~ 100%, increments of 10% |
| Speed ​​| 1 ~ 10 levels |
| Mouse Follow | When enabled, the pet follows the mouse movement |
| Top View | The pet is displayed on top of all windows |
| Create Pet | Open the creation wizard |
| About | Software Information and Updates |
| Exit | Close Program |

---

## Future Adaptation Plans

- [ ] LLM Agent
- [ ] TTS Agent
- [ ] Linux (GTK tray)
- [ ] macOS (rumps / AppKit tray)

---

## Package as a Windows installer (to be continued)

1. Install PyInstaller: `pip install pyinstaller`
2. Package: `pyinstaller --noconsole --onefile --icon="ico/Desktop Hachimi ico.ico" main.py`
3. Use Inno Setup or NSIS to create an installer from the contents of the dist/ directory.