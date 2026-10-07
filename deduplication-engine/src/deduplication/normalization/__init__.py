from .emails import EmailResult, normalize_email
from .names import NameConfig, normalize_name
from .phones import PhoneResult, normalize_phone
from .split import split_emails, split_phones

__all__ = [
    "EmailResult", "NameConfig", "PhoneResult",
    "normalize_email", "normalize_name", "normalize_phone",
    "split_emails", "split_phones",
]