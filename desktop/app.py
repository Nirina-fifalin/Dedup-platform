import queue
import threading
from collections import Counter
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from deduplication import (
    ColumnMapping, DedupResult, NormalizedRecord, RecordNormalizer, apply_same, deduplicate,
)

from file_reader import guess_mapping, read_rows
from review_window import ReviewWindow

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Déduplication des inscriptions")
        self.geometry("560x480")
        self.minsize(480, 440)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._queue: queue.Queue = queue.Queue()
        self._path: Path | None = None
        self._review_win: ReviewWindow | None = None
        self.records: list[NormalizedRecord] | None = None
        self.result: DedupResult | None = None
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
        self.review_btn.pack(side="left")

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
        self.records, self.result, self.decisions = None, None, {}
        self._set_output("")

    def run(self):
        if self._path is None:
            return
        self.choose_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self.review_btn.configure(state="disabled")
        self._set_output("")
        self.progress.grid()
        self.progress.start()
        threading.Thread(target=self._work, args=(self._path,), daemon=True).start()
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

    # --- Travail en arrière-plan (la fenêtre reste réactive)
    def _work(self, path: Path):
        try:
            rows = read_rows(path)
            if not rows:
                raise ValueError("Le fichier est vide.")
            mapping = guess_mapping(rows[0].keys())
            missing = [f for f in ("nom", "prenom") if f not in mapping]
            if missing:
                raise ValueError(
                    "Colonnes introuvables : " + ", ".join(missing)
                    + "\n\nColonnes du fichier :\n" + ", ".join(map(str, rows[0].keys()))
                )
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
        pending = [(i, j) for i, j, _ in final.review if self.decisions.get((i, j)) != "different"]
        contradictions = [p for p in different if final.person_of[p[0]] == final.person_of[p[1]]]

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

    def _set_output(self, text: str):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()