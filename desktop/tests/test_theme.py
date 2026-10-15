import json
from pathlib import Path

import customtkinter as ctk

import theme


def test_blue_theme_colors_become_orange_and_greys_stay():
    assert theme._to_orange("#3B8ED0") == theme.ORANGE
    assert theme._to_orange("#1F6AA5") == theme.ORANGE
    assert theme._to_orange("#144870") == theme.ORANGE_DARK
    assert theme._to_orange("#979DA2") == "#979DA2"        # gris : inchangé
    assert theme._to_orange("transparent") == "transparent"
    assert theme._to_orange("gray10") == "gray10"


def test_converted_builtin_theme_has_no_blue_left():
    source = Path(ctk.__file__).resolve().parent / "assets" / "themes" / "blue.json"
    converted = json.dumps(theme._convert(json.loads(source.read_text(encoding="utf-8")))).lower()
    for blue in ("#3b8ed0", "#1f6aa5", "#36719f", "#144870"):
        assert blue not in converted