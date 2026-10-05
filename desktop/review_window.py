from collections.abc import Callable

import customtkinter as ctk
from deduplication import MatchResult, NormalizedRecord

FIELDS = [("nom", "Nom"), ("prenom", "Prénom"), ("email", "Email"), ("telephone", "Téléphone")]
SAME_COLOR = ("gray10", "gray90")
DIFF_COLOR = ("#c2570c", "#f0a060")

Pair = tuple[int, int, MatchResult]


class ReviewWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        records: list[NormalizedRecord],
        pairs: list[Pair],
        mapping: dict[str, str],
        decisions: dict[tuple[int, int], str],
        on_close: Callable[[], None],
    ):
        super().__init__(master)
        self.title("Vérification des paires")
        self.geometry("660x580")
        self.minsize(620, 540)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.records = records
        self.pairs = pairs
        self.mapping = mapping
        self.decisions = decisions
        self.on_close = on_close
        # on reprend à la première paire sans décision
        self.index = next(
            (n for n, (i, j, _) in enumerate(pairs) if (i, j) not in decisions), 0
        )

        self.grid_columnconfigure((0, 1), weight=1, uniform="cards")
        self.grid_rowconfigure(2, weight=1)

        self.header = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.header.grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 0), sticky="w")

        self.cards = [self._build_card(0), self._build_card(1)]

        self.reasons = ctk.CTkTextbox(self, height=120, state="disabled")
        self.reasons.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 10), sticky="nsew")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=2, pady=(0, 6))
        ctk.CTkButton(
            buttons, text="Même personne", fg_color="#2e7d32", hover_color="#1b5e20",
            command=lambda: self._decide("same"),
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            buttons, text="Personnes différentes", fg_color="#c62828", hover_color="#8e0000",
            command=lambda: self._decide("different"),
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            buttons, text="Plus tard", fg_color="gray40", hover_color="gray30",
            command=lambda: self._decide(None),
        ).pack(side="left", padx=5)

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=4, column=0, columnspan=2, pady=(0, 16))
        ctk.CTkButton(
            nav, text="◀ Précédent", width=110, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), command=lambda: self._go(self.index - 1),
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            nav, text="Terminer", width=110, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), command=self.close,
        ).pack(side="left", padx=5)

        self._show()

    def _build_card(self, column: int):
        frame = ctk.CTkFrame(self)
        frame.grid(
            row=1, column=column, padx=(20, 10) if column == 0 else (10, 20),
            pady=12, sticky="nsew",
        )
        title = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(weight="bold"))
        title.pack(anchor="w", padx=12, pady=(10, 6))
        labels: dict[str, ctk.CTkLabel] = {}
        for key, name in FIELDS:
            ctk.CTkLabel(frame, text=name, text_color="gray").pack(anchor="w", padx=12)
            value = ctk.CTkLabel(frame, text="", anchor="w", justify="left", wraplength=250)
            value.pack(anchor="w", padx=12, pady=(0, 6))
            labels[key] = value
        return title, labels

    def _raw(self, rec: NormalizedRecord, key: str) -> str:
        col = self.mapping.get(key)
        value = rec.raw.get(col) if col else None
        if isinstance(value, float) and value.is_integer():
            value = int(value)                      # Excel : 341234567.0 -> 341234567
        text = "" if value is None else str(value).strip()
        return text or "—"

    def _show(self):
        i, j, res = self.pairs[self.index]
        a, b = self.records[i], self.records[j]
        tag = {"same": " · confirmée : même personne",
               "different": " · confirmée : différentes"}.get(self.decisions.get((i, j), ""), "")
        self.header.configure(
            text=f"Paire {self.index + 1} / {len(self.pairs)} · score {res.score:.0%}{tag}"
        )
        for (title, labels), rec, other in ((self.cards[0], a, b), (self.cards[1], b, a)):
            title.configure(text=f"Ligne {rec.row} du fichier")
            for key, _ in FIELDS:
                differs = getattr(rec, key) != getattr(other, key)
                labels[key].configure(
                    text=self._raw(rec, key),
                    text_color=DIFF_COLOR if differs else SAME_COLOR,
                )
        self.reasons.configure(state="normal")
        self.reasons.delete("1.0", "end")
        self.reasons.insert("1.0", "\n".join(res.reasons))
        self.reasons.configure(state="disabled")

    def _decide(self, value: str | None):
        i, j, _ = self.pairs[self.index]
        if value is None:
            self.decisions.pop((i, j), None)
        else:
            self.decisions[(i, j)] = value
        self._go(self.index + 1)

    def _go(self, n: int):
        if n >= len(self.pairs):
            self.close()
            return
        self.index = max(0, n)
        self._show()

    def close(self):
        self.on_close()
        self.destroy()