from dataclasses import dataclass

import phonenumbers


@dataclass(frozen=True)
class PhoneResult:
    raw: str | None
    normalized: str | None  # E.164, ex. +261341234567
    is_valid: bool


def normalize_phone(value, default_region: str = "MG") -> PhoneResult:
    if value is None or str(value).strip() == "":
        return PhoneResult(None, None, False)

    # Excel renvoie parfois 341234567.0 (zéro initial perdu)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    raw = str(value)

    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException:
        return PhoneResult(raw, None, False)

    if not phonenumbers.is_possible_number(parsed):
        return PhoneResult(raw, None, False)

    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    return PhoneResult(raw, e164, phonenumbers.is_valid_number(parsed))

