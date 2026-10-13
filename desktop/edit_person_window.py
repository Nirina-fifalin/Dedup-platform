import sqlite3
from collections.abc import Callable
from contextlib import closing
from tkinter import messagebox

import customtkinter as ctk
from deduplication.normalization import normalize_email, split_emails

import person_edit
import store

SEXES = ["", "F", "M"]


class EditPersonWindow(ctk.CTkToplevel):
    def __init__(self, master, person_id: int, on_saved: Callable[[int], None]):
        super().__init__(master)
        self.title("Modifier la fiche")
        self.geometry("580x700")
        self.resizable(False, False)
        self.transient(master)
        self._owner = master
        self.person_id = person_id
        self.on_saved = on_saved
        try:
            with closing(store.connect()) as conn:
                d = person_edit.person_details(conn, person_id)
                self._shared_before = person_edit.shared_contacts(conn, person_id)
        except (LookupError, sqlite3.Error) as e:
            messagebox.showerror("Fiche introuvable", str(e), parent=master)
            self.destroy()
            return
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text=f"Fiche n° {person_id}", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        ctk.CTkLabel(self, text="Nom").grid(row=1, column=0, padx=(20, 10), pady=6, sticky="w")
        self.nom = ctk.CTkEntry(self)
        self.nom.insert(0, d.nom)
        self.nom.grid(row=1, column=1, padx=(0, 20), pady=6, sticky="ew")

        ctk.CTkLabel(self, text="Prénom").grid(row=2, column=0, padx=(20, 10), pady=6, sticky="w")
        self.prenom = ctk.CTkEntry(self)
        self.prenom.insert(0, d.prenom)
        self.prenom.grid(row=2, column=1, padx=(0, 20), pady=6, sticky="ew")

        ctk.CTkLabel(self, text="Sexe").grid(row=3, column=0, padx=(20, 10), pady=6, sticky="w")
        sexes = SEXES if (not d.sexe or d.sexe in SEXES) else [*SEXES, d.sexe]
        self.sexe = ctk.StringVar(value=d.sexe or "")
        ctk.CTkOptionMenu(self, values=sexes, variable=self.sexe, width=120).grid(
            row=3, column=1, padx=(0, 20), pady=6, sticky="w"
        )

        ctk.CTkLabel(self, text="Emails\n(un par ligne,\nle 1er est le\nprincipal)", justify="left").grid(
            row=4, column=0, padx=(20, 10), pady=6, sticky="nw"
        )
        self.emails_box = ctk.CTkTextbox(self, height=110)
        self.emails_box.insert("1.0", "\n".join(d.emails))
        self.emails_box.grid(row=4, column=1, padx=(0, 20), pady=6, sticky="ew")
        ctk.CTkButton(
            self, text="Corriger les fautes évidentes des domaines (gamil → gmail…)",
            command=self._fix_domains, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
        ).grid(row=5, column=1, padx=(0, 20), pady=(0, 6), sticky="w")

        ctk.CTkLabel(self, text="Téléphones\n(un par ligne)", justify="left").grid(
            row=6, column=0, padx=(20, 10), pady=6, sticky="nw"
        )
        self.phones_box = ctk.CTkTextbox(self, height=110)
        self.phones_box.insert("1.0", "\n".join(d.phones))
        self.phones_box.grid(row=6, column=1, padx=(0, 20), pady=6, sticky="ew")

        ctk.CTkLabel(
            self, text="Les inscriptions gardent ce qui a été saisi à l'origine : "
                       "seule la fiche de la personne est corrigée.",
            text_color="gray", wraplength=520, justify="left",
        ).grid(row=7, column=0, columnspan=2, padx=20, pady=(8, 0), sticky="w")

        self.hint = ctk.CTkLabel(self, text="", wraplength=520, justify="left", anchor="w")
        self.hint.grid(row=8, column=0, columnspan=2, padx=20, pady=(8, 0), sticky="w")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=9, column=0, columnspan=2, pady=16)
        ctk.CTkButton(buttons, text="Enregistrer", command=self._save).pack(side="left", padx=5)
        ctk.CTkButton(
            buttons, text="Annuler", fg_color="gray40", hover_color="gray30", command=self.destroy
        ).pack(side="left", padx=5)
        self.after(100, self.grab_set)

    def _hint(self, text: str, error: bool = False):
        self.hint.configure(text=text, text_color="#c62828" if error else "#c2570c")

    def _fix_domains(self):
        lines: list[str] = []
        fixed = 0
        for part in split_emails(self.emails_box.get("1.0", "end")):
            e = normalize_email(part)
            if e.is_valid and e.local and e.suspected_domain:
                lines.append(f"{e.local}@{e.suspected_domain}")
                fixed += 1
            else:
                lines.append(part)
        self.emails_box.delete("1.0", "end")
        self.emails_box.insert("1.0", "\n".join(lines))
        self._hint(
            f"{fixed} adresse(s) corrigée(s) : vérifiez avant d'enregistrer." if fixed
            else "Aucune faute évidente trouvée."
        )

    def _save(self):
        parsed = person_edit.parse_contacts(
            self.emails_box.get("1.0", "end"), self.phones_box.get("1.0", "end")
        )
        if parsed.errors:
            self._hint("\n".join(parsed.errors) + "\nCorrigez ou supprimez ces lignes.", error=True)
            return
        if parsed.suspected:
            lines = "\n".join(f"   • {e} (proche de {d})" for e, d in parsed.suspected)
            if not messagebox.askyesno(
                "Adresses à vérifier",
                f"Ces adresses semblent contenir une faute :\n{lines}\n\nLes enregistrer quand même ?",
                parent=self,
            ):
                return
        try:
            with closing(store.connect()) as conn:
                changed = person_edit.update_person(
                    conn, self.person_id, self.nom.get(), self.prenom.get(), self.sexe.get(),
                    parsed.emails, parsed.phones,
                )
                shared_after = person_edit.shared_contacts(conn, self.person_id)
        except (ValueError, LookupError, sqlite3.Error) as e:
            self._hint(str(e), error=True)
            return

        new_shared = shared_after - self._shared_before
        owner = self._owner
        self.destroy()
        self.on_saved(self.person_id)
        if "contact" in changed:
            messagebox.showinfo(
                "Contact",
                "Une des adresses figure dans la liste d'opposition : la fiche a été "
                "marquée « ne pas contacter ».",
                parent=owner,
            )
        if new_shared:
            lines = "\n".join(
                f"   • {kind} {value} : fiche n° {pid} ({name})"
                for kind, value, pid, name in sorted(new_shared)
            )
            messagebox.showwarning(
                "Peut-être un doublon",
                f"Ces valeurs existent aussi sur une autre fiche :\n{lines}\n\n"
                "S'il s'agit de la même personne, supprimez la fiche en trop "
                "(la fusion de deux fiches n'existe pas encore). Un numéro partagé "
                "peut aussi être normal (famille).",
                parent=owner,
            )