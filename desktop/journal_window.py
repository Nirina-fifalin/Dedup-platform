import sqlite3
from contextlib import closing
from tkinter import messagebox, ttk

import customtkinter as ctk
from deduplication.normalization import normalize_name

import journal
import store

COLUMNS = [("date", "Date et heure", 150), ("action", "Action", 200), ("detail", "Détail", 600)]


class JournalWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Journal des actions")
        self.geometry("1000x520")
        self.minsize(760, 360)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.rows: list[tuple[str, str, str, str]] = []
        try:
            with closing(store.connect()) as conn:
                raw = journal.list_audit(conn)
        except sqlite3.Error as e:
            messagebox.showerror("Journal indisponible", str(e), parent=master)
            self.destroy()
            return
        for at, action, detail in raw:
            label = journal.ACTION_LABELS.get(action, action)
            self.rows.append(
                (journal.fmt_datetime(at), label, detail, normalize_name(f"{label} {detail}"))
            )
        self._style()

        ctk.CTkLabel(
            self,
            text="Toutes les actions effectuées sur la base, de la plus récente à la plus ancienne. "
                 "Le journal ne contient ni adresse email ni numéro de téléphone.",
            text_color="gray", wraplength=940, justify="left",
        ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.query = ctk.StringVar()
        self.query.trace_add("write", lambda *_: self._fill())
        ctk.CTkEntry(bar, textvariable=self.query, placeholder_text="Chercher dans le journal…").grid(
            row=0, column=0, sticky="ew", padx=(0, 10)
        )
        self.count = ctk.CTkLabel(bar, text="", text_color="gray")
        self.count.grid(row=0, column=1)

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS], show="headings")
        for key, label, width in COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self._fill()

    def _style(self):
        dark = ctk.get_appearance_mode() == "Dark"
        bg, fg = ("#2b2b2b", "#e6e6e6") if dark else ("#ffffff", "#1a1a1a")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", background=bg, fieldbackground=bg, foreground=fg,
                        rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background="#3a3a3a" if dark else "#e8e8e8",
                        foreground=fg, relief="flat", font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#1f6aa5" if dark else "#3b8ed0")],
                  foreground=[("selected", "#ffffff")])

    def _fill(self):
        words = normalize_name(self.query.get()).split()
        shown = [r for r in self.rows if all(w in r[3] for w in words)]
        self.tree.delete(*self.tree.get_children())
        for date, label, detail, _ in shown:
            self.tree.insert("", "end", values=(date, label, detail))
        self.count.configure(text=f"{len(shown)} action(s)")