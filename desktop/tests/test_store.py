import json

import pytest
import sqlite3
from deduplication import ColumnMapping, RecordNormalizer, apply_same, deduplicate
from contextlib import closing

import journal
import person_edit
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


def test_list_persons_and_registrations(conn, tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("x", encoding="utf-8")
    records, final = analysis(same=[(0, 1)])
    store.save_analysis(conn, f, records, final, MAPPING)

    rows = store.list_persons(conn)
    assert [(r[1], r[2], r[6]) for r in rows] == [("RAKOTO", "Jean", 2), ("Rasoa", "Marie", 1)]
    assert rows[0][4] == "jean@x.mg | j2@x.mg"
    assert rows[0][5] == "+261341234567"
    assert [r[0] for r in store.person_registrations(conn, rows[0][0])] == ["Excel", "Python"]


def _save(conn, tmp_path, name, rows, attach=None, replace=None):
    f = tmp_path / name
    f.write_text(repr(rows), encoding="utf-8")        # contenu différent => empreinte différente
    recs = list(RecordNormalizer(ColumnMapping(columns=MAPPING)).normalize_rows(rows))
    return store.save_analysis(conn, f, recs, deduplicate(recs), MAPPING, attach, replace)


V1 = [
    {"Last": "Rakoto", "First": "Jean", "Mail": "a@x.mg", "Tel": "0341234567", "Training": "Excel"},
    {"Last": "Rasoa", "First": "Marie", "Mail": "Marie Rasoa", "Tel": "0329876543", "Training": "IA"},
]
V1_FIXED = [V1[0], {**V1[1], "Mail": "marie@x.mg"}]


def test_replacing_a_corrected_file_does_not_duplicate_registrations(conn, tmp_path):
    first = _save(conn, tmp_path, "a.csv", V1)
    assert store.previous_versions(conn, "A.CSV")[0][0] == first.source_file_id
    assert store.load_known(conn, replacing=[first.source_file_id]) == []   # base vue sans l'ancienne version

    _save(conn, tmp_path, "a.csv", V1_FIXED, replace=[first.source_file_id])
    assert store.stats(conn) == (2, 2, 1)             # ni personne ni inscription en double
    marie = conn.execute("SELECT id FROM persons WHERE nom = 'Rasoa'").fetchone()[0]
    emails = [r[0] for r in conn.execute("SELECT email FROM person_emails WHERE person_id = ?", (marie,))]
    assert emails == ["marie@x.mg"]


def test_replacing_keeps_persons_with_other_registrations_and_rebuilds_contacts(conn, tmp_path):
    jean_a = {"Last": "Rakoto", "First": "Jean", "Mail": "a@x.mg", "Tel": "0341234567", "Training": "Excel"}
    a = _save(conn, tmp_path, "a.csv", [jean_a])
    jean = store.load_known(conn)[0]
    _save(conn, tmp_path, "b.csv", [{**jean_a, "Mail": "b@x.mg", "Training": "IA"}], attach={1: jean.id})
    assert store.stats(conn) == (1, 2, 2)

    without_a = store.load_known(conn, replacing=[a.source_file_id])
    assert [k.emails for k in without_a] == [["b@x.mg"]]   # l'email venu seulement de a.csv a disparu

    _save(conn, tmp_path, "a.csv", [{**jean_a, "Mail": "a2@x.mg"}],
          attach={1: jean.id}, replace=[a.source_file_id])
    assert store.stats(conn) == (1, 2, 2)
    emails = {r[0] for r in conn.execute("SELECT email FROM person_emails WHERE person_id = ?", (jean.id,))}
    assert emails == {"b@x.mg", "a2@x.mg"}


def test_removal_preview_and_delete_file_keep_shared_persons(conn, tmp_path):
    jean_a = {"Last": "Rakoto", "First": "Jean", "Mail": "a@x.mg", "Tel": "0341234567", "Training": "Excel"}
    marie = {"Last": "Rasoa", "First": "Marie", "Mail": "m@x.mg", "Tel": "0329876543", "Training": "IA"}
    a = _save(conn, tmp_path, "a.csv", [jean_a, marie])
    jean = next(k for k in store.load_known(conn) if k.nom == "rakoto")
    _save(conn, tmp_path, "b.csv", [{**jean_a, "Mail": "b@x.mg", "Training": "Python"}],
          attach={1: jean.id})

    preview = store.removal_preview(conn, a.source_file_id)
    assert (preview.registrations, preview.persons_deleted, preview.persons_kept) == (2, 1, 1)

    store.delete_file(conn, a.source_file_id)
    assert store.stats(conn) == (1, 1, 1)         # Marie supprimée ; Jean gardé, avec l'inscription de b.csv
    assert [r[0] for r in conn.execute("SELECT email FROM person_emails")] == ["b@x.mg"]
    assert conn.execute("SELECT action FROM audit_log").fetchone()[0] == "suppression_fichier"


def test_auto_backup_and_restore_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "data" / "h.db")
    monkeypatch.setattr(store, "BACKUP_DIR", tmp_path / "data" / "sauvegardes")
    f = tmp_path / "f.csv"
    f.write_text("x", encoding="utf-8")
    records, final = analysis(same=[(0, 1)])
    with closing(store.connect()) as conn:
        store.save_analysis(conn, f, records, final, MAPPING)

    backup = store.auto_backup("test")
    assert store.backup_info(backup) == (2, 3, 1)

    with closing(store.connect()) as conn:
        store.delete_file(conn, 1)
        assert store.stats(conn) == (0, 0, 0)

    safety = store.restore_from(backup)
    assert store.backup_info(safety) == (0, 0, 0)         # l'état d'avant la restauration est conservé
    with closing(store.connect()) as conn:
        assert store.stats(conn) == (2, 3, 1)
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert actions == ["suppression_fichier", "restauration"]   # le journal survit à la restauration


JEAN = {"Last": "Rakoto", "First": "Jean", "Mail": "a@x.mg", "Tel": "0341234567", "Training": "Excel"}
MARIE = {"Last": "Rasoa", "First": "Marie", "Mail": "m@x.mg", "Tel": "0329876543", "Training": "IA"}


def first_person_id(conn) -> int:
    pid = store.load_known(conn)[0].id
    assert isinstance(pid, int)
    return pid


def ids_by_name(conn) -> dict[str, int]:
    out: dict[str, int] = {}
    for person in store.load_known(conn):
        assert isinstance(person.id, int)
        out[person.nom] = person.id
    return out


def test_connect_migrates_an_old_database(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(store.SCHEMA)                    # base sans les colonnes de contact (version 1)
    raw.execute("PRAGMA user_version = 1")
    raw.execute("INSERT INTO persons (nom, prenom, nom_norm, prenom_norm, created_at) "
                "VALUES ('A', 'B', 'a', 'b', 'x')")
    raw.commit()
    raw.close()
    with closing(store.connect(path)) as migrated:
        assert migrated.execute("SELECT contact_status FROM persons").fetchone()[0] == "ok"
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 2


def test_do_not_contact_survives_file_removal_and_reimport(conn, tmp_path):
    first = _save(conn, tmp_path, "a.csv", [JEAN])
    pid = first_person_id(conn)
    store.set_contact_status(conn, pid, True, "Désabonnement")
    assert [r[0] for r in conn.execute("SELECT email FROM suppressed_emails")] == ["a@x.mg"]

    store.delete_file(conn, first.source_file_id)
    assert store.stats(conn) == (0, 0, 0)               # la personne a disparu avec son fichier

    _save(conn, tmp_path, "a2.csv", [JEAN])             # réimport
    assert conn.execute("SELECT contact_status FROM persons").fetchone()[0] == "do_not_contact"


def test_delete_person_erases_data_but_keeps_only_the_opt_out_email(conn, tmp_path):
    _save(conn, tmp_path, "a.csv", [JEAN, MARIE])
    ids = ids_by_name(conn)
    store.set_contact_status(conn, ids["rakoto"], True)

    assert store.delete_person(conn, ids["rakoto"]) == 1
    assert store.delete_person(conn, ids["rasoa"]) == 1
    assert store.stats(conn)[:2] == (0, 0)
    assert [r[0] for r in conn.execute("SELECT email FROM suppressed_emails")] == ["a@x.mg"]


def test_reauthorizing_contact_clears_the_opposition_entry(conn, tmp_path):
    _save(conn, tmp_path, "a.csv", [JEAN])
    pid = first_person_id(conn)
    store.set_contact_status(conn, pid, True, "Désabonnement")
    status, at, note = store.contact_info(conn, pid)
    assert (status, note) == ("do_not_contact", "Désabonnement") and at

    store.set_contact_status(conn, pid, False)
    assert store.contact_info(conn, pid)[0] == "ok"
    assert conn.execute("SELECT count(*) FROM suppressed_emails").fetchone()[0] == 0


def _person_ids(conn) -> list[int]:
    ids: list[int] = []
    for k in store.load_known(conn):
        assert isinstance(k.id, int)
        ids.append(k.id)
    return ids


def _only_person(conn) -> int:
    (only,) = _person_ids(conn)
    return only


def test_parse_contacts_flags_errors_and_suspected_domains():
    p = person_edit.parse_contacts(
        "jean@gamil.com\npasunemail\nJean@Gmail.com", "034 12 345 67 / 0329876543\n12"
    )
    assert p.emails == ["jean@gamil.com", "jean@gmail.com"]
    assert p.suspected == [("jean@gamil.com", "gmail.com")]
    assert p.phones == ["+261341234567", "+261329876543"]
    assert len(p.errors) == 2                      # « pasunemail » et « 12 »


def test_update_person_fixes_email_keeps_history_and_journal_has_no_address(conn, tmp_path):
    _save(conn, tmp_path, "a.csv", [{**JEAN, "Mail": "jean@gamil.com"}])
    pid = _only_person(conn)
    d = person_edit.person_details(conn, pid)
    assert d.emails == ["jean@gamil.com"]

    changed = person_edit.update_person(
        conn, pid, d.nom, d.prenom, d.sexe, ["jean@gmail.com"], d.phones
    )
    assert changed == ["emails"]
    assert person_edit.person_details(conn, pid).emails == ["jean@gmail.com"]
    assert [h[1:] for h in person_edit.edit_history(conn, pid)] == [
        ("emails", "jean@gamil.com", "jean@gmail.com")
    ]
    latest = journal.list_audit(conn)[0]
    assert latest[1] == "modification_personne"
    assert "gmail" not in latest[2] and "gamil" not in latest[2]


def test_manual_contact_correction_survives_a_file_replacement(conn, tmp_path):
    a = _save(conn, tmp_path, "a.csv", [{**JEAN, "Mail": "jean@gamil.com"}])
    pid = _only_person(conn)
    _save(conn, tmp_path, "b.csv", [{**JEAN, "Mail": "jean@gamil.com", "Training": "IA"}],
          attach={1: pid})
    d = person_edit.person_details(conn, pid)
    person_edit.update_person(conn, pid, d.nom, d.prenom, d.sexe, ["jean@gmail.com"], d.phones)

    store.delete_file(conn, a.source_file_id)      # recalculerait les contacts d'une fiche normale
    assert person_edit.person_details(conn, pid).emails == ["jean@gmail.com"]


def test_correcting_an_opted_out_persons_email_extends_the_opposition_list(conn, tmp_path):
    _save(conn, tmp_path, "a.csv", [{**JEAN, "Mail": "jean@gamil.com"}])
    pid = _only_person(conn)
    store.set_contact_status(conn, pid, True, "Désabonnement")
    d = person_edit.person_details(conn, pid)
    person_edit.update_person(conn, pid, d.nom, d.prenom, d.sexe, ["jean@gmail.com"], d.phones)
    suppressed = {r[0] for r in conn.execute("SELECT email FROM suppressed_emails")}
    assert suppressed == {"jean@gamil.com", "jean@gmail.com"}   # on ne perd jamais un désabonnement


def test_shared_contacts_reveals_a_possible_duplicate(conn, tmp_path):
    other = {**JEAN, "Last": "Autre", "First": "Personne", "Mail": "jean@gamil.com", "Tel": "0329876543"}
    _save(conn, tmp_path, "a.csv", [JEAN, other])
    first_id, second_id = _person_ids(conn)
    d = person_edit.person_details(conn, second_id)
    assert person_edit.shared_contacts(conn, second_id) == set()

    person_edit.update_person(conn, second_id, d.nom, d.prenom, d.sexe, ["a@x.mg"], d.phones)
    shared = person_edit.shared_contacts(conn, second_id)
    assert {(kind, value, pid) for kind, value, pid, _ in shared} == {("email", "a@x.mg", first_id)}