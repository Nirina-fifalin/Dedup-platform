import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from deduplication.normalization import normalize_name
from openpyxl import Workbook

import store
from dialogs import ask_choice
from files_window import FilesWindow

import journal
import person_edit
from edit_person_window import EditPersonWindow

MAX_SHOWN = 5000
OPT_OUT = store.OPT_OUT
OUTLINE = {"fg_color": "transparent", "border_width": 1, "text_color": ("gray10", "gray90")}
COLUMNS = [
    ("id", "N°", 55), ("nom", "Nom", 150), ("prenom", "Prénom", 170), ("sexe", "Sexe", 50),
    ("emails", "Emails", 250), ("telephones", "Téléphones", 170), ("nb", "Inscriptions", 90),
    ("contact", "Contact", 130),
]
DETAIL_COLUMNS = [
    ("formation", "Formation", 320), ("fichier", "Fichier d'origine", 220),
    ("email", "Email saisi", 240), ("tel", "Téléphone saisi", 150),
]
FILTERS = {"Tout le monde": None, "Contactables": "ok", "Ne pas contacter": OPT_OUT}
REASONS = {"desabonnement": "désabonnement", "demande": "demande de la personne", "autre": "autre motif"}
_PHONE_QUERY = re.compile(r"[\d\s+().-]+")
HINT = "Sélectionnez une personne pour voir son historique ou modifier son contact."


def _fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y")
    except ValueError:
        return iso[:10]


def _phone_forms(phone: str) -> str:
    """Un numéro peut être cherché en format international ou local (034...)."""
    digits = re.sub(r"\D", "", phone)
    local = "0" + digits[3:] if digits.startswith("261") else digits
    return f"{digits} {local}"


def _index(row: tuple) -> tuple[str, str]:
    """(texte pour chercher un nom ou un email, chiffres pour chercher un téléphone)."""
    _id, nom, prenom, _sexe, emails, phones, _nb, _status = row
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
    def __init__(self, master, on_change: Callable[[], None] | None = None):
        super().__init__(master)
        self.title("Base des personnes")
        self.geometry("1100x700")
        self.minsize(1080, 560)
        self.transient(master)
        self.on_change = on_change
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=3)
        self.grid_rowconfigure(3, weight=1)

        self.rows: list[tuple] = []
        self.search_index: dict[int, tuple[str, str]] = {}
        self.matching: list[tuple] = []
        self.sort_key = "id"
        self.sort_desc = False
        self.selected: int | None = None
        self.selected_status = "ok"

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
        self.filter_var = ctk.StringVar(value="Tout le monde")
        ctk.CTkOptionMenu(
            bar, values=list(FILTERS), variable=self.filter_var, width=160,
            command=lambda _v: self._apply(),
        ).grid(row=0, column=1, padx=(0, 10))
        self.count = ctk.CTkLabel(bar, text="", text_color="gray")
        self.count.grid(row=0, column=2, padx=(0, 10))
        ctk.CTkButton(
            bar, text="Fichiers importés…", width=150, command=self._open_files, **OUTLINE
        ).grid(row=0, column=3, padx=(0, 10))
        ctk.CTkButton(bar, text="Exporter la liste…", width=140, command=self._export).grid(
            row=0, column=4
        )

        self.tree = self._table(1, COLUMNS, sortable=True, height=14)
        self.tree.tag_configure("optout", foreground="#c62828")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        ctk.CTkLabel(
            self, text="Formations suivies par la personne sélectionnée",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=2, column=0, padx=16, pady=(12, 4), sticky="w")
        self.detail = self._table(3, DETAIL_COLUMNS, sortable=False, height=5)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=4, column=0, padx=16, pady=(0, 14), sticky="ew")
        self.info = ctk.CTkLabel(actions, text=HINT, text_color="gray", anchor="w")
        self.info.pack(side="left")
        self.delete_btn = ctk.CTkButton(
            actions, text="Supprimer cette personne…", fg_color="#c62828", hover_color="#8e0000",
            state="disabled", command=self._delete_person,
        )
        self.delete_btn.pack(side="right")
        self.optout_btn = ctk.CTkButton(
            actions, text="Ne plus contacter", state="disabled", command=self._toggle_contact,
            **OUTLINE,
        )
        self.optout_btn.pack(side="right", padx=(0, 8))
        self.edit_btn = ctk.CTkButton(
            actions, text="Modifier la fiche…", state="disabled", command=self._edit_person, **OUTLINE
        )
        self.edit_btn.pack(side="right", padx=(0, 8))
        self.history_btn = ctk.CTkButton(
            actions, text="Historique…", state="disabled", command=self._show_history, **OUTLINE
        )
        self.history_btn.pack(side="right", padx=(0, 8))

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
        wanted = FILTERS[self.filter_var.get()]
        self.matching = [
            r for r in self.rows
            if (wanted is None or r[7] == wanted) and _matches(q, *self.search_index[r[0]])
        ]
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
            opted_out = r[7] == OPT_OUT
            self.tree.insert(
                "", "end", values=(*r[:7], "NE PAS CONTACTER" if opted_out else ""),
                tags=("optout",) if opted_out else (),
            )
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
        self._set_selected(None)

    def _data_changed(self, keep: int | None = None):
        if self._load():
            self._apply()
            if keep is not None:
                self._reselect(keep)
        if self.on_change:
            self.on_change()

    def _reselect(self, person_id: int):
        for item in self.tree.get_children():
            if int(str(self.tree.item(item, "values")[0])) == person_id:
                self.tree.selection_set(item)
                self.tree.see(item)
                return

    # --- Sélection
    def _set_selected(self, person_id: int | None, status: str = "ok",
                      at: str | None = None, note: str | None = None):
        self.selected, self.selected_status = person_id, status
        if person_id is None:
            self.info.configure(text=HINT, text_color="gray")
            self.optout_btn.configure(state="disabled", text="Ne plus contacter")
            self.delete_btn.configure(state="disabled")
            self.edit_btn.configure(state="disabled")
            self.history_btn.configure(state="disabled")
            return
        if status == OPT_OUT:
            since = f" depuis le {_fmt_date(at)}" if at else ""
            reason = f" — {note}" if note else ""
            self.info.configure(
                text=f"Personne n° {person_id} : NE PAS CONTACTER{since}{reason}",
                text_color="#c62828",
            )
            self.optout_btn.configure(state="normal", text="Autoriser à nouveau le contact")
        else:
            self.info.configure(text=f"Personne n° {person_id} : contactable", text_color="gray")
            self.optout_btn.configure(state="normal", text="Ne plus contacter")
        self.delete_btn.configure(state="normal")
        self.edit_btn.configure(state="normal")
        self.history_btn.configure(state="normal")

    def _on_select(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        person_id = int(str(self.tree.item(selected[0], "values")[0]))
        try:
            with closing(store.connect()) as conn:
                registrations = store.person_registrations(conn, person_id)
                status, at, note = store.contact_info(conn, person_id)
        except (LookupError, sqlite3.Error):
            registrations, status, at, note = [], "ok", None, None
        self.detail.delete(*self.detail.get_children())
        for r in registrations:
            self.detail.insert("", "end", values=r)
        self._set_selected(person_id, status, at, note)

    # --- Actions sur une personne
    def _toggle_contact(self):
        person_id = self.selected
        if person_id is None:
            return
        if self.selected_status == OPT_OUT:
            if not messagebox.askyesno(
                "Autoriser le contact",
                "Autoriser à nouveau le contact avec cette personne ?\n\n"
                "Ne le faites que si elle l'a demandé.",
                parent=self,
            ):
                return
            do_not_contact, note = False, None
        else:
            choice = ask_choice(
                self, "Ne plus contacter",
                "Pourquoi cette personne ne doit-elle plus être contactée ?",
                [("desabonnement", "Désabonnement"), ("demande", "Demande de la personne"),
                 ("autre", "Autre motif"), ("cancel", "Annuler")],
            )
            if choice not in REASONS:
                return
            do_not_contact, note = True, REASONS[choice]
        try:
            with closing(store.connect()) as conn:
                store.set_contact_status(conn, person_id, do_not_contact, note)
        except (LookupError, sqlite3.Error) as e:
            messagebox.showerror("Modification impossible", str(e), parent=self)
            return
        self._data_changed(keep=person_id)

    def _delete_person(self):
        person_id = self.selected
        row = next((r for r in self.rows if r[0] == person_id), None)
        if person_id is None or row is None:
            return
        message = (
            f"Supprimer {row[1]} {row[2]} (n° {person_id}) et ses {row[6]} inscription(s) ?\n\n"
            "Ses données sont effacées de la base. Une sauvegarde automatique est faite avant : "
            "« Restaurer… » sur l'écran principal permet de revenir en arrière."
        )
        if row[7] == OPT_OUT:
            message += ("\n\nSes adresses email restent dans la liste d'opposition, "
                        "pour ne pas la recontacter.")
        if not messagebox.askyesno("Supprimer une personne", message, parent=self):
            return
        try:
            backup = store.auto_backup("avant-suppression-personne")   # pas de sauvegarde = pas de suppression
            with closing(store.connect()) as conn:
                store.delete_person(conn, person_id)
        except Exception as e:
            messagebox.showerror("Suppression impossible", str(e), parent=self)
            return
        self._data_changed()
        messagebox.showinfo(
            "Personne supprimée",
            f"La personne n° {person_id} a été supprimée.\n\nSauvegarde de l'état précédent : "
            f"dossier « sauvegardes », fichier {backup.name}.",
            parent=self,
        )
    def _edit_person(self):
        if self.selected is None:
            return
        EditPersonWindow(self, self.selected, on_saved=lambda pid: self._data_changed(keep=pid))

    def _show_history(self):
        if self.selected is None:
            return
        try:
            with closing(store.connect()) as conn:
                history = person_edit.edit_history(conn, self.selected)
        except sqlite3.Error as e:
            messagebox.showerror("Historique indisponible", str(e), parent=self)
            return
        if not history:
            messagebox.showinfo(
                "Historique", "Aucune modification n'a été faite sur cette fiche.", parent=self
            )
            return
        lines = [
            f"{journal.fmt_datetime(at)} — {field} : « {old} » → « {new} »"
            for at, field, old, new in history[:15]
        ]
        if len(history) > 15:
            lines.append(f"… et {len(history) - 15} autre(s)")
        journal.record_action("export_liste", f"{len(self.matching)} personnes exportées")
        messagebox.showinfo(f"Historique de la fiche n° {self.selected}", "\n".join(lines), parent=self)

    # --- Autres fenêtres et export
    def _open_files(self):
        FilesWindow(self, on_change=self._data_changed)

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
        ws.append(["id_personne", "nom", "prenom", "sexe", "emails", "telephones",
                   "nb_inscriptions", "statut_contact"])
        for r in self.matching:
            values = [*r[:7], "ne pas contacter" if r[7] == OPT_OUT else "contactable"]
            # une valeur commençant par "=" serait exécutée comme une formule par Excel
            ws.append([("'" + v) if isinstance(v, str) and v.startswith("=") else v for v in values])
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