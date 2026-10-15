from tkinter import ttk

import customtkinter as ctk

from theme import ORANGE, ORANGE_DARK


def apply_tree_style(widget) -> None:
    """Aspect des tableaux : titres noirs, ligne sélectionnée orange."""
    dark = ctk.get_appearance_mode() == "Dark"
    bg, fg = ("#2b2b2b", "#e6e6e6") if dark else ("#ffffff", "#1a1a1a")
    style = ttk.Style(widget)
    style.theme_use("clam")
    style.configure("Treeview", background=bg, fieldbackground=bg, foreground=fg,
                    rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", background="#000000" if not dark else "#1a1a1a",
                    foreground="#ffffff", relief="flat", font=("Segoe UI", 10, "bold"))
    style.map("Treeview.Heading", background=[("active", ORANGE_DARK)],
              foreground=[("active", "#000000")])
    style.map("Treeview", background=[("selected", ORANGE)], foreground=[("selected", "#000000")])