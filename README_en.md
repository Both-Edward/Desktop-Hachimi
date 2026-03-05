# Choose Language

**Read this in other languages: [English](README_en.md), [简体中文](README.md).**

---

# Desktop Hachimi - Smart Desktop Pet Companion 🐾

<div align="center">
    <img src="/ico/Desktop Hachimi ico.ico" width="150" height="150" />
</div>

Desktop Hachimi is a feature-rich desktop pet application that adds vibrancy and fun to your Windows desktop. This adorable digital companion moves freely on your desktop, responds to your interactions, plays music alongside you, and brings life to your digital workspace.

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

State transitions happen on a 5-second timer according to configurable weights.

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
- Add tracks from anywhere on your computer
- Delete tracks to the recycle bin

### 🖱️ Mouse Follow

When enabled, the pet chases your cursor around the screen. As the cursor approaches, the pet switches to the Dynamic state; as it moves away, the pet transitions back to moving.

### 🎨 Pet Customization

- **Switch Pet** — choose from all installed pets
- **Create Pet** — built-in wizard to assemble a new pet from your own GIFs and icons
- **Delete Pet** — move a pet to the recycle bin from the menu
- **Size** — scale from x0.1 to x2.0 in steps of 0.1
- **Opacity** — 10% to 100% in steps of 10%
- **Speed** — 10 levels
- **State Weights** — adjust how often each state appears via the weight editor
- **Motion Flip** — configure per-move-variant whether the sprite flips horizontally

### 🌐 Language

Switch between **Simplified Chinese (简体中文)**, **Traditional Chinese (繁體中文)**, **English**, **Japanese (日本語)**, **Korean (한국어)**, and **French (Français)** at any time via the right-click menu. The selected language is saved and restored on next launch.

### 🖥️ Display

- **Always on Top** — keep the pet above all other windows
- **Multi-monitor support** — the pet stays within the bounds of whichever screen it is on
- **Position memory** — window position is saved and restored between sessions

### ⚙️ System

- **Autostart** — launch with Windows
- **System tray icon** — shows the app in the system tray; double-click to focus the pet
- **Check for updates** — built into the About dialog

---

## Future Plans

- [x] Internationalization (Simplified Chinese, Traditional Chinese, English, Japanese, Korean, French)
- [ ] LLM Agent
- [ ] TTS Agent
- [ ] Linux (GTK tray)
- [ ] macOS (rumps / AppKit tray)
