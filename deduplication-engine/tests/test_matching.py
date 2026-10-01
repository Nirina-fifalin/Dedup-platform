from deduplication import ColumnMapping, RecordNormalizer
from deduplication.matching import Classification, Matcher

N = RecordNormalizer(ColumnMapping(columns={
    "nom": "nom", "prenom": "prenom", "email": "email",
    "telephone": "telephone", "sexe": "sexe",
}))
M = Matcher()


def rec(**row):
    return next(N.normalize_rows([row]))


def test_spec_example_same_person_different_formats():
    a = rec(nom="Rakoto", prenom="Jean", email="jean.rakoto@gmail.com", telephone="0341234567")
    b = rec(nom="RAKOTO", prenom="Jean", email="jean.rakoto@gmial.com", telephone="+261 34 12 345 67")
    r = M.compare(a, b)
    assert r.classification == Classification.CERTAIN
    assert "+ Téléphone identique" in r.reasons
    assert "- Email légèrement différent" in r.reasons


def test_swapped_name_columns():
    a = rec(nom="Rakoto", prenom="Jean", telephone="0341234567")
    b = rec(nom="Jean", prenom="Rakoto", telephone="0341234567")
    r = M.compare(a, b)
    assert r.classification == Classification.CERTAIN
    assert "+ Nom et prénom inversés" in r.reasons


def test_typo_in_surname_with_same_contacts():
    a = rec(nom="Rakoto", prenom="Jean", email="j@x.mg", telephone="0341234567")
    b = rec(nom="Rakotto", prenom="Jean", email="j@x.mg", telephone="0341234567")
    assert M.compare(a, b).classification == Classification.CERTAIN


def test_same_email_different_phone_is_flagged_not_merged():
    a = rec(nom="Rakoto", prenom="Jean", email="jean.rakoto@gmail.com", telephone="0341234567")
    b = rec(nom="Rakoto", prenom="Jean", email="jean.rakoto@gmail.com", telephone="0329876543")
    r = M.compare(a, b)
    assert r.classification == Classification.PROBABLE
    assert "telephone_conflict" in r.conflicts


def test_name_alone_is_never_certain():
    a = rec(nom="Rakoto", prenom="Jean")
    b = rec(nom="Rakoto", prenom="Jean")
    assert M.compare(a, b).classification != Classification.CERTAIN


def test_shared_family_phone_is_not_same_person():
    a = rec(nom="Rakoto", prenom="Jean", telephone="0341234567")
    b = rec(nom="Rasoa", prenom="Marie", telephone="0341234567")
    r = M.compare(a, b)
    assert r.classification == Classification.NONE
    assert "name_conflict" in r.conflicts


def test_different_people():
    a = rec(nom="Rakoto", prenom="Jean", email="a@x.mg", telephone="0341234567")
    b = rec(nom="Rasoanaivo", prenom="Marie", email="m@y.mg", telephone="0329876543")
    assert M.compare(a, b).classification == Classification.NONE