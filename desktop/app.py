import queue
import sqlite3
import threading
from collections import Counter
from contextlib import closing
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from deduplication import (
    Classification, ColumnMapping, DedupResult, GroupMatch, KnownIndex, KnownPerson,
    MatchResult, NormalizedRecord, RecordNormalizer, apply_same, deduplicate, match_to_known,
)

import store
from exporter import export_workbook
from file_reader import guess_mapping, load_saved_mapping, read_rows, save_mapping
from mapping_dialog import MappingDialog
from review_window import ReviewWindow

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")


def _key(gm: GroupMatch) -> tuple[int, int] | None:
    """Clé stable d'une décision : (ligne du fichier, position de la personne connue)."""
    if gm.record_index is None or gm.known_index is None:
        return None
    return gm.record_index, gm.known_index


def _person_id(kp: KnownPerson) -> int:
    assert isinstance(kp.id, int)
    return kp.id


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Déduplication des inscriptions")
        self.geometry("660x600")
        self.minsize(620, 560)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)

        self._queue: queue.Queue = queue.Queue()
        self._path: Path | None = None
        self._review_win: ReviewWindow | None = None
        self._known_win: ReviewWindow | None = None
        self.records: list[NormalizedRecord] | None = None
        self.result: DedupResult | None = None
        self.final: DedupResult | None = None
        self.pending_cases: list[tuple[int, int, MatchResult]] = []
        self.mapping: dict[str, str] = {}
        self.decisions: dict[tuple[int, int], str] = {}        # paires DU FICHIER
        self.saved = False

        # Correspondances avec la base
        self.index: KnownIndex | None = None
        self.known_cache: dict[frozenset[int], GroupMatch] = {}
        self.matches: dict[int, GroupMatch] = {}
        self.known_pairs: list[tuple[int, int, MatchResult]] = []   # (ligne, ligne d'affichage, résultat)
        self.known_display: list[NormalizedRecord] = []
        self._display_known: dict[int, int] = {}                    # ligne d'affichage -> position connue
        self.known_decisions: dict[tuple[int, int], str] = {}       # (ligne, position connue) -> décision
        self.pending_known = 0

        ctk.CTkLabel(
            self, text="Déduplication des inscriptions",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        self.file_label = ctk.CTkLabel(self, text="Aucun fichier choisi", anchor="w")
        self.file_label.grid(row=1, column=0, padx=20, sticky="ew")

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=2, column=0, padx=20, pady=(10, 4), sticky="w")
        self.choose_btn = ctk.CTkButton(top, text="Choisir un fichier…", command=self.choose_file)
        self.choose_btn.pack(side="left", padx=(0, 10))
        self.run_btn = ctk.CTkButton(top, text="Analyser", command=self.run, state="disabled")
        self.run_btn.pack(side="left")

        checks = ctk.CTkFrame(self, fg_color="transparent")
        checks.grid(row=3, column=0, padx=20, pady=(0, 4), sticky="w")
        self.review_btn = ctk.CTkButton(
            checks, text="Paires du fichier", command=self.open_review, state="disabled"
        )
        self.review_btn.pack(side="left", padx=(0, 10))
        self.known_btn = ctk.CTkButton(
            checks, text="Correspondances avec la base", command=self.open_known_review,
            state="disabled",
        )
        self.known_btn.pack(side="left")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=4, column=0, padx=20, pady=(0, 6), sticky="w")
        self.export_btn = ctk.CTkButton(
            actions, text="Exporter…", command=self.export, state="disabled"
        )
        self.export_btn.pack(side="left", padx=(0, 10))
        self.save_btn = ctk.CTkButton(
            actions, text="Enregistrer dans la base", command=self.save_to_db, state="disabled",
            fg_color="#2e7d32", hover_color="#1b5e20",
        )
        self.save_btn.pack(side="left")

        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress.grid(row=5, column=0, padx=20, sticky="ew")
        self.progress.grid_remove()

        self.output = ctk.CTkTextbox(
            self, state="disabled", font=ctk.CTkFont(family="Consolas", size=13)
        )
        self.output.grid(row=6, column=0, padx=20, pady=(10, 6), sticky="nsew")

        self.db_label = ctk.CTkLabel(self, text="", text_color="gray", anchor="w")
        self.db_label.grid(row=7, column=0, padx=20, pady=(0, 14), sticky="ew")
        self._update_db_label()

    # --- Choix du fichier et analyse
    def _disable_all_actions(self):
        for b in (self.review_btn, self.known_btn, self.export_btn, self.save_btn):
            b.configure(state="disabled")

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
        self.review_btn.configure(text="Paires du fichier")
        self.known_btn.configure(text="Correspondances avec la base")
        self._disable_all_actions()
        self.records, self.result, self.final, self.index = None, None, None, None
        self.decisions, self.known_decisions, self.known_cache = {}, {}, {}
        self.pending_cases, self.known_pairs, self.matches = [], [], {}
        self.saved = False
        self._set_output("")

    def run(self):
        if self._path is None:
            return
        try:
            rows = read_rows(self._path)
            if not rows:
                raise ValueError("Le fichier est vide.")
        except Exception as e:
            self._set_output("⚠ " + str(e))
            return
        headers = [str(h) for h in rows[0].keys()]
        initial = load_saved_mapping(headers) or guess_mapping(headers)
        MappingDialog(
            self, headers, initial, rows[0],
            on_confirm=lambda m: self._start(rows, headers, m),
        )

    def _start(self, rows: list[dict], headers: list[str], mapping: dict[str, str]):
        save_mapping(headers, mapping)
        self.choose_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self._disable_all_actions()
        self._set_output("")
        self.progress.grid()
        self.progress.start()
        threading.Thread(target=self._work, args=(rows, mapping), daemon=True).start()
        self.after(100, self._poll)

    # --- Travail en arrière-plan (la fenêtre reste réactive)
    def _work(self, rows: list[dict], mapping: dict[str, str]):
        try:
            records = list(RecordNormalizer(ColumnMapping(columns=mapping)).normalize_rows(rows))
            with closing(store.connect()) as conn:
                known = store.load_known(conn)
            self._queue.put(("ok", records, deduplicate(records), mapping, KnownIndex(known)))
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
            self.records, self.result, self.mapping, self.index = msg[1], msg[2], msg[3], msg[4]
            self.decisions, self.known_decisions, self.known_cache = {}, {}, {}
            self.saved = False
            self._refresh()
        else:
            self._set_output("⚠ " + msg[1])

    # --- Fenêtres de vérification
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

    def open_known_review(self):
        if self.records is None or not self.known_pairs:
            return
        if self._known_win is not None and self._known_win.winfo_exists():
            self._known_win.lift()
            return
        # La fenêtre numérote les personnes de la base à sa façon ; on traduit dans les deux sens
        # pour que les décisions restent valables quand les groupes changent.
        to_known = dict(self._display_known)                       # ligne d'affichage -> position
        to_display = {k: j for j, k in to_known.items()}
        window_decisions = {
            (i, to_display[k]): d for (i, k), d in self.known_decisions.items() if k in to_display
        }
        pairs = list(self.known_pairs)

        def done():
            for i, j, _ in pairs:
                k = to_known[j]
                if (i, j) in window_decisions:
                    self.known_decisions[(i, k)] = window_decisions[(i, j)]
                else:
                    self.known_decisions.pop((i, k), None)
            self._refresh()

        assert self.records is not None
        self._known_win = ReviewWindow(
            self, [*self.records, *self.known_display], pairs, self.mapping,
            window_decisions, on_close=done,
        )

    # --- Export et enregistrement
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

    def _attach(self) -> dict[int, int]:
        """Groupes à rattacher à une personne déjà en base : les certains, et les probables confirmés."""
        index = self.index
        assert index is not None
        attach: dict[int, int] = {}
        for number, gm in self.matches.items():
            if gm.result is None or gm.known_index is None:
                continue
            cls = gm.result.classification
            key = _key(gm)
            confirmed = key is not None and self.known_decisions.get(key) == "same"
            if cls == Classification.CERTAIN or (cls == Classification.PROBABLE and confirmed):
                attach[number] = _person_id(index.persons[gm.known_index])
        return attach

    def save_to_db(self):
        if self.records is None or self.final is None or self._path is None or self.index is None:
            return
        records, final = self.records, self.final
        attach = self._attach()
        nom, prenom = store.identity_of(records[final.clusters[min(final.clusters)][0]], self.mapping)
        message = (
            f"Enregistrer {len(records)} inscriptions dans la base ?\n\n"
            f"   • {len(attach)} personne(s) déjà connue(s) : l'inscription s'ajoute à leur fiche\n"
            f"   • {len(final.clusters) - len(attach)} nouvelle(s) personne(s)\n\n"
            f"Contrôle (1re personne du fichier) :\n   nom = « {nom} »\n   prénom = « {prenom} »\n"
            "Si c'est inversé, annule et corrige les colonnes."
        )
        warnings = []
        if self.pending_cases:
            warnings.append(f"{len(self.pending_cases)} paire(s) du fichier non tranchée(s) : "
                            "enregistrées comme personnes distinctes.")
        if self.pending_known:
            warnings.append(f"{self.pending_known} correspondance(s) avec la base non tranchée(s) : "
                            "créées comme nouvelles personnes.")
        if warnings:
            message += "\n\n⚠ " + "\n⚠ ".join(warnings)
        if not messagebox.askyesno("Enregistrer dans la base", message):
            return
        try:
            with closing(store.connect()) as conn:
                report = store.save_analysis(conn, self._path, records, final, self.mapping, attach)
        except store.AlreadySavedError as e:
            messagebox.showwarning("Déjà enregistré", str(e))
            return
        except Exception as e:
            messagebox.showerror("Enregistrement impossible", str(e))
            return
        self.saved = True
        self.save_btn.configure(state="disabled")
        self._update_db_label()
        messagebox.showinfo(
            "Enregistré",
            f"{report.registrations} inscriptions ajoutées :\n"
            f"   • {report.known_persons} personne(s) déjà connue(s)\n"
            f"   • {report.new_persons} nouvelle(s) personne(s)",
        )

    # --- Affichage
    def _match_known(self, final: DedupResult):
        records, index = self.records, self.index
        assert records is not None and index is not None
        # seuls les groupes nouveaux ou modifiés sont recalculés
        todo = {n: m for n, m in final.clusters.items() if frozenset(m) not in self.known_cache}
        if todo:
            for n, gm in match_to_known(records, todo, index).items():
                self.known_cache[frozenset(todo[n])] = gm
        self.matches = {n: self.known_cache[frozenset(m)] for n, m in final.clusters.items()}

        self.known_display, self.known_pairs, self._display_known = [], [], {}
        shown: dict[int, int] = {}
        for gm in self.matches.values():
            if gm.result is None or gm.result.classification != Classification.PROBABLE:
                continue
            if gm.known_index is None or gm.record_index is None:
                continue
            if gm.known_index not in shown:
                self.known_display.append(
                    store.known_as_record(index.persons[gm.known_index], self.mapping)
                )
                j = len(records) + len(self.known_display) - 1
                shown[gm.known_index] = j
                self._display_known[j] = gm.known_index
            self.known_pairs.append((gm.record_index, shown[gm.known_index], gm.result))

    def _refresh(self):
        records, result = self.records, self.result
        if records is None or result is None or self.index is None:
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
        self._match_known(final)

        attached = new = pending_known = 0
        for gm in self.matches.values():
            cls = gm.result.classification if gm.result else Classification.NONE
            if cls == Classification.CERTAIN:
                attached += 1
            elif cls == Classification.PROBABLE:
                key = _key(gm)
                decision = self.known_decisions.get(key) if key else None
                if decision == "same":
                    attached += 1
                else:
                    new += 1
                    pending_known += decision is None
            else:
                new += 1
        self.pending_known = pending_known

        persons = len(final.clusters)
        no_name = sum(1 for r in records if any(i.code == "name_missing" for i in r.issues))
        issues = Counter(i.code for r in records for i in r.issues if i.code != "name_missing")

        lines = [
            f"Lignes lues                  {len(records):>6}",
            f"Personnes uniques            {persons:>6}",
            f"Doublons regroupés           {len(records) - persons:>6}",
            f"Paires du fichier en attente {len(pending):>6}",
            f"  confirmées identiques      {len(same):>6}",
            f"  confirmées différentes     {len(different):>6}",
            "",
            f"Déjà en base                 {attached:>6}",
            f"Nouvelles personnes          {new:>6}",
            f"Correspondances à vérifier   {pending_known:>6}",
            "",
            f"Lignes sans nom/prénom       {no_name:>6}",
        ]
        if contradictions:
            lines += ["", f"⚠ {len(contradictions)} décision(s) « différentes » contredite(s) "
                          "par d'autres confirmations."]
        if issues:
            lines += ["", "Problèmes de données :"]
            lines += [f"  {code} : {n}" for code, n in issues.most_common()]
        self._set_output("\n".join(lines))

        self.review_btn.configure(
            text=f"Paires du fichier ({len(pending)} en attente)",
            state="normal" if result.review else "disabled",
        )
        self.known_btn.configure(
            text=f"Correspondances avec la base ({pending_known} en attente)",
            state="normal" if self.known_pairs else "disabled",
        )
        self.export_btn.configure(state="normal")
        self.save_btn.configure(state="disabled" if self.saved else "normal")

    def _update_db_label(self):
        try:
            with closing(store.connect()) as conn:
                persons, registrations, files = store.stats(conn)
            text = f"Base : {persons} personnes · {registrations} inscriptions · {files} fichier(s)"
        except sqlite3.Error:
            text = "Base : indisponible"
        self.db_label.configure(text=text)

    def _set_output(self, text: str):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()