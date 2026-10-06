import csv
import json
from pathlib import Path

from deduplication.normalization import normalize_name

SYNONYMS = {
    "nom": {"nom", "nom de famille", "last name", "lastname", "surname", "family name"},
    "prenom": {"prenom", "first name", "firstname", "given name"},
    "email": {"email", "e mail", "mail", "adresse email", "adresse mail",
              "adresse e mail", "courriel"},
    "telephone": {"telephone", "tel", "phone", "phone number", "mobile",
                  "numero de telephone", "contact"},
    "sexe": {"sexe", "genre", "gender", "sex"},
    "formation": {"formation", "training", "training name", "name of training conducted",
                  "name of training", "nom de la formation", "intitule de la formation"},    
}

_STORE = Path(__file__).with_name("column_mappings.json")


def guess_mapping(headers) -> dict[str, str]:
    """Associe chaque champ à la colonne qui porte un nom courant (nom, e-mail, tél...)."""
    mapping: dict[str, str] = {}
    ambiguous = None
    for h in headers:
        key = normalize_name(h)
        if key == "name":
            ambiguous = ambiguous or h
        for field, names in SYNONYMS.items():
            if field not in mapping and key in names:
                mapping[field] = h
    # « Name » seul est ambigu : on le range dans le champ identité qui manque
    if ambiguous:
        if "nom" in mapping and "prenom" not in mapping:
            mapping["prenom"] = ambiguous
        elif "prenom" in mapping and "nom" not in mapping:
            mapping["nom"] = ambiguous
    return mapping


def _signature(headers) -> str:
    return "|".join(headers)


def load_saved_mapping(headers) -> dict[str, str] | None:
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    saved = data.get(_signature(headers))
    if isinstance(saved, dict) and all(v in headers for v in saved.values()):
        return saved
    return None


def save_mapping(headers, mapping: dict[str, str]) -> None:
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[_signature(headers)] = mapping
    try:
        _STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass   # ne pas empêcher l'analyse si le dossier est en lecture seule


def _read_csv_text(path: Path) -> str:
    # Les CSV exportés par Excel sous Windows sont souvent en cp1252, pas en UTF-8
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Encodage du fichier non reconnu.")


def _delimiter(text: str) -> str:
    first = text.splitlines()[0] if text else ""
    return ";" if first.count(";") > first.count(",") else ","


def read_headers(path: str | Path) -> list[str]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = _read_csv_text(path)
        if not text.strip():
            raise ValueError("Le fichier est vide.")
        first = text.splitlines()[0]
        return next(csv.reader([first], delimiter=_delimiter(text)), [])
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            if ws is None:
                raise ValueError("Classeur sans feuille active.")
            first = next(ws.iter_rows(values_only=True), None)
            if not first:
                raise ValueError("Le fichier est vide.")
            return [str(h).strip() if h is not None else "" for h in first]
        finally:
            wb.close()
    raise ValueError(f"Format non supporté : {suffix} (utiliser .csv ou .xlsx)")


def read_rows(path: str | Path) -> list[dict]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = _read_csv_text(path)
        return list(csv.DictReader(text.splitlines(), delimiter=_delimiter(text)))
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            if ws is None:
                raise ValueError("Classeur sans feuille active.")
            it = ws.iter_rows(values_only=True)
            headers = [str(h).strip() if h is not None else "" for h in next(it, [])]
            return [dict(zip(headers, r)) for r in it if any(c is not None for c in r)]
        finally:
            wb.close()
    raise ValueError(f"Format non supporté : {suffix} (utiliser .csv ou .xlsx)")