import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from tkinter import messagebox, ttk

import customtkinter as ctk

import store
from dialogs import ask_typed_confirmation

BIG_REMOVAL = 10   # à partir de ce nombre d'inscriptions, il faut taper SUPPRIMER
COLUMNS = [
    ("id", "N°", 50), ("nom", "Fichier", 300), ("date", "Enregistré le", 120),
    ("regs", "Inscriptions", 100), ("gone", "Personnes supprimées avec lui", 210),
]


def _fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y")
    except ValueError:
        return iso[:10]


class FilesWindow(ctk.CTkToplevel):
    def __init__(self, master, on_change: Callable[[], None]):
        super().__init__(master)
        self.title("Fichiers importés")
        self.geometry("880x420")
        self.minsize(760, 340)
        self.transient(master)
        self.on_change = on_change
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text="Fichiers enregistrés dans la base", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=1, column=0, padx=16, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            frame, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse"
        )
        for key, label, width in COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=16, pady=14, sticky="ew")
        ctk.CTkButton(
            buttons, text="Supprimer ce fichier…", fg_color="#c62828", hover_color="#8e0000",
            command=self._delete,
        ).pack(side="left")
        ctk.CTkButton(
            buttons, text="Fermer", fg_color="gray40", hover_color="gray30", command=self.destroy
        ).pack(side="right")
        self._reload()

    def _reload(self):
        self.tree.delete(*self.tree.get_children())
        try:
            with closing(store.connect()) as conn:
                files = store.list_files(conn)
        except sqlite3.Error as e:
            messagebox.showerror("Base indisponible", str(e), parent=self)
            return
        for imported_at, p in files:
            self.tree.insert(
                "", "end",
                values=(p.file_id, p.filename, _fmt_date(imported_at), p.registrations, p.persons_deleted),
            )

    def _delete(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Supprimer", "Sélectionnez d'abord un fichier dans la liste.", parent=self)
            return
        file_id = int(str(self.tree.item(selected[0], "values")[0]))
        try:
            with closing(store.connect()) as conn:
                p = store.removal_preview(conn, file_id)
        except (LookupError, sqlite3.Error) as e:
            messagebox.showerror("Suppression impossible", str(e), parent=self)
            return

        message = (
            f"Supprimer le fichier « {p.filename} » ?\n\n"
            f"   • {p.registrations} inscription(s) supprimée(s)\n"
            f"   • {p.persons_deleted} personne(s) supprimée(s) : elles n'existent que par ce fichier\n"
            f"   • {p.persons_kept} personne(s) conservée(s) : elles ont d'autres inscriptions\n\n"
            "Une sauvegarde automatique est faite juste avant. Elle permet de revenir en arrière "
            "avec « Restaurer… » sur l'écran principal."
        )
        if p.registrations >= BIG_REMOVAL:
            confirmed = ask_typed_confirmation(self, "Supprimer un fichier", message, "SUPPRIMER")
        else:
            confirmed = messagebox.askyesno("Supprimer un fichier", message, parent=self)
        if not confirmed:
            return

        try:
            backup = store.auto_backup("avant-suppression")      # pas de sauvegarde = pas de suppression
            with closing(store.connect()) as conn:
                store.delete_file(conn, file_id)
        except Exception as e:
            messagebox.showerror("Suppression impossible", str(e), parent=self)
            return
        self._reload()
        self.on_change()
        messagebox.showinfo(
            "Fichier supprimé",
            f"« {p.filename} » a été supprimé.\n\n"
            f"Sauvegarde de l'état précédent : dossier « sauvegardes », fichier {backup.name}.",
            parent=self,
        )