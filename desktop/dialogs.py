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