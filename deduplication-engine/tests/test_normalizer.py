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


def test_multi_value_cells_are_split_and_kept():
    row = {"nom": "Rakoto", "prenom": "Jean",
           "email": "a@x.mg /b@y.mg", "telephone": "0341234567/ 0329876543"}
    rec = next(make().normalize_rows([row]))
    assert rec.emails == ["a@x.mg", "b@y.mg"]
    assert len(rec.phones) == 2 and rec.phones[0] == "+261341234567"
    codes = {i.code for i in rec.issues}
    assert {"email_multiple", "phone_multiple"} <= codes
    assert "email_invalid" not in codes and "phone_invalid" not in codes


def test_unverified_phone_is_flagged_and_not_used():
    row = {"nom": "Rakoto", "prenom": "Jean", "email": "a@x.mg", "telephone": "6303708"}
    rec = next(make().normalize_rows([row]))
    assert rec.phones == [] and rec.telephone is None
    assert "phone_unverified" in {i.code for i in rec.issues}


def test_text_in_email_cell_is_a_single_problem():
    row = {"nom": "Rakoto", "prenom": "Jean", "email": "Fanomezantsoa Narindra Prisca",
           "telephone": "0341234567"}
    rec = next(make().normalize_rows([row]))
    assert [i.code for i in rec.issues if i.field == "email"] == ["email_invalid"]


