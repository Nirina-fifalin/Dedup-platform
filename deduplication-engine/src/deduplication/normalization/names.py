import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class NameConfig:
    lowercase: bool = True
    strip_accents: bool = True
    hyphen_as_space: bool = True
    remove_punctuation: bool = True


_HYPHENS = re.compile(r"[-_\u2010\u2011\u2013]")
_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def normalize_name(value, config: NameConfig = NameConfig()) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    if config.strip_accents:
        text = "".join(
            c for c in unicodedata.normalize("NFD", text)
            if not unicodedata.combining(c)
        )
    if config.lowercase:
        text = text.casefold()
    if config.hyphen_as_space:
        text = _HYPHENS.sub(" ", text)
    if config.remove_punctuation:
        text = _PUNCT.sub("", text)
    return _SPACES.sub(" ", text).strip()

