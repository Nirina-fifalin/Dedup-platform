import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from .models import Correction, Issue, NormalizedRecord
from .normalization import (
    NameConfig, normalize_email, normalize_name, normalize_phone, split_emails, split_phones,
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


def _email_problem(text: str) -> str:
    if "@" not in text:
        return f"Email invalide (pas de @) : {text!r}"
    if "." not in text.rsplit("@", 1)[1]:
        return f"Email invalide (domaine incomplet, point manquant) : {text!r}"
    return f"Email invalide : {text!r}"


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

        # Noms : la forme normalisée ne sert qu'à comparer, la valeur d'origine reste intacte
        nom_raw, prenom_raw = get("nom"), get("prenom")
        nom = normalize_name(nom_raw, self.name_config)
        prenom = normalize_name(prenom_raw, self.name_config)
        track("nom", nom_raw, nom)
        track("prenom", prenom_raw, prenom)
        if not nom or not prenom:
            issues.append(Issue(n, "nom/prenom", "name_missing", "Nom ou prénom manquant"))

        # Emails : une cellule peut en contenir plusieurs ; on garde les valides, on signale le reste
        emails: list[str] = []
        email_cell = get("email")
        if email_cell is not None and "@" not in str(email_cell):
            # du texte sans @ : un seul problème pour toute la cellule (pas un par mot)
            issues.append(Issue(n, "email", "email_invalid", _email_problem(str(email_cell))))
            email_parts: list[str] = []
        else:
            email_parts = split_emails(email_cell)
        for part in email_parts:
            e = normalize_email(part)
            if not (e.is_valid and e.normalized):
                issues.append(Issue(n, "email", "email_invalid", _email_problem(part)))
                continue
            if e.suspected_domain:
                issues.append(Issue(
                    n, "email", "email_suspected_domain",
                    f"Domaine {e.domain!r} proche de {e.suspected_domain!r} (non corrigé)",
                ))
            track("email", e.raw, e.normalized)
            if e.normalized not in emails:
                emails.append(e.normalized)
        if len(emails) > 1:
            issues.append(Issue(
                n, "email", "email_multiple",
                f"{len(emails)} emails dans la même cellule : tous conservés",
            ))

        # Téléphones : idem. Un numéro peu plausible est signalé mais n'est PAS utilisé :
        # on ne devine jamais un indicatif (il reste tel que saisi dans la ligne d'origine)
        phones: list[str] = []
        for part in split_phones(get("telephone")):
            p = normalize_phone(part, self.default_region)
            if p.normalized is None:
                issues.append(Issue(n, "telephone", "phone_invalid", f"Téléphone invalide : {p.raw!r}"))
                continue
            if not p.is_valid:
                issues.append(Issue(n, "telephone", "phone_unverified", f"Numéro peu plausible : {p.raw!r}"))
                continue
            track("telephone", p.raw, p.normalized)
            if p.normalized not in phones:
                phones.append(p.normalized)
        if len(phones) > 1:
            issues.append(Issue(
                n, "telephone", "phone_multiple",
                f"{len(phones)} téléphones dans la même cellule : tous conservés",
            ))

        if not emails and not phones:
            issues.append(Issue(n, "contact", "no_contact", "Ni email ni téléphone exploitable"))

        extra = {
            f: (None if get(f) is None else str(get(f)))
            for f in resolved if f not in IDENTITY_FIELDS
        }

        return NormalizedRecord(
            row=n, nom=nom, prenom=prenom,
            email=emails[0] if emails else None,
            telephone=phones[0] if phones else None,
            extra=extra, raw=dict(row), corrections=corrections, issues=issues,
            emails=emails, phones=phones,
        )