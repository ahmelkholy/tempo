"""Shared colors and window placement for Tempo's Tk interface."""

import tkinter as tk
from tkinter import ttk


def palette(config, widget):
    dark = config.get("dark_theme", True)
    colors = (
        ("#171b1b", "#252c2b", "#f3f5f1", "#b0bcb7", "#374843", "#a5dfba")
        if dark
        else ("#f3f5f0", "#ffffff", "#192b22", "#52635a", "#d8e5dc", "#216342")
    )
    result = dict(zip(("bg", "card", "fg", "muted", "selected", "accent"), colors))
    accent = config.get("accent_color", "")
    if accent and accent != "#00ff00":
        try:
            widget.winfo_rgb(accent)
            result["accent"] = accent
        except tk.TclError:
            pass
    return result


def place_dialog(window, parent):
    """Size to content and let Tk place the window on its parent's screen."""
    scale = getattr(window._root(), "_tempo_scale", None)
    if scale:
        scale.tree(window)
    window.tk.call("tk::PlaceWindow", window._w, "widget", parent.winfo_toplevel()._w)


def apply_styles(root, colors):
    style = ttk.Style(root)
    if style.theme_use() != "clam":
        style.theme_use("clam")
    bg, fg, card = colors["bg"], colors["fg"], colors["card"]
    accent, muted, hover = colors["accent"], colors["muted"], colors["selected"]
    root.configure(bg=bg)
    root.option_add("*TCombobox*Listbox.background", card)
    root.option_add("*TCombobox*Listbox.foreground", fg)
    root.option_add("*TCombobox*Listbox.selectBackground", hover)
    root.option_add("*TCombobox*Listbox.selectForeground", fg)
    style.configure(".", background=bg, foreground=fg)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg, font=("Arial", 11))
    for name in ("TButton", "TMenubutton"):
        style.configure(
            name,
            background=card,
            foreground=fg,
            borderwidth=0,
            padding=(8, 5),
            arrowcolor=muted,
        )
        style.map(
            name,
            background=[("pressed", hover), ("active", hover)],
            foreground=[("disabled", muted)],
        )
    style.configure("Muted.TLabel", foreground=muted)
    style.configure(
        "Error.TLabel",
        foreground="#ffb4a7" if colors["bg"] == "#171b1b" else "#9a3028",
    )
    style.configure("Secondary.TButton", background=hover)
    style.configure(
        "TNotebook",
        background=bg,
        bordercolor=bg,
        lightcolor=bg,
        darkcolor=bg,
        borderwidth=0,
    )
    style.configure(
        "TNotebook.Tab",
        background=bg,
        foreground=muted,
        bordercolor=bg,
        lightcolor=bg,
        darkcolor=bg,
        padding=(10, 7),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", card), ("active", hover)],
        foreground=[("selected", fg)],
    )
    for name in ("TCheckbutton", "TRadiobutton"):
        style.map(
            name,
            background=[("active", bg)],
            indicatorbackground=[("selected", accent), ("!selected", card)],
        )
    rgb = [value / 65535 for value in root.winfo_rgb(accent)]
    luminance = sum(
        weight * (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
        for weight, v in zip((0.2126, 0.7152, 0.0722), rgb)
    )
    ink = "#101412" if luminance > 0.20 else "#ffffff"
    for name in ("Modern.TButton", "MusicPlay.TButton"):
        style.configure(name, background=accent, foreground=ink, padding=(10, 6))
        style.map(
            name,
            background=[("active", hover)],
            foreground=[("active", fg), ("disabled", muted)],
        )
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            name,
            fieldbackground=card,
            foreground=fg,
            insertcolor=fg,
            arrowcolor=fg,
            bordercolor=hover,
            lightcolor=card,
            darkcolor=card,
            padding=3,
        )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", card)],
        foreground=[("readonly", fg)],
    )
    style.configure(
        "TScale",
        background=muted,
        troughcolor=hover,
        lightcolor=muted,
        darkcolor=muted,
        bordercolor=hover,
        gripcount=0,
    )
    style.configure(
        "Horizontal.TProgressbar",
        background=accent,
        troughcolor=hover,
        bordercolor=hover,
        lightcolor=accent,
        darkcolor=accent,
        borderwidth=0,
    )
    style.configure("Horizontal.TProgressbar", arrowsize=4)
    style.configure(
        "TScrollbar",
        background=card,
        troughcolor=bg,
        bordercolor=bg,
        arrowcolor=muted,
        arrowsize=9,
    )
    style.configure("Current.TFrame", background=card)

    style.configure("Card.TFrame", background=card)
    style.configure("Treeview", fieldbackground=card, background=card, foreground=fg)
    style.map(
        "Treeview", background=[("selected", hover)], foreground=[("selected", fg)]
    )


def _pixel_values(widget, value):
    parts = value if isinstance(value, tuple) else widget.tk.splitlist(str(value))
    return tuple(widget.winfo_pixels(part) for part in parts)


class WindowScale:
    """Scale Tk widgets from their original measurements, including new dialogs."""

    def __init__(self, root):
        self.root = root
        self.level = 1.0
        self.fonts = {}
        root.bind_all("<Map>", self._mapped, add="+")

    def _mapped(self, event):
        # Tk also sends events for native popdown windows without a Python widget.
        if isinstance(event.widget, tk.Misc):
            self.widget(event.widget)

    def apply(self, level):
        self.level = level
        for font, size in self.fonts.values():
            font.configure(size=self.font_size(size))
        style = ttk.Style(self.root)
        base = ("Arial", self.font_size(11))
        style.configure(".", font=base)
        for name in (
            "TLabel",
            "TButton",
            "TEntry",
            "TCombobox",
            "TMenubutton",
            "TSpinbox",
            "TCheckbutton",
            "TRadiobutton",
            "Treeview.Heading",
        ):
            style.configure(name, font=base)
        for name, x, y in (
            ("TButton", 8, 5),
            ("TMenubutton", 8, 5),
            ("Modern.TButton", 10, 6),
            ("MusicPlay.TButton", 10, 6),
            ("TNotebook.Tab", 10, 7),
        ):
            style.configure(name, padding=(round(x * level), round(y * level)))
        for name in ("Modern.TButton", "MusicPlay.TButton"):
            style.configure(name, font=(*base, "bold"))
        style.configure("Treeview", rowheight=round(24 * level))
        for name in ("TEntry", "TSpinbox", "TCombobox"):
            style.configure(name, padding=max(1, round(3 * level)))
        self.tree(self.root)

    def font_size(self, size):
        return (1 if size >= 0 else -1) * max(1, round(abs(size) * self.level))

    def tree(self, parent):
        self.widget(parent)
        for child in parent.winfo_children():
            self.tree(child)

    def widget(self, widget):
        if getattr(widget, "_tempo_scale_level", None) == self.level:
            return
        if not hasattr(widget, "_tempo_dimensions"):
            from tkinter import font as tkfont

            options = widget.keys()
            if "font" in options and (spec := str(widget.cget("font"))):
                if spec not in self.fonts:
                    font = tkfont.Font(root=self.root, font=spec)
                    size = font.actual("size")
                    font.configure(size=self.font_size(size))
                    self.fonts[spec] = (font, size)
                widget.configure(font=self.fonts[spec][0])
            # Text widths and heights already follow their font. Scale pixel units.
            sizes = ["padx", "pady", "padding", "wraplength"]
            if isinstance(widget, (tk.Canvas, tk.Frame, ttk.Frame)):
                sizes.extend(("height", "width"))
            dimensions = {}
            for key in sizes:
                if key in options:
                    values = _pixel_values(widget, widget.cget(key))
                    if any(values):
                        dimensions[key] = values
            widget._tempo_dimensions = dimensions

        manager = widget.winfo_manager()
        widget._tempo_scale_level = self.level if manager else None
        for key, values in widget._tempo_dimensions.items():
            scaled = tuple(max(0, round(value * self.level)) for value in values)
            widget.configure(**{key: scaled[0] if len(scaled) == 1 else scaled})
        if manager in ("grid", "pack"):
            if not hasattr(widget, "_tempo_spacing"):
                info = widget.grid_info() if manager == "grid" else widget.pack_info()
                widget._tempo_spacing = {
                    key: _pixel_values(widget, info[key])
                    for key in ("padx", "pady", "ipadx", "ipady")
                    if info.get(key)
                }
            options = {
                key: tuple(round(v * self.level) for v in values)
                for key, values in widget._tempo_spacing.items()
            }
            if options:
                configure = (
                    widget.grid_configure
                    if manager == "grid"
                    else widget.pack_configure
                )
                configure(
                    **{key: v[0] if len(v) == 1 else v for key, v in options.items()}
                )


def scale_interface(root, level):
    if not hasattr(root, "_tempo_scale"):
        root._tempo_scale = WindowScale(root)
    root._tempo_scale.apply(level)
