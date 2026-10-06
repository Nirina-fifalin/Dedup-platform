import queue
import threading
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from deduplication import (
    ColumnMapping, DedupResult, MatchResult, NormalizedRecord, RecordNormalizer,
    apply_same, deduplicate,
)

from exporter import export_workbook
from file_reader import guess_mapping, load_saved_mapping, read_headers, read_rows, save_mapping
from mapping_dialog import MappingDialog
from review_window import ReviewWindow

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Déduplication des inscriptions")
        self.geometry("560x500")
        self.minsize(480, 460)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._queue: queue.Queue = queue.Queue()
        self._path: Path | None = None
        self._review_win: ReviewWindow | None = None
        self.records: list[NormalizedRecord] | None = None
        self.result: DedupResult | None = None
        self.final: DedupResult | None = None
        self.pending_cases: list[tuple[int, int, MatchResult]] = []
        self.mapping: dict[str, str] = {}
        self.decisions: dict[tuple[int, int], str] = {}   # (i, j) -> "same" | "different"

        ctk.CTkLabel(
            self, text="Déduplication des inscriptions",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        self.file_label = ctk.CTkLabel(self, text="Aucun fichier choisi", anchor="w")
        self.file_label.grid(row=1, column=0, padx=20, sticky="ew")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=20, pady=10, sticky="w")
        self.choose_btn = ctk.CTkButton(buttons, text="Choisir un fichier…", command=self.choose_file)
        self.choose_btn.pack(side="left", padx=(0, 10))
        self.run_btn = ctk.CTkButton(buttons, text="Analyser", command=self.run, state="disabled")
        self.run_btn.pack(side="left", padx=(0, 10))
        self.review_btn = ctk.CTkButton(
            buttons, text="Vérifier les paires", command=self.open_review, state="disabled"
        )
        self.review_btn.pack(side="left", padx=(0, 10))
        self.export_btn = ctk.CTkButton(
            buttons, text="Exporter…", command=self.export, state="disabled",
            fg_color="#2e7d32", hover_color="#1b5e20",
        )
        self.export_btn.pack(side="left")

        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress.grid(row=3, column=0, padx=20, sticky="ew")
        self.progress.grid_remove()

        self.output = ctk.CTkTextbox(
            self, state="disabled", font=ctk.CTkFont(family="Consolas", size=13)
        )
        self.output.grid(row=4, column=0, padx=20, pady=(10, 20), sticky="nsew")

    # --- Actions
    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Choisir un fichier d'inscriptions",
            filetypes=[("Excel ou CSV", "*.xlsx *.csv")],
        )
        if not path:
            return
        self._path = Path(path)
        self.file_label.configure(text=self._path.name)
        self.run_btn.configure(state="normal")
        self.review_btn.configure(text="Vérifier les paires", state="disabled")
        self.export_btn.configure(state="disabled")
        self.records, self.result, self.final, self.decisions = None, None, None, {}
        self.pending_cases = []
        self._set_output("")

    def run(self):
        if self._path is None:
            return
        try:
            headers = read_headers(self._path)
        except Exception as e:
            self._set_output("⚠ " + str(e))
            return
        initial = load_saved_mapping(headers) or guess_mapping(headers)
        MappingDialog(self, headers, initial, on_confirm=lambda m: self._start(headers, m))

    def _start(self, headers: list[str], mapping: dict[str, str]):
        if self._path is None:
            return
        save_mapping(headers, mapping)
        self.choose_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self.review_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self._set_output("")
        self.progress.grid()
        self.progress.start()
        threading.Thread(target=self._work, args=(self._path, mapping), daemon=True).start()
        self.after(100, self._poll)

    def open_review(self):
        if self.records is None or self.result is None or not self.result.review:
            return
        if self._review_win is not None and self._review_win.winfo_exists():
            self._review_win.lift()
            return
        self._review_win = ReviewWindow(
            self, self.records, self.result.review, self.mapping, self.decisions,
            on_close=self._refresh,
        )

    def export(self):
        if self.records is None or self.final is None or self._path is None:
            return
        target = filedialog.asksaveasfilename(
            title="Enregistrer le fichier nettoyé", defaultextension=".xlsx",
            initialfile=f"{self._path.stem}_nettoye.xlsx", filetypes=[("Excel", "*.xlsx")],
        )
        if not target:
            return
        try:
            export_workbook(target, self.records, self.final, self.pending_cases, self.mapping)
        except PermissionError:
            messagebox.showerror(
                "Export impossible",
                "Le fichier est ouvert dans Excel ou protégé en écriture.\n"
                "Ferme-le, ou choisis un autre nom.",
            )
            return
        except Exception as e:
            messagebox.showerror("Export impossible", str(e))
            return
        messagebox.showinfo("Export terminé", f"Fichier enregistré :\n{target}")

    # --- Travail en arrière-plan (la fenêtre reste réactive)
    def _work(self, path: Path, mapping: dict[str, str]):
        try:
            rows = read_rows(path)
            if not rows:
                raise ValueError("Le fichier est vide.")
            records = list(RecordNormalizer(ColumnMapping(columns=mapping)).normalize_rows(rows))
            self._queue.put(("ok", records, deduplicate(records), mapping))
        except Exception as e:
            self._queue.put(("error", str(e)))

    def _poll(self):
        try:
            msg = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return
        self.progress.stop()
        self.progress.grid_remove()
        self.choose_btn.configure(state="normal")
        self.run_btn.configure(state="normal")
        if msg[0] == "ok":
            self.records, self.result, self.mapping = msg[1], msg[2], msg[3]
            self.decisions = {}
            self._refresh()
        else:
            self._set_output("⚠ " + msg[1])

    # --- Affichage
    def _refresh(self):
        records, result = self.records, self.result
        if records is None or result is None:
            return

        same = [p for p, d in self.decisions.items() if d == "same"]
        different = [p for p, d in self.decisions.items() if d == "different"]
        final = apply_same(result, same)
        pending = [
            (i, j, res) for i, j, res in final.review
            if self.decisions.get((i, j)) != "different"
        ]
        contradictions = [p for p in different if final.person_of[p[0]] == final.person_of[p[1]]]
        self.final, self.pending_cases = final, pending

        persons = len(final.clusters)
        no_name = sum(1 for r in records if any(i.code == "name_missing" for i in r.issues))
        issues = Counter(i.code for r in records for i in r.issues if i.code != "name_missing")

        lines = [
            f"Lignes lues              {len(records):>6}",
            f"Personnes uniques        {persons:>6}",
            f"Doublons regroupés       {len(records) - persons:>6}",
            f"Paires en attente        {len(pending):>6}",
            f"  confirmées identiques  {len(same):>6}",
            f"  confirmées différentes {len(different):>6}",
            f"Lignes sans nom/prénom   {no_name:>6}",
        ]
        if contradictions:
            lines += ["", f"⚠ {len(contradictions)} décision(s) « différentes » contredite(s) "
                          "par d'autres confirmations."]
        if issues:
            lines += ["", "Problèmes de données :"]
            lines += [f"  {code} : {n}" for code, n in issues.most_common()]
        self._set_output("\n".join(lines))

        self.review_btn.configure(
            text=f"Vérifier les paires ({len(pending)} en attente)",
            state="normal" if result.review else "disabled",
        )
        self.export_btn.configure(state="normal")

    def _set_output(self, text: str):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()