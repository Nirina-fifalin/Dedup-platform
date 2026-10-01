import re
from dataclasses import dataclass
from difflib import get_close_matches

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

COMMON_DOMAINS = (
    "gmail.com", "yahoo.fr", "yahoo.com", "hotmail.com",
    "hotmail.fr", "outlook.com", "outlook.fr", "live.fr",
)


@dataclass(frozen=True)
class EmailResult:
    raw: str | None
    normalized: str | None
    local: str | None
    domain: str | None
    is_valid: bool
    suspected_domain: str | None  # suggestion seulement, jamais appliquée


def normalize_email(value) -> EmailResult:
    if value is None or not str(value).strip():
        return EmailResult(None, None, None, None, False, None)

    raw = str(value)
    text = raw.strip().lower()
    if not _EMAIL_RE.match(text):
        return EmailResult(raw, text, None, None, False, None)

    local, domain = text.rsplit("@", 1)
    suspected = None
    if domain not in COMMON_DOMAINS:
        close = get_close_matches(domain, COMMON_DOMAINS, n=1, cutoff=0.8)
        suspected = close[0] if close else None

    return EmailResult(raw, text, local, domain, True, suspected)
