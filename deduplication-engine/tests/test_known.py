from deduplication import (
    Classification, ColumnMapping, GroupMatch, KnownIndex, KnownPerson, RecordNormalizer,
    match_to_known,
)

N = RecordNormalizer(ColumnMapping(columns={
    "nom": "nom", "prenom": "prenom", "email": "email", "telephone": "telephone",
}))


def classify(gm: GroupMatch) -> Classification:
    assert gm.result is not None
    return gm.result.classification


def known_id(index: KnownIndex, gm: GroupMatch):
    assert gm.known_index is not None
    return index.persons[gm.known_index].id


def test_known_certain_probable_and_new():
    jean = KnownPerson(id=7, nom="rakoto", prenom="jean",
                       emails=["jean@x.mg", "j2@x.mg"], phones=["+261341234567"], extra={})
    marie = KnownPerson(id=8, nom="rasoa", prenom="marie",
                        emails=["m@x.mg"], phones=["+261329876543"], extra={})
    index = KnownIndex([jean, marie])
    records = list(N.normalize_rows([
        dict(nom="Rakoto", prenom="Jean", email="j2@x.mg", telephone="0341234567"),   # 2e email connu
        dict(nom="Rasoa", prenom="Marie", email="m@x.mg", telephone="0331111111"),    # autre téléphone
        dict(nom="Andria", prenom="Tiana", email="t@x.mg", telephone="0349999999"),   # inconnue
    ]))
    out = match_to_known(records, {1: [0], 2: [1], 3: [2]}, index)

    assert classify(out[1]) == Classification.CERTAIN and known_id(index, out[1]) == 7
    assert classify(out[2]) == Classification.PROBABLE and known_id(index, out[2]) == 8
    assert out[3].known_index is None


def test_group_matching_two_known_persons_is_downgraded_to_probable():
    a = KnownPerson(id=1, nom="rakoto", prenom="jean", emails=["a@x.mg"], phones=[], extra={})
    b = KnownPerson(id=2, nom="rakoto", prenom="jean", emails=["b@x.mg"], phones=[], extra={})
    records = list(N.normalize_rows([
        dict(nom="Rakoto", prenom="Jean", email="a@x.mg"),
        dict(nom="Rakoto", prenom="Jean", email="b@x.mg"),
    ]))
    out = match_to_known(records, {1: [0, 1]}, KnownIndex([a, b]))
    assert classify(out[1]) == Classification.PROBABLE