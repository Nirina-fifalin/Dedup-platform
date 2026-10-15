import colorsys
import json
import tempfile
from pathlib import Path
from typing import Any

import customtkinter as ctk

ORANGE = "#FF7900"        # orange de la marque
ORANGE_DARK = "#CC6100"   # survol, et texte orange sur fond clair


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
        theme = _convert(json.loads(source.read_text(encoding="utf-8")))
        for widget in ("CTkButton", "CTkOptionMenu"):
            theme[widget]["text_color"] = ["#000000", "#000000"]     # texte noir sur l'orange
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


def keep_white_text_on_colored_buttons() -> None:
    """Les boutons rouges, verts ou gris (couleur imposée) gardent un texte blanc lisible."""
    original = ctk.CTkButton.__init__

    def init(self, *args, **kwargs):
        fg = kwargs.get("fg_color")
        if "text_color" not in kwargs and fg not in (None, "transparent"):
            kwargs["text_color"] = "#FFFFFF"
        original(self, *args, **kwargs)

    ctk.CTkButton.__init__ = init  # type: ignore[method-assign]