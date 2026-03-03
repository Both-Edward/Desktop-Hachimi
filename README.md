# Choose Language

**Read this in other languages: [English](README.md), [简体中文](README_zh.md).**

---

# Desktop Hachimi - Smart Desktop Pet Companion 🐾

<div align="center">
    <img src="/ico/Desktop Hachimi ico.ico" width="150" height="150" />
</div>

Desktop Hachimi is a feature-rich desktop pet application that adds vibrancy and fun to your Windows desktop. This adorable digital companion moves freely on your desktop, responds to your interactions, plays music alongside you, and brings life to your digital workspace.

---

## Install Dependencies

```bash
pip install -r requirements.txt
```

Full dependency list:

```
Pillow >= 10.0.0
pystray >= 0.19.4
screeninfo >= 0.8.1
numpy >= 1.24.0
pygame >= 2.0.0
send2trash >= 1.8.2
```

> **Notice**: Python 3.8+ required

---

## Run

```bash
python main.py
```

---

## Features

### 🐾 Pet States

The pet switches between four states automatically and in response to user actions:

| State | Description |
|-------|-------------|
| **Dynamic** | Lively animation — triggered on launch, by music playback, or by mouse proximity |
| **Idle** | Resting animation — plays when the pet is stationary |
| **Move** | Walking animation — pet roams freely around the screen |
| **Drag** | Drag animation — plays while you drag the pet with the mouse |

State transitions happen on a 5-second timer according to configurable weights (see `weights.json`).

### 🎵 Music-Reactive Mode

The built-in music player is linked directly to the pet's behavior:

- When a song **starts playing**, the pet immediately enters the **Dynamic** state and stays there for the entire duration of the track.
- When the song **stops or is paused**, the pet is released and randomly transitions to one of its other states based on the configured weights.
- This lock is respected by all other state systems — the autonomous timer, mouse-follow logic, and movement triggers will not override Dynamic state while music is playing.

### 🎵 Music Player

Open via right-click menu on the pet → **Music Player**.

- Supports MP3, WAV, OGG, FLAC, AAC, M4A, WMA
- Playback modes: Loop All / Loop One / Play Once
- Controls: Previous, Play/Pause, Next
- Draggable progress bar with time display
- Double-click a track in the playlist to jump to it
- Add tracks from anywhere on your computer (copied into the `Music/` folder)
- Delete tracks to the recycle bin

### 🖱️ Mouse Follow

When enabled, the pet chases your cursor around the screen. As the cursor approaches, the pet switches to the Dynamic state; as it moves away, the pet transitions back to moving.

### 🎨 Pet Customization

- **Switch Pet** — choose from all pets in the `Pets/` folder
- **Create Pet** — built-in wizard to assemble a new pet from your own GIFs and icons
- **Delete Pet** — move a pet folder to the recycle bin from the menu
- **Size** — scale from x0.1 to x2.0 in steps of 0.1
- **Opacity** — 10% to 100% in steps of 10%
- **Speed** — 10 levels
- **State Weights** — adjust how often each state appears via the weight editor
- **Motion Flip** — configure per-move-variant whether the sprite flips horizontally

### 🖥️ Display

- **Always on Top** — keep the pet above all other windows
- **Multi-monitor support** — the pet stays within the bounds of whichever screen it is on
- **Position memory** — window position is saved and restored between sessions

### ⚙️ System

- **Autostart** — launch with Windows
- **System tray icon** — shows the app in the system tray; double-click to focus the pet
- **Check for updates** — built into the About dialog

---

## Right-Click Context Menu

Right-clicking the **pet sprite** opens the full control menu. The system tray icon only has a minimal **Exit** item — all features are accessible from the pet's right-click menu.

| Menu Item | Function |
|-----------|----------|
| Switch Pet | Choose from all pets in `Pets/` |
| Delete Pet | Move a pet folder to the recycle bin |
| Pet Size | x0.1 ~ x2.0, step 0.1 |
| Opacity | 10% ~ 100%, step 10% |
| Speed | Levels 1 ~ 10 |
| Mouse Follow | Pet follows the cursor when enabled |
| Always on Top | Pet stays above all other windows |
| Launch on Startup | Register/remove Windows autostart entry |
| Music Player | Open the music player window |
| Edit State Weights | Adjust per-state probability weights |
| Edit Motion Flip | Configure sprite flip per move variant |
| Create Pet | Open the pet creation wizard |
| About | Software info and update check |
| Exit | Close the program |

---

## Directory Structure

```
Desktop-Hachimi/
├── main.py                  <- Application entry point
├── requirements.txt
├── config.json              <- Auto-generated user settings
├── core/                    <- Backend: config, GIF loader, pet data
├── ui/                      <- Frontend: all tkinter UI components
│   ├── theme.py             <- ★ Centralized UI color palette & styles
│   ├── music_player.py      <- Music player dialog
│   └── helpers.py           <- Shared UI utilities
├── compat/                  <- Platform helpers (autostart, DPI, trash)
├── ico/                     <- UI and window icons
├── Music/                   <- Music folder (add your tracks here)
└── Pets/
    └── Ameath/              <- Default pet folder
        ├── Ameath.ico
        ├── Ameath.gif       <- Dynamic state animation
        ├── drag.gif         <- Drag state animation
        ├── idle.gif         <- Idle state (single file)
        │   or idle1.gif, idle2.gif ...
        ├── move.gif         <- Move state (single file)
        │   or move1.gif, move2.gif ...
        ├── weights.json     <- State weights
        └── flip.json        <- Motion flip config (optional)
```

---

## UI Theming

All UI colors, fonts, and button styles are centralized in **`ui/theme.py`**. To change the visual style of all dialogs and the music player at once, simply edit the constants in that file — no hunting through individual dialog classes needed.

Key constants in `ui/theme.py`:

| Constant | Purpose |
|----------|---------|
| `BG` | Main dialog background |
| `CARD_BG` | Inner card / panel background |
| `HEADER_BG` | Header stripe color |
| `PINK` | Accent color (buttons, highlights) |
| `TEXT` | Primary text color |
| `BTN_SAVE` | Style dict for save/confirm buttons |
| `BTN_CLOSE` | Style dict for close/cancel buttons |

---

## weights.json Format

```json
{
  "dynamic_weight": 3,
  "idle_weight": [2],
  "move_weight": [1]
}
```

If there are multiple idle/move GIFs, the weight array length must match the number of files.

---

## flip.json Format

```json
{
  "move": {
    "enabled": true,
    "default_dir": "left"
  }
}
```

When `default_dir` is `"left"`: moving left does not flip the sprite; moving right flips it.

---

## Future Plans

- [ ] LLM Agent
- [ ] TTS Agent
- [ ] Linux (GTK tray)
- [ ] macOS (rumps / AppKit tray)
