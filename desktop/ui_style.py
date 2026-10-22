from tkinter import ttk

import customtkinter as ctk

from theme import ORANGE, ORANGE_DARK


def apply_tree_style(widget) -> None:
    """Aspect des tableaux : titres noirs, ligne sélectionnée orange, barre de défilement fine."""
    dark = ctk.get_appearance_mode() == "Dark"
    bg, fg = ("#2b2b2b", "#e6e6e6") if dark else ("#ffffff", "#1a1a1a")
    trough = "#1e1e1e" if dark else "#f2f2f2"
    thumb = "#555555" if dark else "#c9c9c9"
    arrow = "#ffffff" if dark else "#000000"
    style = ttk.Style(widget)
    style.theme_use("clam")
    style.configure("Treeview", background=bg, fieldbackground=bg, foreground=fg,
                    rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", background="#000000" if not dark else "#1a1a1a",
                    foreground="#ffffff", relief="flat", font=("Segoe UI", 10, "bold"))
    style.map("Treeview.Heading", background=[("active", ORANGE_DARK)],
              foreground=[("active", "#000000")])
    style.map("Treeview", background=[("selected", ORANGE)], foreground=[("selected", "#000000")])
    style.configure("Vertical.TScrollbar", background=thumb, troughcolor=trough, bordercolor=trough,
                    lightcolor=thumb, darkcolor=thumb, arrowcolor=arrow, relief="flat")
    style.map("Vertical.TScrollbar", background=[("active", ORANGE)],
              lightcolor=[("active", ORANGE)], darkcolor=[("active", ORANGE)])