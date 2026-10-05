from deduplication import ColumnMapping, RecordNormalizer, deduplicate

N = RecordNormalizer(ColumnMapping(columns={
    "nom": "nom", "prenom": "prenom", "email": "email", "telephone": "telephone",
}))


def run(rows):
    records = list(N.normalize_rows(rows))
    return deduplicate(records)


def test_groups_certain_and_flags_probable():
    res = run([
        dict(nom="Rakoto", prenom="Jean", email="jean@x.mg", telephone="0341234567"),
        dict(nom="RAKOTO", prenom="Jean", email="jean@x.mg", telephone="034 12 345 67"),
        dict(nom="Rasoa", prenom="Marie", email="m@x.mg", telephone="0329876543"),
        dict(nom="Rasoa", prenom="Marie", email="m@x.mg", telephone="0331111111"),
    ])
    assert res.person_of[0] == res.person_of[1]
    assert res.person_of[2] != res.person_of[3]
    assert len(res.clusters) == 3
    assert [(i, j) for i, j, _ in res.review] == [(2, 3)]


def test_homonyms_with_different_contacts_stay_separate_and_unflagged():
    res = run([
        dict(nom="Rakoto", prenom="Jean", email="a@x.mg", telephone="0341234567"),
        dict(nom="Rakoto", prenom="Jean", email="b@x.mg", telephone="0329876543"),
    ])
    assert len(res.clusters) == 2
    assert res.review == []