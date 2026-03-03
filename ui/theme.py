"""
ui/theme.py – Centralized UI color palette and style constants.

All UI components (context menu, dialogs, music player) import from here.
Modify this file to change the global look & feel of Desktop Hachimi.
"""

# ── Context Menu & Dialog Shared Palette ──────────────────────────────────────
# These colors are used by the pet right-click context menu AND all popup dialogs,
# keeping a consistent pink/white cherry-blossom aesthetic.

# --- Background colors ---
BG           = "#fff0f5"   # Soft blush white  – main window/dialog background
CARD_BG      = "#ffe0ee"   # Light pink        – card / inner panel background
HEADER_BG    = "#ffb6d5"   # Vibrant pink      – header stripe / accent panels
DARK_BG      = "#2b1a2e"   # Deep purple       – (legacy, kept for compat)

# --- Text colors ---
TEXT         = "#5a1a3a"   # Deep rose         – primary text
TEXT_LIGHT   = "#9c6080"   # Muted rose        – secondary / label text
WHITE        = "#ffffff"   # Pure white        – bright text on dark backgrounds

# --- Accent colors ---
PINK         = "#e0457a"   # Hot pink          – accents, icons, highlights
PINK_LIGHT   = "#ffb6d5"   # Soft pink         – hover backgrounds, progress fill
GREEN        = "#6fcf97"   # Mint green        – save/confirm action buttons
GREEN_FG     = "#1a0a20"   # Dark text for green buttons

# --- Interactive state colors ---
HOVER_BG     = "#ffd0e8"   # Hover highlight   – menu/button hover background
SEL_BG       = "#f0a0c8"   # Selected item     – listbox selection background

# --- Separator / border colors ---
SEP          = "#f9c6d8"   # Separator line    – thin dividers in menus
SHADOW       = "#f0b8cc"   # Border/shadow     – 1px outer border effect
GRAY         = "#c090a8"   # Gray-pink         – disabled text, labels, info text

# --- Progress bar ---
PB_TRACK     = "#fad0e0"   # Progress track    – unfilled bar background
PB_FILL      = "#e0457a"   # Progress fill     – filled bar color
PB_THUMB     = "#ffffff"   # Progress thumb    – draggable circle

# --- Check / toggle indicator ---
CHECK        = "#e0457a"   # Checkmark color   – ✦ indicator in menus
BTN_BG       = "#ffffff"   # Button background – normal button bg

# --- Button styles (pre-composed dicts for tk.Button) ---
BTN_SAVE = dict(
    bg=GREEN, fg=GREEN_FG, relief="flat", padx=12,
    font=("Microsoft YaHei UI", 10, "bold"),
    activebackground="#5bbf85", activeforeground=GREEN_FG,
    cursor="hand2",
)

BTN_CANCEL = dict(
    bg=CARD_BG, fg=GRAY, relief="flat", padx=12,
    font=("Microsoft YaHei UI", 10),
    activebackground=HOVER_BG, activeforeground=TEXT,
    cursor="hand2",
)

BTN_ACCENT = dict(
    bg=PINK, fg=WHITE, relief="flat", padx=10,
    font=("Microsoft YaHei UI", 10, "bold"),
    activebackground="#c03060", activeforeground=WHITE,
    cursor="hand2",
)

BTN_NORMAL = dict(
    bg=CARD_BG, fg=PINK, relief="flat", padx=8,
    font=("Microsoft YaHei UI", 10),
    activebackground=HOVER_BG, activeforeground=PINK,
    cursor="hand2",
)

BTN_CLOSE = dict(
    bg=CARD_BG, fg=TEXT_LIGHT, relief="flat", padx=12,
    font=("Microsoft YaHei UI", 10),
    activebackground=HOVER_BG, activeforeground=TEXT,
    cursor="hand2",
)

# --- Spinbox style ---
SPINBOX_STYLE = dict(
    bg=CARD_BG, fg=PINK, insertbackground=PINK,
    buttonbackground=CARD_BG, relief="flat",
    highlightthickness=1, highlightbackground=SEP,
    font=("Microsoft YaHei UI", 10),
)

# --- Entry style ---
ENTRY_STYLE = dict(
    bg=CARD_BG, fg=TEXT, insertbackground=PINK,
    relief="flat", highlightthickness=1, highlightbackground=SEP,
)

# --- Listbox style ---
LISTBOX_STYLE = dict(
    bg=CARD_BG, fg=TEXT,
    selectbackground=SEL_BG, selectforeground=TEXT,
    bd=0, highlightthickness=0, activestyle="none",
)

# --- Fonts (mirrors core/config.py FONT_* constants) ---
FONT_NORMAL = ("Microsoft YaHei UI", 10)
FONT_BOLD   = ("Microsoft YaHei UI", 10, "bold")
FONT_LARGE  = ("Microsoft YaHei UI", 13, "bold")
FONT_SMALL  = ("Microsoft YaHei UI", 9)
FONT_TITLE  = ("Microsoft YaHei UI", 15, "bold")
