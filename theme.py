# theme.py — application color theme management

import tkinter as tk
import json
import os

# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

THEME_DARK = {
    # Classic terminal look — dark background, contrasting colors
    "bg":                "#1a1a2e",
    "panel":             "#16213e",
    "card":              "#0f3460",
    "card_hover":        "#1a4a7a",
    "card_hover2":       "#1e3a5f",
    "accent":            "#e94560",
    "accent2":           "#f5a623",
    "text":              "#eaeaea",
    "text_dim":          "#8899aa",
    "progress_bg":       "#0a1628",
    "progress_fg":       "#e94560",
    "btn":               "#e94560",
    "btn_hover":         "#c73652",
    "btn_secondary":     "#0f3460",
    "btn_sec_hover":     "#1a4a7a",
    "border":            "#1e3a5f",
    "check_on":          "#e94560",
    "checkpoint_done":   "#1a3a1a",
    "checkpoint_undone": "#0f3460",
}

THEME_LIGHT = {
    # Windows-like — white background, dark font
    "bg":                "#f0f2f5",
    "panel":             "#ffffff",
    "card":              "#ffffff",
    "card_hover":        "#e8edf5",
    "card_hover2":       "#dce4f0",
    "accent":            "#1a56db",
    "accent2":           "#b45309",
    "text":              "#111827",
    "text_dim":          "#4b5563",
    "progress_bg":       "#d1d5db",
    "progress_fg":       "#1a56db",
    "btn":               "#1a56db",
    "btn_hover":         "#1447b5",
    "btn_secondary":     "#e5e7eb",
    "btn_sec_hover":     "#d1d5db",
    "border":            "#d1d5db",
    "check_on":          "#1a56db",
    "checkpoint_done":   "#dcfce7",
    "checkpoint_undone": "#f9fafb",
}

THEMES = {
    "dark":  THEME_DARK,
    "light": THEME_LIGHT,
}

THEME_NAMES = {
    "dark":  "Dark (terminal)",
    "light": "Light (Windows)",
}

# ---------------------------------------------------------------------------
# Active theme — module level singleton
# ---------------------------------------------------------------------------

_current_theme_name: str = "dark"
_current_colors: dict = dict(THEME_DARK)

# Settings file path (next to this file)
_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(data: dict):
    try:
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_theme():
    """Loads saved theme on application start."""
    global _current_theme_name
    settings = _load_settings()
    name = settings.get("theme", "dark")
    if name not in THEMES:
        name = "dark"
    _current_theme_name = name
    _current_colors.clear()
    _current_colors.update(THEMES[name])


def set_theme(name: str):
    """Sets theme and saves the choice to the settings file."""
    global _current_theme_name
    if name not in THEMES:
        return
    _current_theme_name = name
    _current_colors.clear()
    _current_colors.update(THEMES[name])
    settings = _load_settings()
    settings["theme"] = name
    _save_settings(settings)


def get_colors() -> dict:
    """Returns color dictionary of the active theme."""
    return _current_colors


def get_theme_name() -> str:
    return _current_theme_name


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog:
    """Application settings window — theme selection only for now."""

    def __init__(self, parent, on_theme_change=None):
        self.on_theme_change = on_theme_change
        colors = get_colors()

        self.window = tk.Toplevel(parent)
        self.window.title("Settings")
        self.window.configure(bg=colors["bg"])
        self.window.resizable(False, False)
        self.window.transient(parent)

        # Header
        tk.Frame(self.window, bg=colors["accent"], height=3).pack(fill="x")
        hdr = tk.Frame(self.window, bg=colors["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚙  SETTINGS",
                 font=("Segoe UI", 12, "bold"),
                 bg=colors["panel"], fg=colors["accent"],
                 padx=16, pady=10).pack(side="left")
        tk.Frame(self.window, bg=colors["accent"], height=1).pack(fill="x")

        body = tk.Frame(self.window, bg=colors["bg"], padx=20, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Color theme:", font=("Segoe UI", 10),
                 bg=colors["bg"], fg=colors["text"]).pack(anchor="w")

        self._theme_var = tk.StringVar(value=get_theme_name())

        radio_style = dict(
            bg=colors["bg"], fg=colors["text"],
            activebackground=colors["bg"], activeforeground=colors["text"],
            selectcolor=colors["card"], font=("Segoe UI", 10)
        )
        for key, label in THEME_NAMES.items():
            tk.Radiobutton(
                body, text=label,
                variable=self._theme_var, value=key,
                **radio_style
            ).pack(anchor="w", pady=2)

        # Buttons
        btn_bar = tk.Frame(self.window, bg=colors["bg"], padx=20, pady=10)
        btn_bar.pack(fill="x")

        cancel_lbl = tk.Label(btn_bar, text="Cancel",
                              font=("Segoe UI", 10),
                              bg=colors["btn_secondary"], fg=colors["text_dim"],
                              padx=10, pady=6, cursor="hand2")
        cancel_lbl.pack(side="right", padx=(8, 0))
        cancel_lbl.bind("<Button-1>", lambda e: self.window.destroy())

        save_lbl = tk.Label(btn_bar, text="Apply",
                            font=("Segoe UI", 10, "bold"),
                            bg=colors["btn"], fg="white",
                            padx=10, pady=6, cursor="hand2")
        save_lbl.pack(side="right")
        save_lbl.bind("<Button-1>", lambda e: self._apply())
        save_lbl.bind("<Enter>", lambda e: save_lbl.config(bg=colors["btn_hover"]))
        save_lbl.bind("<Leave>", lambda e: save_lbl.config(bg=colors["btn"]))

        self.window.bind("<Return>", lambda e: self._apply())
        self.window.bind("<Escape>", lambda e: self.window.destroy())

        # Auto-sizing — fit window to content
        self.window.update_idletasks()
        w = max(self.window.winfo_reqwidth() + 20, 320)
        h = self.window.winfo_reqheight() + 10
        self.window.geometry(f"{w}x{h}")

    def _apply(self):
        chosen = self._theme_var.get()
        if chosen != get_theme_name():
            set_theme(chosen)
            if self.on_theme_change:
                self.on_theme_change()
        self.window.destroy()
