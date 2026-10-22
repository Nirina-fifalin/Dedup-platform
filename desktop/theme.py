import colorsys
import json
import tempfile
from pathlib import Path
from tkinter import ttk
from typing import Any

import customtkinter as ctk

ORANGE = "#FF7900"        # orange de la marque
ORANGE_DARK = "#CC6100"   # survol, et texte orange sur fond clair

WINDOW_BG = ["#FFFFFF", "#141414"]
PANEL_BG = ["#F6F6F6", "#232323"]
PANEL_BG_2 = ["#EEEEEE", "#2E2E2E"]
DISABLED_BG = ("#E5E5E5", "#3A3A3A")
INPUT_BG = ["#FFFFFF", "#1E1E1E"]
INPUT_BORDER = ["#BDBDBD", "#555555"]


def _to_orange(color: Any) -> Any:
    """Remplace un bleu du thème par l'orange de la marque ; les gris et le reste ne changent pas."""
    if not (isinstance(color, str) and color.startswith("#") and len(color) == 7):
        return color
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if 0.50 <= h <= 0.64 and s > 0.30:                 # teintes bleues
        return ORANGE if v >= 0.64 else ORANGE_DARK
    return color


def _convert(node: Any) -> Any:
    if isinstance(node, str):
        return _to_orange(node)
    if isinstance(node, list):
        return [_convert(x) for x in node]
    if isinstance(node, dict):
        return {k: _convert(v) for k, v in node.items()}
    return node


def apply_orange_theme() -> None:
    """À appeler avant de créer la moindre fenêtre."""
    try:
        source = Path(ctk.__file__).resolve().parent / "assets" / "themes" / "blue.json"
        theme: dict[str, Any] = _convert(json.loads(source.read_text(encoding="utf-8")))
        for widget in ("CTkButton", "CTkOptionMenu"):
            theme[widget]["text_color"] = ["#000000", "#000000"]     # texte noir sur l'orange
        theme["CTkButton"]["text_color_disabled"] = ["#8F8F8F", "#8F8F8F"]
        theme.setdefault("CTk", {})["fg_color"] = WINDOW_BG          # page blanche
        theme.setdefault("CTkToplevel", {})["fg_color"] = WINDOW_BG
        theme.setdefault("CTkFrame", {})["fg_color"] = PANEL_BG      # cartes gris très clair
        theme["CTkFrame"]["top_fg_color"] = PANEL_BG_2
        # champs de saisie : fond blanc et contour visible
        theme.setdefault("CTkEntry", {}).update(fg_color=INPUT_BG, border_color=INPUT_BORDER)
        theme.setdefault("CTkTextbox", {}).update(
            fg_color=INPUT_BG, border_color=INPUT_BORDER, border_width=1
        )
        folder = Path(tempfile.mkdtemp())
        path = folder / "orange.json"
        path.write_text(json.dumps(theme), encoding="utf-8")
        try:
            ctk.set_default_color_theme(str(path))
        finally:
            path.unlink(missing_ok=True)
            folder.rmdir()
    except (OSError, ValueError, KeyError):
        ctk.set_default_color_theme("blue")


def polish_buttons() -> None:
    """Deux réglages communs à tous les boutons :
    - une couleur imposée (rouge, vert, gris) garde un texte blanc lisible ;
    - un bouton désactivé devient franchement gris, au lieu d'un orange délavé."""
    original_init = ctk.CTkButton.__init__
    original_configure = ctk.CTkButton.configure

    def grey_out(button) -> None:
        current = button.cget("fg_color")
        if current != "transparent" and current != DISABLED_BG:
            button._enabled_fg = current
            original_configure(button, fg_color=DISABLED_BG)

    def restore(button) -> None:
        saved = getattr(button, "_enabled_fg", None)
        if saved is not None:
            button._enabled_fg = None
            original_configure(button, fg_color=saved)

    def init(self, *args, **kwargs):
        fg = kwargs.get("fg_color")
        if "text_color" not in kwargs and fg not in (None, "transparent"):
            kwargs["text_color"] = "#FFFFFF"
        original_init(self, *args, **kwargs)
        if not hasattr(self, "_enabled_fg"):
            self._enabled_fg = None
        if kwargs.get("state") == "disabled":
            grey_out(self)

    def configure(self, require_redraw=False, **kwargs):
        result = original_configure(self, require_redraw=require_redraw, **kwargs)
        state = kwargs.get("state")
        if state == "disabled":
            grey_out(self)
        elif state == "normal":
            restore(self)
        return result

    ctk.CTkButton.__init__ = init  # type: ignore[method-assign]
    ctk.CTkButton.configure = configure  # type: ignore[method-assign]


def style_title_bar(window) -> None:
    """Barre de titre noire à bordure orange (Windows 11 ; sans effet sur Windows 10)."""
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        for attribute, colorref in (
            (35, 0x00000000),      # fond de la barre de titre : noir
            (36, 0x00FFFFFF),      # texte : blanc
            (34, 0x000079FF),      # bordure : orange #FF7900 (format Windows BBGGRR)
        ):
            value = ctypes.c_int(colorref)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass          # décoratif seulement : ne doit jamais bloquer l'application


def polish_windows() -> None:
    """Barre de titre noire et orange pour TOUTES les fenêtres secondaires, sans toucher à leur code."""
    original_init = ctk.CTkToplevel.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.after(250, lambda: style_title_bar(self))    # après l'affichage de la fenêtre

    ctk.CTkToplevel.__init__ = init  # type: ignore[method-assign]


def polish_tables() -> None:
    """Titres de colonnes alignés à gauche, comme les valeurs."""
    original_heading = ttk.Treeview.heading

    def heading(self, column, option=None, **kw):
        if option is None and "text" in kw and "anchor" not in kw:
            kw["anchor"] = "w"
        return original_heading(self, column, option, **kw)

    ttk.Treeview.heading = heading  # type: ignore[method-assign, assignment]