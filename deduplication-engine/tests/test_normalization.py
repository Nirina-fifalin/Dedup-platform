import pytest
from deduplication.normalization import (
    normalize_email, normalize_name, normalize_phone,
)


@pytest.mark.parametrize("raw", [" Jean Rakoto ", "JEAN RAKOTO", "Jean  Rakoto", "Jean-Rakoto"])
def test_name_variants_converge(raw):
    assert normalize_name(raw) == "jean rakoto"


def test_name_accents():
    assert normalize_name("Éloïse") == "eloise"


def test_email_case_and_spaces():
    assert normalize_email(" Jean.Rakoto@GMAIL.COM ").normalized == "jean.rakoto@gmail.com"


def test_email_typo_is_flagged_not_corrected():
    r = normalize_email("jean.rakoto@gmial.com")
    assert r.normalized == "jean.rakoto@gmial.com"
    assert r.suspected_domain == "gmail.com"


def test_email_invalid():
    assert not normalize_email("pas un email").is_valid


@pytest.mark.parametrize("raw", ["034 12 345 67", "0341234567", "+261 34 12 345 67", 341234567.0])
def test_phone_formats_converge(raw):
    assert normalize_phone(raw).normalized == "+261341234567"


def test_phone_empty():
    assert normalize_phone("").normalized is None
    