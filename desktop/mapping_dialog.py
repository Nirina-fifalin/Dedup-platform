from collections.abc import Callable, Mapping

import customtkinter as ctk

FIELDS = [
    ("nom", "Nom de famille", True),
    ("prenom", "Prénom", True),
    ("email", "Email", False),
    ("telephone", "Téléphone", False),
    ("sexe", "Sexe / genre", False),
    ("formation", "Formation (nom)", False),
]
NONE = "(aucune)"


class MappingDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        headers: list[str],
        initial: dict[str, str],
        sample: Mapping,
        on_confirm: Callable[[dict[str, str]], None],
    ):
        super().__init__(master)
        self.title("Colonnes du fichier")
        self.geometry("700x470")
        self.resizable(False, False)
        self.transient(master)
        self.on_confirm = on_confirm
        self.sample = sample
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text="Quelle colonne correspond à quoi ?",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=20, pady=(16, 4), sticky="w")
        ctk.CTkLabel(
            self, text="Compare avec l'exemple de la 1re ligne : « Name » peut être le nom "
                       "ou le prénom selon le formulaire.",
            text_color="gray", wraplength=650, justify="left",
        ).grid(row=1, column=0, columnspan=3, padx=20, pady=(0, 10), sticky="w")

        options = [NONE, *dict.fromkeys(h for h in headers if h.strip())]
        self.vars: dict[str, ctk.StringVar] = {}
        self.examples: dict[str, ctk.CTkLabel] = {}
        for row, (key, label, required) in enumerate(FIELDS, start=2):
            ctk.CTkLabel(self, text=label + (" *" if required else "")).grid(
                row=row, column=0, padx=(20, 10), pady=6, sticky="w"
            )
            value = initial.get(key, NONE)
            var = ctk.StringVar(value=value if value in options else NONE)
            self.vars[key] = var
            ctk.CTkOptionMenu(
                self, values=options, variable=var, width=280,
                command=lambda _v: self._validate(),
            ).grid(row=row, column=1, padx=(0, 10), pady=6, sticky="ew")
            example = ctk.CTkLabel(self, text="", text_color="gray", anchor="w", width=190)
            example.grid(row=row, column=2, padx=(0, 20), sticky="w")
            self.examples[key] = example

        self.hint = ctk.CTkLabel(self, text="", text_color="#c2570c")
        self.hint.grid(row=9, column=0, columnspan=3, padx=20, pady=(10, 0), sticky="w")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=10, column=0, columnspan=3, pady=16)
        self.ok = ctk.CTkButton(buttons, text="Analyser", command=self._confirm)
        self.ok.pack(side="left", padx=5)
        ctk.CTkButton(
            buttons, text="Inverser nom ↔ prénom", fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), command=self._swap,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            buttons, text="Annuler", fg_color="gray40", hover_color="gray30",
            command=self.destroy,
        ).pack(side="left", padx=5)

        self._validate()
        self.after(100, self.grab_set)

    def _chosen(self) -> dict[str, str]:
        return {k: v.get() for k, v in self.vars.items() if v.get() != NONE}

    def _swap(self):
        nom, prenom = self.vars["nom"], self.vars["prenom"]
        a, b = nom.get(), prenom.get()
        nom.set(b)
        prenom.set(a)
        self._validate()

    def _refresh_examples(self):
        for key, var in self.vars.items():
            value = self.sample.get(var.get()) if var.get() != NONE else None
            text = str(value).strip() if value is not None else ""
            self.examples[key].configure(text=f"ex. : {text[:28]}" if text else "")

    def _validate(self):
        chosen = self._chosen()
        problem = ""
        if "nom" not in chosen or "prenom" not in chosen:
            problem = "Le nom et le prénom sont obligatoires."
        elif len(set(chosen.values())) < len(chosen):
            problem = "Une même colonne ne peut servir qu'à un seul champ."
        self.hint.configure(text=problem)
        self.ok.configure(state="disabled" if problem else "normal")
        self._refresh_examples()

    def _confirm(self):
        mapping = self._chosen()
        self.destroy()
        self.on_confirm(mapping)