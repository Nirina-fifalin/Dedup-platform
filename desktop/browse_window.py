import re
import sqlite3
from contextlib import closing
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from deduplication.normalization import normalize_name
from openpyxl import Workbook

import store

MAX_SHOWN = 5000
COLUMNS = [
    ("id", "N°", 60), ("nom", "Nom", 160), ("prenom", "Prénom", 180), ("sexe", "Sexe", 55),
    ("emails", "Emails", 270), ("telephones", "Téléphones", 180), ("nb", "Inscriptions", 95),
]
DETAIL_COLUMNS = [
    ("formation", "Formation", 320), ("fichier", "Fichier d'origine", 220),
    ("email", "Email saisi", 240), ("tel", "Téléphone saisi", 150),
]
_PHONE_QUERY = re.compile(r"[\d\s+().-]+")


def _phone_forms(phone: str) -> str:
    """Un numéro peut être cherché en format international ou local (034...)."""
    digits = re.sub(r"\D", "", phone)
    local = "0" + digits[3:] if digits.startswith("261") else digits
    return f"{digits} {local}"


def _index(row: tuple) -> tuple[str, str]:
    """(texte pour chercher un nom ou un email, chiffres pour chercher un téléphone)."""
    _id, nom, prenom, _sexe, emails, phones, _nb = row
    text = normalize_name(f"{nom} {prenom} {emails}")
    digits = " ".join(_phone_forms(p) for p in phones.split(" | ") if p)
    return text, digits


def _matches(query: str, text: str, digits: str) -> bool:
    q = query.strip()
    if not q:
        return True
    if _PHONE_QUERY.fullmatch(q):
        wanted = re.sub(r"\D", "", q)
        return bool(wanted) and wanted in digits
    return all(token in text for token in normalize_name(q).split())


class BrowseWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Base des personnes")
        self.geometry("1020x660")
        self.minsize(860, 540)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=3)
        self.grid_rowconfigure(3, weight=1)

        self.rows: list[tuple] = []
        self.search_index: dict[int, tuple[str, str]] = {}
        self.matching: list[tuple] = []
        self.sort_key = "id"
        self.sort_desc = False

        if not self._load():
            self.destroy()
            return
        self._style()

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.query = ctk.StringVar()
        self.query.trace_add("write", lambda *_: self._apply())
        entry = ctk.CTkEntry(
            bar, textvariable=self.query,
            placeholder_text="Chercher un nom, un email ou un numéro de téléphone…",
        )
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.count = ctk.CTkLabel(bar, text="", text_color="gray")
        self.count.grid(row=0, column=1, padx=(0, 10))
        ctk.CTkButton(bar, text="Exporter la liste…", width=140, command=self._export).grid(
            row=0, column=2
        )

        self.tree = self._table(1, COLUMNS, sortable=True, height=14)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        ctk.CTkLabel(
            self, text="Formations suivies par la personne sélectionnée",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=2, column=0, padx=16, pady=(12, 4), sticky="w")
        self.detail = self._table(3, DETAIL_COLUMNS, sortable=False, height=5)

        entry.focus()
        self._apply()

    # --- Construction
    def _table(self, row: int, columns, sortable: bool, height: int) -> ttk.Treeview:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=0, padx=16, pady=(0, 8), sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            frame, columns=[c[0] for c in columns], show="headings",
            selectmode="browse", height=height,
        )
        for key, label, width in columns:
            if sortable:
                tree.heading(key, text=label, command=lambda k=key: self._sort(k))
            else:
                tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return tree

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

    # --- Données
    def _load(self) -> bool:
        try:
            with closing(store.connect()) as conn:
                self.rows = store.list_persons(conn)
        except sqlite3.Error as e:
            messagebox.showerror("Base indisponible", str(e), parent=self)
            return False
        self.search_index = {r[0]: _index(r) for r in self.rows}
        return True

    def _apply(self):
        q = self.query.get()
        self.matching = [r for r in self.rows if _matches(q, *self.search_index[r[0]])]
        self._sort_rows()
        self._fill()

    def _sort_rows(self):
        idx = [c[0] for c in COLUMNS].index(self.sort_key)
        numeric = self.sort_key in ("id", "nb")
        self.matching.sort(
            key=lambda r: r[idx] if numeric else normalize_name(str(r[idx])),
            reverse=self.sort_desc,
        )

    def _sort(self, key: str):
        self.sort_desc = (not self.sort_desc) if key == self.sort_key else False
        self.sort_key = key
        self._sort_rows()
        self._fill()

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.matching[:MAX_SHOWN]:
            self.tree.insert("", "end", values=r)
        for key, label, _ in COLUMNS:
            arrow = (" ▼" if self.sort_desc else " ▲") if key == self.sort_key else ""
            self.tree.heading(key, text=label + arrow)
        if not self.rows:
            text = "La base est vide : analyse puis enregistre un fichier d'abord."
        elif len(self.matching) > MAX_SHOWN:
            text = f"{len(self.matching)} personnes ({MAX_SHOWN} affichées : précise la recherche)"
        else:
            text = f"{len(self.matching)} personne(s)"
        self.count.configure(text=text)
        self.detail.delete(*self.detail.get_children())

    def _on_select(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        person_id = int(str(self.tree.item(selected[0], "values")[0]))
        try:
            with closing(store.connect()) as conn:
                registrations = store.person_registrations(conn, person_id)
        except sqlite3.Error:
            registrations = []
        self.detail.delete(*self.detail.get_children())
        for r in registrations:
            self.detail.insert("", "end", values=r)

    # --- Export
    def _export(self):
        if not self.matching:
            messagebox.showinfo("Export", "Il n'y a rien à exporter.", parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self, title="Enregistrer la liste", defaultextension=".xlsx",
            initialfile="personnes.xlsx", filetypes=[("Excel", "*.xlsx")],
        )
        if not target:
            return
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("personnes")
        ws.append(["id_personne", "nom", "prenom", "sexe", "emails", "telephones", "nb_inscriptions"])
        for r in self.matching:
            # une valeur commençant par "=" serait exécutée comme une formule par Excel
            ws.append([("'" + v) if isinstance(v, str) and v.startswith("=") else v for v in r])
        try:
            wb.save(target)
        except PermissionError:
            messagebox.showerror(
                "Export impossible",
                "Le fichier est ouvert dans Excel ou protégé en écriture.\n"
                "Ferme-le, ou choisis un autre nom.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Export terminé", f"{len(self.matching)} personnes exportées :\n{target}", parent=self
        )