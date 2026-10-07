import re

_PHONE_SEP = re.compile(r"\s*(?:[/;,|\n]|\s-\s|\s(?:et|ou|and)\s)\s*", re.IGNORECASE)
_EMAIL_SEP = re.compile(r"[\s/;,|]+")


def split_phones(value) -> list[str]:
    """'0376491452/0346077875' -> deux numéros. Les espaces DANS un numéro sont conservés."""
    if value is None:
        return []
    if isinstance(value, float) and value.is_integer():   # Excel : 341234567.0
        value = int(value)
    return [p.strip() for p in _PHONE_SEP.split(str(value)) if p and p.strip()]


def split_emails(value) -> list[str]:
    if value is None:
        return []
    return [e for e in _EMAIL_SEP.split(str(value).strip()) if e]