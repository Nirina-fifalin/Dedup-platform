from dataclasses import dataclass, field
from enum import Enum
from types import SimpleNamespace

from ..normalization import normalize_name
from .comparators import compare_email, compare_exact, compare_names, phone_distance
from .config import MatchConfig

BASE_FIELDS = {"nom", "prenom", "email", "telephone"}


class Classification(str, Enum):
    CERTAIN = "certain"
    PROBABLE = "probable"
    NONE = "none"


@dataclass
class MatchResult:
    score: float
    classification: Classification
    field_scores: dict[str, float | None]
    reasons: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


_ORDER = {Classification.CERTAIN: 2, Classification.PROBABLE: 1, Classification.NONE: 0}


def _rank(res: "MatchResult") -> tuple[int, float]:
    return (_ORDER[res.classification], res.score)

class Matcher:
    def __init__(self, config: MatchConfig = MatchConfig()):
        self.config = config

    def compare(self, a, b) -> MatchResult:
        """a et b : objets avec nom, prenom, email, telephone, extra."""
        c = self.config
        reasons: list[str] = []
        conflicts: list[str] = []

        # --- Noms
        nom_s, prenom_s, swapped = compare_names(a, b)
        name_vals = [s for s in (nom_s, prenom_s) if s is not None]
        name_avg = sum(name_vals) / len(name_vals) if name_vals else None
        name_conflict = name_avg is not None and name_avg < c.name_conflict_threshold

        # --- Email (en dessous du seuil "similaire" => compte comme différent)
        email_raw = compare_email(a.email, b.email)
        email_s = email_raw
        if email_raw is not None and email_raw < c.email_similar_threshold:
            email_s = 0.0

        # --- Téléphone (0 identique, 1 proche, 2 différent)
        phone_d = phone_distance(a.telephone, b.telephone)
        if phone_d is None:
            phone_s = None
        elif phone_d == 0:
            phone_s = 1.0
        elif phone_d == 1:
            phone_s = c.phone_near_score
        else:
            phone_s = 0.0

        scores: dict[str, float | None] = {
            "nom": nom_s, "prenom": prenom_s,
            "email": email_s, "telephone": phone_s,
        }

        # --- Champs additionnels pondérés (sexe, tranche_age, ...)
        for key in c.weights:
            if key in BASE_FIELDS:
                continue
            va = normalize_name(a.extra.get(key)) if a.extra.get(key) else None
            vb = normalize_name(b.extra.get(key)) if b.extra.get(key) else None
            scores[key] = compare_exact(va, vb)
            if scores[key] == 0.0:
                reasons.append(f"- {key} différent")

        # --- Score pondéré sur les champs disponibles des deux côtés
        used = {k: v for k, v in scores.items() if v is not None and k in c.weights}
        total_w = sum(c.weights[k] for k in used)
        score = sum(c.weights[k] * v for k, v in used.items()) / total_w if total_w else 0.0

        # -- Explications
        if phone_d == 0:
            reasons.append("+ Téléphone identique")
        elif phone_d == 1:
            reasons.append("- Téléphone légèrement différent")
        elif phone_d == 2:
            reasons.append("- Téléphone différent")
            conflicts.append("telephone_conflict")

        if email_raw is not None:
            if email_raw == 1.0:
                reasons.append("+ Email identique")
            elif email_s and email_s > 0:
                reasons.append("- Email légèrement différent")
            else:
                reasons.append("- Email différent")
                conflicts.append("email_conflict")

        for label, s in (("Nom", nom_s), ("Prénom", prenom_s)):
            if s is None:
                continue
            if s >= 0.999:
                reasons.append(f"+ {label} identique")
            elif s >= c.name_conflict_threshold:
                reasons.append(f"+ {label} similaire")
            else:
                reasons.append(f"- {label} différent")
        if swapped and name_avg and name_avg >= c.name_conflict_threshold:
            reasons.append("+ Nom et prénom inversés")
        if name_conflict:
            conflicts.append("name_conflict")

        # --- Classification
        strong = int(email_s == 1.0) + int(phone_d == 0)
        phone_near = phone_d == 1

        if strong >= 1 and not conflicts and score >= c.certain_threshold:
            cls = Classification.CERTAIN
        elif score >= c.probable_threshold:
            cls = Classification.PROBABLE
        elif strong == 2 or ((strong == 1 or phone_near) and not name_conflict):
            cls = Classification.PROBABLE   # indice fort ou proche + conflit => validation humaine
        else:
            cls = Classification.NONE

        return MatchResult(round(score, 4), cls, scores, reasons, conflicts)

    def compare_to_person(self, record, person) -> MatchResult:
        """Compare une inscription à une personne ayant plusieurs emails/téléphones.

        On teste chaque combinaison (email, téléphone) connue de la personne et on
        garde la meilleure : une inscription avec un ancien email ne doit pas être
        pénalisée parce que la personne en a aussi un autre.
        """
        emails = list(person.emails) or [None]
        phones = list(person.phones) or [None]
        best = None
        for e in emails:
            for p in phones:
                view = SimpleNamespace(
                    nom=person.nom, prenom=person.prenom,
                    email=e, telephone=p, extra=person.extra,
                )
                res = self.compare(record, view)
                if best is None or _rank(res) > _rank(best):
                    best = res
        assert best is not None
        return best