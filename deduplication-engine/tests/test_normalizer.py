import pytest
from deduplication.normalizer import ColumnMapping, MissingColumnsError, RecordNormalizer

MAPPING = ColumnMapping(columns={
    "nom": "Nom", "prenom": "Prénom", "email": "Email",
    "telephone": "Téléphone", "ville": "Ville",
})


def make():
    return RecordNormalizer(MAPPING)


def test_full_row():
    row = {"nom": "RAKOTO", "PRENOM": " Jean ", "email": "Jean.Rakoto@GMIAL.com",
           "TELEPHONE": "034 12 345 67", "ville": "Tana"}
    rec = next(make().normalize_rows([row]))
    assert (rec.nom, rec.prenom) == ("rakoto", "jean")
    assert rec.email == "jean.rakoto@gmial.com"
    assert rec.telephone == "+261341234567"
    assert rec.extra == {"ville": "Tana"}
    assert rec.row == 2
    assert {i.code for i in rec.issues} == {"email_suspected_domain"}
    assert {c.field for c in rec.corrections} >= {"nom", "email", "telephone"}


def test_invalid_email_and_missing_contact():
    row = {"Nom": "Rakoto", "Prénom": "Jean", "Email": "nimportequoi", "Téléphone": None}
    rec = next(make().normalize_rows([row]))
    assert rec.email is None
    assert {i.code for i in rec.issues} == {"email_invalid", "no_contact"}


def test_missing_required_column():
    with pytest.raises(MissingColumnsError):
        list(make().normalize_rows([{"Nom": "Rakoto", "Email": "a@b.com"}]))
