import csv
from pathlib import Path

from deduplication.normalization import normalize_name

SYNONYMS = {
    "nom": {"nom", "nom de famille", "name", "last name", "lastname", "surname"},
    "prenom": {"prenom", "first name", "firstname", "given name"},
    "email": {"email", "e mail", "mail", "adresse email", "adresse mail",
              "adresse e mail", "courriel"},
    "telephone": {"telephone", "tel", "phone", "mobile", "numero de telephone", "contact"},
    "sexe": {"sexe", "genre", "gender", "sex"},
}


def guess_mapping(headers) -> dict[str, str]:
    """Associe chaque champ à la colonne qui porte un nom courant (nom, e-mail, tél...)."""
    mapping: dict[str, str] = {}
    for h in headers:
        key = normalize_name(h)
        for field, names in SYNONYMS.items():
            if field not in mapping and key in names:
                mapping[field] = h
    return mapping


def _read_csv(path: Path) -> list[dict]:
    # Les CSV exportés par Excel sous Windows sont souvent en cp1252, pas en UTF-8
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Encodage du fichier non reconnu.")
    first_line = text.splitlines()[0] if text else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    return list(csv.DictReader(text.splitlines(), delimiter=delimiter))


def _read_xlsx(path: Path) -> list[dict]:
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


def read_rows(path: str | Path) -> list[dict]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(path)
    if suffix == ".xlsx":
        return _read_xlsx(path)
    raise ValueError(f"Format non supporté : {suffix} (utiliser .csv ou .xlsx)")