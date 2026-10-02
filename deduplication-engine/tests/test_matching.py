from deduplication import ColumnMapping, RecordNormalizer
from deduplication.matching import Classification, Matcher
from deduplication import KnownPerson


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


def test_phone_one_digit_typo_with_same_email_is_certain():
    a = rec(nom="Razafy", prenom="Fanja", email="fanja.razafy@yahoo.fr", telephone="0332842572")
    b = rec(nom="Razafy", prenom="Fanja", email="fanja.razafy@yahoo.fr", telephone="0332842582")
    r = M.compare(a, b)
    assert r.classification == Classification.CERTAIN
    assert "telephone_conflict" not in r.conflicts


def test_phone_typo_with_new_email_goes_to_review():
    a = rec(nom="Rasolofo", prenom="Marie", email="marie.rasolofo@hotmail.com", telephone="0381296570")
    b = rec(nom="Rasolofo", prenom="Marie", email="marie92@gmail.com", telephone="0381295570")
    assert M.compare(a, b).classification == Classification.PROBABLE


def test_phone_transposition_counts_as_near():
    a = rec(nom="Rabe", prenom="Tiana", telephone="0336872032")
    b = rec(nom="Rabe", prenom="Tiana", telephone="0336872302")
    assert "- Téléphone légèrement différent" in M.compare(a, b).reasons


def test_same_surname_and_domain_different_first_name_is_not_similar_email():
    a = rec(nom="Rakotoarisoa", prenom="Tiana", email="tiana.rakotoarisoa@hotmail.com", sexe="F")
    b = rec(nom="Rakkotoarisoa", prenom="Jean", email="jean.rakotoarisoa@hotmail.com", sexe="M")
    r = M.compare(a, b)
    assert "- Email différent" in r.reasons
    assert r.classification == Classification.NONE


def test_domain_typo_is_still_similar_email():
    a = rec(nom="Rakoto", prenom="Jean", email="jean.rakoto@gmail.com")
    b = rec(nom="Rakoto", prenom="Jean", email="jean.rakoto@gmail.cm")
    assert "- Email légèrement différent" in M.compare(a, b).reasons


def test_inscription_with_second_known_email_is_certain():
    p = KnownPerson(id=1, nom="randria", prenom="tsiky",
                    emails=["tsiky.randria@gmail.com", "tsiky29@gmail.com"],
                    phones=["+261320781151"])
    r = rec(nom="Randria", prenom="Tsiky", email="tsiky29@gmail.com", telephone="0320781151")
    assert M.compare_to_person(r, p).classification == Classification.CERTAIN


def test_inscription_with_unknown_email_goes_to_review():
    p = KnownPerson(id=1, nom="randria", prenom="tsiky",
                    emails=["tsiky.randria@gmail.com"], phones=["+261320781151"])
    r = rec(nom="Randria", prenom="Tsiky", email="autre@yahoo.fr", telephone="0320781151")
    assert M.compare_to_person(r, p).classification == Classification.PROBABLE


def test_inscription_with_new_phone_matches_previous_phone():
    p = KnownPerson(id=2, nom="rabe", prenom="hery",
                    emails=["hery.rabe@gmail.com"],
                    phones=["+261321111111", "+261331112222"])
    r = rec(nom="Rabe", prenom="Hery", email="hery.rabe@gmail.com", telephone="0321111111")
    res = M.compare_to_person(r, p)
    assert res.classification == Classification.CERTAIN
    assert "telephone_conflict" not in res.conflicts