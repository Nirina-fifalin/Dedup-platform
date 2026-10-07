import queue
import sqlite3
import threading
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from deduplication import (
    Classification, ColumnMapping, DedupResult, GroupMatch, KnownIndex, KnownPerson,
    MatchResult, NormalizedRecord, RecordNormalizer, apply_same, deduplicate, match_to_known,
)

import store
from browse_window import BrowseWindow
from dialogs import ask_choice
from exporter import export_workbook
from file_reader import guess_mapping, load_saved_mapping, read_rows, save_mapping
from mapping_dialog import MappingDialog
from review_window import ReviewWindow

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

OUTLINE = {"fg_color": "transparent", "border_width": 1, "text_color": ("gray10", "gray90")}
ACCENT = ("#1f6aa5", "#6fb3e8")

ISSUE_LABELS = {
    "email_invalid": "adresse email incorrecte (non utilisée)",
    "email_suspected_domain": "adresse email avec une faute probable, par exemple « gmial.com » (non corrigée)",
    "email_multiple": "plusieurs emails dans la même case (tous conservés)",
    "phone_invalid": "numéro de téléphone incorrect (non utilisé)",
    "phone_unverified": "numéro de téléphone douteux, par exemple sans indicatif (non utilisé)",
    "phone_multiple": "plusieurs téléphones dans la même case (tous conservés)",
    "no_contact": "ni email ni téléphone utilisable",
}


def _key(gm: GroupMatch) -> tuple[int, int] | None:
    """Clé stable d'une décision : (ligne du fichier, position de la personne connue)."""
    if gm.record_index is None or gm.known_index is None:
        return None
    return gm.record_index, gm.known_index


def _person_id(kp: KnownPerson) -> int:
    assert isinstance(kp.id, int)
    return kp.id


def _fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y")
    except ValueError:
        return iso[:10]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Déduplication des inscriptions")
        self.geometry("1000x720")
        self.minsize(900, 640)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._queue: queue.Queue = queue.Queue()
        self._path: Path | None = None
        self._review_win: ReviewWindow | None = None
        self._known_win: ReviewWindow | None = None
        self._browse_win: BrowseWindow | None = None
        self.records: list[NormalizedRecord] | None = None
        self.result: DedupResult | None = None
        self.final: DedupResult | None = None
        self.pending_cases: list[tuple[int, int, MatchResult]] = []
        self.mapping: dict[str, str] = {}
        self.decisions: dict[tuple[int, int], str] = {}        # paires DU FICHIER
        self.saved = False
        self.replace_ids: list[int] = []
        self.replace_note = ""

        # Correspondances avec la base
        self.index: KnownIndex | None = None
        self.known_cache: dict[frozenset[int], GroupMatch] = {}
        self.matches: dict[int, GroupMatch] = {}
        self.known_pairs: list[tuple[int, int, MatchResult]] = []
        self.known_display: list[NormalizedRecord] = []
        self._display_known: dict[int, int] = {}
        self.known_decisions: dict[tuple[int, int], str] = {}
        self.pending_known = 0

        self._build_header()
        self._build_file_panel()
        self._build_results()
        self._build_footer()
        self._update_db_label()
        self._reset_view()

    # ------------------------------------------------------------------ construction
    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=24, pady=(18, 0), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="Déduplication des inscriptions",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.db_label = ctk.CTkLabel(header, text="", text_color="gray", anchor="w")
        self.db_label.grid(row=1, column=0, sticky="w")
        tools = ctk.CTkFrame(header, fg_color="transparent")
        tools.grid(row=0, column=1, rowspan=2, sticky="e")
        ctk.CTkButton(tools, text="Consulter la base", command=self.open_browse, **OUTLINE).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(tools, text="Sauvegarder la base", command=self.backup_db, **OUTLINE).pack(
            side="left"
        )
        self.hint = ctk.CTkLabel(
            self, text="", anchor="w", font=ctk.CTkFont(size=14), text_color=ACCENT
        )
        self.hint.grid(row=1, column=0, padx=24, pady=(10, 8), sticky="ew")

    def _build_file_panel(self):
        panel = ctk.CTkFrame(self)
        panel.grid(row=2, column=0, padx=24, pady=(0, 12), sticky="ew")
        panel.grid_columnconfigure(0, weight=1)
        self.file_label = ctk.CTkLabel(
            panel, text="Aucun fichier choisi", anchor="w", font=ctk.CTkFont(size=14)
        )
        self.file_label.grid(row=0, column=0, padx=16, pady=14, sticky="ew")
        self.choose_btn = ctk.CTkButton(panel, text="Choisir un fichier…", width=170, command=self.choose_file)
        self.choose_btn.grid(row=0, column=1, padx=(0, 8), pady=14)
        self.run_btn = ctk.CTkButton(panel, text="Analyser", width=130, command=self.run, state="disabled")
        self.run_btn.grid(row=0, column=2, padx=(0, 16), pady=14)
        self.progress = ctk.CTkProgressBar(panel, mode="indeterminate")
        self.progress.grid(row=1, column=0, columnspan=3, padx=16, pady=(0, 12), sticky="ew")
        self.progress.grid_remove()

    def _build_results(self):
        self.placeholder = ctk.CTkLabel(
            self, text="Les résultats de l'analyse s'afficheront ici.", text_color="gray"
        )
        self.placeholder.grid(row=3, column=0)

        r = self.results = ctk.CTkScrollableFrame(self, fg_color="transparent")
        r.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="cards")

        self.note = ctk.CTkLabel(r, text="", anchor="w", text_color="#c2570c")
        self.note.grid(row=0, column=0, columnspan=4, padx=8, sticky="ew")

        self.cards: dict[str, ctk.CTkLabel] = {}
        for col, (key, label) in enumerate([
            ("rows", "Lignes lues"),
            ("persons", "Personnes différentes\n(doublons regroupés)"),
            ("known", "Déjà dans la base"),
            ("new", "Nouvelles personnes"),
        ]):
            card = ctk.CTkFrame(r, corner_radius=10)
            card.grid(row=1, column=col, padx=6, pady=6, sticky="nsew")
            value = ctk.CTkLabel(card, text="–", font=ctk.CTkFont(size=30, weight="bold"))
            value.pack(padx=12, pady=(14, 0))
            ctk.CTkLabel(card, text=label, text_color="gray", justify="center").pack(
                padx=12, pady=(0, 14)
            )
            self.cards[key] = value

        check = ctk.CTkFrame(r, corner_radius=10)
        check.grid(row=2, column=0, columnspan=4, padx=6, pady=6, sticky="ew")
        check.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(check, text="À vérifier", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=2, padx=16, pady=(12, 4), sticky="w"
        )
        self.file_pairs_label = ctk.CTkLabel(check, text="", anchor="w")
        self.file_pairs_label.grid(row=1, column=0, padx=16, pady=4, sticky="ew")
        self.file_pairs_btn = ctk.CTkButton(check, text="Vérifier", width=110, command=self.open_review)
        self.file_pairs_btn.grid(row=1, column=1, padx=16, pady=4)
        self.known_label = ctk.CTkLabel(check, text="", anchor="w")
        self.known_label.grid(row=2, column=0, padx=16, pady=(4, 12), sticky="ew")
        self.known_btn = ctk.CTkButton(check, text="Vérifier", width=110, command=self.open_known_review)
        self.known_btn.grid(row=2, column=1, padx=16, pady=(4, 12))

        problems = ctk.CTkFrame(r, corner_radius=10)
        problems.grid(row=3, column=0, columnspan=4, padx=6, pady=6, sticky="ew")
        ctk.CTkLabel(
            problems, text="Données à surveiller", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(padx=16, pady=(12, 4), anchor="w")
        self.issues_text = ctk.CTkLabel(
            problems, text="", justify="left", anchor="w", wraplength=820
        )
        self.issues_text.pack(padx=16, pady=(0, 12), anchor="w")

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, padx=24, pady=(4, 18), sticky="ew")
        footer.grid_columnconfigure(1, weight=1)
        self.export_btn = ctk.CTkButton(
            footer, text="Exporter en Excel…", command=self.export, state="disabled", **OUTLINE
        )
        self.export_btn.grid(row=0, column=0)
        self.footer_hint = ctk.CTkLabel(
            footer, text="", text_color="gray", anchor="e", justify="right", wraplength=430
        )
        self.footer_hint.grid(row=0, column=1, padx=12, sticky="e")
        self.save_btn = ctk.CTkButton(
            footer, text="Enregistrer dans la base", width=220, height=40, command=self.save_to_db,
            state="disabled", fg_color="#2e7d32", hover_color="#1b5e20",
            font=ctk.CTkFont(weight="bold"),
        )
        self.save_btn.grid(row=0, column=2)

    # ------------------------------------------------------------------ états
    def _reset_view(self):
        self.results.grid_remove()
        self.placeholder.grid(row=3, column=0)
        self.export_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.footer_hint.configure(text="")
        if self._path is None:
            self.hint.configure(text="Étape 1 sur 3 — Choisissez un fichier Excel ou CSV d'inscriptions.")
        else:
            self.hint.configure(text="Étape 2 sur 3 — Cliquez sur « Analyser ».")

    def _busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.choose_btn.configure(state=state)
        self.run_btn.configure(state="disabled" if busy or self._path is None else "normal")
        if busy:
            self.export_btn.configure(state="disabled")
            self.save_btn.configure(state="disabled")
            self.progress.grid()
            self.progress.start()
            self.hint.configure(text="Analyse en cours…")
        else:
            self.progress.stop()
            self.progress.grid_remove()

    # ------------------------------------------------------------------ choix et analyse
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
        self.records, self.result, self.final, self.index = None, None, None, None
        self.decisions, self.known_decisions, self.known_cache = {}, {}, {}
        self.pending_cases, self.known_pairs, self.matches = [], [], {}
        self.replace_ids, self.replace_note = [], ""
        self.saved = False
        self._reset_view()

    def run(self):
        if self._path is None:
            return
        try:
            rows = read_rows(self._path)
            if not rows:
                raise ValueError("Le fichier est vide.")
        except Exception as e:
            messagebox.showerror("Lecture impossible", str(e))
            return

        # Un fichier du même nom a-t-il déjà été enregistré ? (version corrigée ?)
        self.replace_ids, self.replace_note = [], ""
        try:
            with closing(store.connect()) as conn:
                versions = store.previous_versions(conn, self._path.name)
        except sqlite3.Error:
            versions = []
        if versions:
            when = _fmt_date(versions[-1][1])
            choice = ask_choice(
                self, "Fichier déjà enregistré",
                f"Un fichier nommé « {self._path.name} » a déjà été enregistré le {when}.\n\n"
                "S'agit-il de la même feuille, corrigée ? Dans ce cas, remplacez l'ancienne "
                "version : les inscriptions ne seront pas comptées deux fois.\n\n"
                "S'il s'agit d'inscriptions différentes, ajoutez-le comme nouveau fichier.",
                [("replace", "Remplacer l'ancienne version"),
                 ("add", "L'ajouter comme nouveau fichier"),
                 ("cancel", "Annuler")],
            )
            if choice in (None, "cancel"):
                return
            if choice == "replace":
                self.replace_ids = [v[0] for v in versions]
                self.replace_note = f"↻ Cette feuille remplacera la version enregistrée le {when}."

        headers = [str(h) for h in rows[0].keys()]
        initial = load_saved_mapping(headers) or guess_mapping(headers)
        MappingDialog(
            self, headers, initial, rows[0],
            on_confirm=lambda m: self._start(rows, headers, m),
        )

    def _start(self, rows: list[dict], headers: list[str], mapping: dict[str, str]):
        save_mapping(headers, mapping)
        self._busy(True)
        threading.Thread(
            target=self._work, args=(rows, mapping, list(self.replace_ids)), daemon=True
        ).start()
        self.after(100, self._poll)

    def _work(self, rows: list[dict], mapping: dict[str, str], replacing: list[int]):
        try:
            records = list(RecordNormalizer(ColumnMapping(columns=mapping)).normalize_rows(rows))
            with closing(store.connect()) as conn:
                known = store.load_known(conn, replacing=replacing)
            self._queue.put(("ok", records, deduplicate(records), mapping, KnownIndex(known)))
        except Exception as e:
            self._queue.put(("error", str(e)))

    def _poll(self):
        try:
            msg = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return
        self._busy(False)
        if msg[0] == "ok":
            self.records, self.result, self.mapping, self.index = msg[1], msg[2], msg[3], msg[4]
            self.decisions, self.known_decisions, self.known_cache = {}, {}, {}
            self.saved = False
            self._refresh()
        else:
            self._reset_view()
            messagebox.showerror("Analyse impossible", msg[1])

    # ------------------------------------------------------------------ fenêtres de vérification
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

    def open_browse(self):
        if self._browse_win is not None and self._browse_win.winfo_exists():
            self._browse_win.lift()
            return
        self._browse_win = BrowseWindow(self)

    # ------------------------------------------------------------------ export, sauvegarde, enregistrement
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

    def backup_db(self):
        target = filedialog.asksaveasfilename(
            title="Sauvegarder la base", defaultextension=".db",
            initialfile=f"sauvegarde_base_{datetime.now():%Y-%m-%d}.db",
            filetypes=[("Base de données", "*.db")],
        )
        if not target:
            return
        try:
            store.backup_to(Path(target))
        except Exception as e:
            messagebox.showerror("Sauvegarde impossible", str(e))
            return
        messagebox.showinfo(
            "Sauvegarde terminée",
            f"La base a été copiée dans :\n{target}\n\n"
            "Garde ce fichier en lieu sûr : il contient des données personnelles.",
        )

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
            f"   • {len(attach)} personne(s) déjà dans la base : on ajoute leur inscription\n"
            f"   • {len(final.clusters) - len(attach)} nouvelle(s) personne(s)\n\n"
        )
        if self.replace_ids:
            message += "↻ L'ancienne version de ce fichier sera remplacée.\n\n"
        message += (
            f"Contrôle (1re personne du fichier) :\n   nom = « {nom} »\n   prénom = « {prenom} »\n"
            "Si c'est inversé, annulez et corrigez les colonnes."
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
                report = store.save_analysis(
                    conn, self._path, records, final, self.mapping, attach, self.replace_ids
                )
        except store.AlreadySavedError as e:
            messagebox.showwarning("Déjà enregistré", str(e))
            return
        except Exception as e:
            messagebox.showerror("Enregistrement impossible", str(e))
            return
        self.saved = True
        self.replace_ids, self.replace_note = [], ""
        self._update_db_label()
        self._refresh()
        messagebox.showinfo(
            "Enregistré",
            f"{report.registrations} inscriptions ajoutées :\n"
            f"   • {report.known_persons} personne(s) déjà dans la base\n"
            f"   • {report.new_persons} nouvelle(s) personne(s)",
        )

    # ------------------------------------------------------------------ affichage
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

    @staticmethod
    def _set_check(label: ctk.CTkLabel, button: ctk.CTkButton, text: str, pending: int, has_cases: bool):
        if not has_cases:
            status = "aucun cas"
        elif pending == 0:
            status = "tout est tranché ✔"
        else:
            status = f"{pending} à trancher"
        label.configure(text=f"{text} : {status}")
        button.configure(
            state="normal" if has_cases else "disabled",
            text="Vérifier" if (pending or not has_cases) else "Revoir",
        )

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

        no_name = sum(1 for r in records if any(i.code == "name_missing" for i in r.issues))
        issues = Counter(i.code for r in records for i in r.issues if i.code != "name_missing")

        self.placeholder.grid_remove()
        self.results.grid(row=3, column=0, padx=14, pady=(0, 4), sticky="nsew")
        self.note.configure(text=self.replace_note)
        self.cards["rows"].configure(text=str(len(records)))
        self.cards["persons"].configure(text=str(len(final.clusters)))
        self.cards["known"].configure(text=str(attached))
        self.cards["new"].configure(text=str(new))

        self._set_check(self.file_pairs_label, self.file_pairs_btn,
                        "Mêmes personnes possibles dans ce fichier", len(pending), bool(result.review))
        self._set_check(self.known_label, self.known_btn,
                        "Personnes peut-être déjà dans la base", pending_known, bool(self.known_pairs))

        lines = [f"•  {n} cas : {ISSUE_LABELS.get(code, code)}" for code, n in issues.most_common()]
        if no_name:
            lines.append(f"•  {no_name} ligne(s) sans nom ou sans prénom")
        if contradictions:
            lines.append(f"⚠  {len(contradictions)} décision(s) « personnes différentes » "
                         "contredite(s) par d'autres confirmations")
        self.issues_text.configure(text="\n".join(lines) if lines else "Aucun problème détecté ✔")

        total = len(pending) + pending_known
        self.export_btn.configure(state="normal")
        self.save_btn.configure(state="disabled" if self.saved else "normal")
        if self.saved:
            self.hint.configure(text="✔ Enregistré. Vous pouvez choisir un autre fichier.")
            self.footer_hint.configure(text="")
        elif total:
            self.hint.configure(
                text="Étape 3 sur 3 — Vous pouvez trancher les cas à vérifier, puis enregistrer."
            )
            self.footer_hint.configure(
                text=f"{total} cas non tranché(s) : ils seront enregistrés comme personnes distinctes."
            )
        else:
            self.hint.configure(
                text="Étape 3 sur 3 — Tout est prêt : vous pouvez enregistrer dans la base."
            )
            self.footer_hint.configure(text="")

    def _update_db_label(self):
        try:
            with closing(store.connect()) as conn:
                persons, registrations, files = store.stats(conn)
            text = f"Base : {persons} personnes · {registrations} inscriptions · {files} fichier(s)"
        except sqlite3.Error:
            text = "Base : indisponible"
        self.db_label.configure(text=text)


if __name__ == "__main__":
    App().mainloop()