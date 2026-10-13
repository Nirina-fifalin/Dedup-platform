import customtkinter as ctk


class ChoiceDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, message: str, choices: list[tuple[str, str]]):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result: str | None = None
        ctk.CTkLabel(self, text=message, justify="left", wraplength=480, anchor="w").pack(
            padx=24, pady=(22, 16), anchor="w"
        )
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(padx=24, pady=(0, 20), anchor="e")
        for value, label in choices:
            ctk.CTkButton(row, text=label, command=lambda v=value: self._pick(v)).pack(
                side="left", padx=4
            )
        self.geometry(f"+{master.winfo_rootx() + 90}+{master.winfo_rooty() + 120}")
        self.after(100, self.grab_set)

    def _pick(self, value: str):
        self.result = value
        self.destroy()


def ask_choice(master, title: str, message: str, choices: list[tuple[str, str]]) -> str | None:
    dialog = ChoiceDialog(master, title, message, choices)
    master.wait_window(dialog)
    return dialog.result


class TypedConfirmDialog(ctk.CTkToplevel):
    """Confirmation forte : le bouton ne s'active que si on a tapé le mot demandé."""

    def __init__(self, master, title: str, message: str, word: str, button: str):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.confirmed = False
        self._word = word.casefold()
        ctk.CTkLabel(self, text=message, justify="left", wraplength=480, anchor="w").pack(
            padx=24, pady=(22, 12), anchor="w"
        )
        ctk.CTkLabel(self, text=f"Pour confirmer, tapez le mot {word} :", anchor="w").pack(
            padx=24, anchor="w"
        )
        self._var = ctk.StringVar()
        self._var.trace_add("write", lambda *_: self._check())
        self._entry = ctk.CTkEntry(self, textvariable=self._var, width=220)
        self._entry.pack(padx=24, pady=(6, 14), anchor="w")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(padx=24, pady=(0, 20), anchor="e")
        ctk.CTkButton(
            row, text="Annuler", fg_color="gray40", hover_color="gray30", command=self.destroy
        ).pack(side="left", padx=4)
        self._ok = ctk.CTkButton(
            row, text=button, fg_color="#c62828", hover_color="#8e0000",
            state="disabled", command=self._confirm,
        )
        self._ok.pack(side="left", padx=4)
        self.geometry(f"+{master.winfo_rootx() + 90}+{master.winfo_rooty() + 120}")
        self.after(100, self.grab_set)
        self.after(150, self._entry.focus)

    def _check(self):
        typed = self._var.get().strip().casefold() == self._word
        self._ok.configure(state="normal" if typed else "disabled")

    def _confirm(self):
        self.confirmed = True
        self.destroy()


def ask_typed_confirmation(
    master, title: str, message: str, word: str = "SUPPRIMER", button: str = "Supprimer"
) -> bool:
    dialog = TypedConfirmDialog(master, title, message, word, button)
    master.wait_window(dialog)
    return dialog.confirmed