import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from .models import Correction, Issue, NormalizedRecord
from .normalization import (
    NameConfig, normalize_email, normalize_name, normalize_phone,
)

IDENTITY_FIELDS = ("nom", "prenom", "email", "telephone")


class MissingColumnsError(ValueError):
    pass


@dataclass(frozen=True)
class ColumnMapping:
    """champ canonique -> nom de la colonne dans le fichier source."""
    columns: dict[str, str]
    required: tuple[str, ...] = ("nom", "prenom")


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):  # cellule vide pandas
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class RecordNormalizer:
    def __init__(
        self,
        mapping: ColumnMapping,
        name_config: NameConfig = NameConfig(),
        default_region: str = "MG",
    ):
        self.mapping = mapping
        self.name_config = name_config
        self.default_region = default_region

    def resolve_columns(self, available: Iterable[str]) -> dict[str, str]:
        """Associe champ canonique -> colonne réelle (insensible casse/accents)."""
        by_key = {normalize_name(c): c for c in available}
        resolved, missing = {}, []
        for field_name, header in self.mapping.columns.items():
            actual = by_key.get(normalize_name(header))
            if actual is not None:
                resolved[field_name] = actual
            elif field_name in self.mapping.required:
                missing.append(header)
        if missing:
            raise MissingColumnsError(f"Colonnes obligatoires absentes : {missing}")
        return resolved

    def normalize_rows(
        self, rows: Iterable[Mapping], first_row_number: int = 2
    ) -> Iterator[NormalizedRecord]:
        """first_row_number=2 : la ligne 1 d'Excel est l'en-tête."""
        resolved = None
        for i, row in enumerate(rows, start=first_row_number):
            if resolved is None:
                resolved = self.resolve_columns(row.keys())
            yield self._normalize_row(row, i, resolved)

    def _normalize_row(self, row, n, resolved) -> NormalizedRecord:
        def get(name):
            return _clean(row.get(resolved[name])) if name in resolved else None

        corrections: list[Correction] = []
        issues: list[Issue] = []

        def track(name, raw, norm):
            if raw is not None and str(raw) != (norm or ""):
                corrections.append(Correction(n, name, str(raw), norm))

        # Noms
        nom_raw, prenom_raw = get("nom"), get("prenom")
        nom = normalize_name(nom_raw, self.name_config)
        prenom = normalize_name(prenom_raw, self.name_config)
        track("nom", nom_raw, nom)
        track("prenom", prenom_raw, prenom)
        if not nom or not prenom:
            issues.append(Issue(n, "nom/prenom", "name_missing", "Nom ou prénom manquant"))

        # Email : on ne garde que les emails valides, on signale les domaines suspects
        e = normalize_email(get("email"))
        email = e.normalized if e.is_valid else None
        if e.raw is not None and not e.is_valid:
            issues.append(Issue(n, "email", "email_invalid", f"Email invalide : {e.raw!r}"))
        elif e.suspected_domain:
            issues.append(Issue(
                n, "email", "email_suspected_domain",
                f"Domaine {e.domain!r} proche de {e.suspected_domain!r} (non corrigé)",
            ))
        if e.is_valid:
            track("email", e.raw, email)

        # Téléphone
        p = normalize_phone(get("telephone"), self.default_region)
        if p.raw is not None and p.normalized is None:
            issues.append(Issue(n, "telephone", "phone_invalid", f"Téléphone invalide : {p.raw!r}"))
        elif p.normalized and not p.is_valid:
            issues.append(Issue(n, "telephone", "phone_unverified", f"Numéro peu plausible : {p.raw!r}"))
        if p.normalized:
            track("telephone", p.raw, p.normalized)

        if email is None and p.normalized is None:
            issues.append(Issue(n, "contact", "no_contact", "Ni email ni téléphone exploitable"))

        extra = {
            f: (None if get(f) is None else str(get(f)))
            for f in resolved if f not in IDENTITY_FIELDS
        }

        return NormalizedRecord(
            row=n, nom=nom, prenom=prenom, email=email, telephone=p.normalized,
            extra=extra, raw=dict(row), corrections=corrections, issues=issues,
        )
