import json

import pytest
from deduplication import ColumnMapping, RecordNormalizer, apply_same, deduplicate

import store

MAPPING = {"nom": "Last", "prenom": "First", "email": "Mail", "telephone": "Tel",
           "formation": "Training"}
ROWS = [
    {"Last": "RAKOTO", "First": "Jean", "Mail": "jean@x.mg", "Tel": "0341234567",
     "Training": "Excel", "Age": "15-24 years"},
    {"Last": "Rakoto", "First": "Jean", "Mail": "j2@x.mg", "Tel": "034 12 345 67",
     "Training": "Python", "Age": "25-34 years"},
    {"Last": "Rasoa", "First": "Marie", "Mail": "m@x.mg", "Tel": "6303708",
     "Training": "IA", "Age": "15-24 years"},
]


def analysis(same=()):
    records = list(RecordNormalizer(ColumnMapping(columns=MAPPING)).normalize_rows(ROWS))
    return records, apply_same(deduplicate(records), same)


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "h.db")
    yield c
    c.close()


def test_save_creates_persons_contacts_and_registrations(conn, tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("contenu", encoding="utf-8")
    records, final = analysis(same=[(0, 1)])    # lignes 0 et 1 : confirmées "même personne"

    report = store.save_analysis(conn, f, records, final, MAPPING)
    assert (report.new_persons, report.registrations) == (2, 3)

    first = conn.execute("SELECT id, nom, prenom FROM persons ORDER BY id").fetchone()
    assert first[1:] == ("RAKOTO", "Jean")          # valeur saisie, pas la forme normalisée

    emails = [r[0] for r in conn.execute(
        "SELECT email FROM person_emails WHERE person_id = ? ORDER BY is_primary DESC, id", (first[0],))]
    assert emails == ["jean@x.mg", "j2@x.mg"]       # deux emails pour la même personne

    # le numéro peu plausible n'est pas un contact, mais reste dans l'inscription
    assert conn.execute("SELECT count(*) FROM person_phones").fetchone()[0] == 1
    reg = conn.execute("SELECT telephone_saisi, raw FROM registrations WHERE source_row = 4").fetchone()
    assert reg[0] == "6303708"
    assert json.loads(reg[1])["Age"] == "15-24 years"


def test_same_file_cannot_be_saved_twice(conn, tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("contenu", encoding="utf-8")
    records, final = analysis()
    store.save_analysis(conn, f, records, final, MAPPING)
    before = store.stats(conn)
    with pytest.raises(store.AlreadySavedError):
        store.save_analysis(conn, f, records, final, MAPPING)
    assert store.stats(conn) == before


def test_second_file_attaches_to_known_person_and_adds_new_email(conn, tmp_path):
    f1 = tmp_path / "a.csv"
    f1.write_text("1", encoding="utf-8")
    records, final = analysis(same=[(0, 1)])
    store.save_analysis(conn, f1, records, final, MAPPING)

    known = store.load_known(conn)
    assert len(known) == 2
    jean = next(k for k in known if k.nom == "rakoto")
    assert isinstance(jean.id, int)

    # 2e fichier : la même personne se réinscrit avec un nouvel email
    rows2 = [{"Last": "RAKOTO", "First": "Jean", "Mail": "jean.new@x.mg", "Tel": "0341234567",
              "Training": "IA", "Age": "25-34 years"}]
    recs2 = list(RecordNormalizer(ColumnMapping(columns=MAPPING)).normalize_rows(rows2))
    f2 = tmp_path / "b.csv"
    f2.write_text("2", encoding="utf-8")
    report = store.save_analysis(conn, f2, recs2, deduplicate(recs2), MAPPING, attach={1: jean.id})

    assert (report.new_persons, report.known_persons, report.registrations) == (0, 1, 1)
    assert store.stats(conn) == (2, 4, 2)          # aucune personne créée, une inscription de plus
    emails = {r[0] for r in conn.execute(
        "SELECT email FROM person_emails WHERE person_id = ?", (jean.id,))}
    assert emails == {"jean@x.mg", "j2@x.mg", "jean.new@x.mg"}