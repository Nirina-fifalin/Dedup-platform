import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing

from deduplication import DedupResult, KnownPerson, NormalizedRecord
from deduplication.matching.comparators import compare_email, phone_distance
from deduplication.normalization import normalize_email, normalize_phone, split_emails, split_phones

from exporter import EMAIL_SIMILAR, _collect_emails, _collect_phones, _raw

DB_PATH = Path(__file__).with_name("data") / "historique.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_files (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    row_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY,
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    nom_norm TEXT NOT NULL,
    prenom_norm TEXT NOT NULL,
    sexe TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS person_emails (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES persons(id),
    email TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    UNIQUE (person_id, email)
);
CREATE TABLE IF NOT EXISTS person_phones (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES persons(id),
    phone TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    UNIQUE (person_id, phone)
);
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES persons(id),
    source_file_id INTEGER NOT NULL REFERENCES source_files(id),
    source_row INTEGER NOT NULL,
    formation TEXT,
    email_saisi TEXT,
    telephone_saisi TEXT,
    raw TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_emails_email ON person_emails(email);
CREATE INDEX IF NOT EXISTS ix_phones_phone ON person_phones(phone);
CREATE INDEX IF NOT EXISTS ix_persons_norm ON persons(nom_norm, prenom_norm);
CREATE INDEX IF NOT EXISTS ix_reg_person ON registrations(person_id);
CREATE INDEX IF NOT EXISTS ix_reg_file ON registrations(source_file_id);
"""


class AlreadySavedError(Exception):
    pass


@dataclass
class SaveReport:
    source_file_id: int
    new_persons: int
    known_persons: int
    registrations: int


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
        conn.execute("PRAGMA user_version = 1")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    row_id = conn.execute(sql, params).lastrowid
    assert row_id is not None
    return row_id


def identity_of(rec: NormalizedRecord, mapping: dict[str, str]) -> tuple[str, str]:
    """Nom et prénom tels que saisis dans le fichier (pas la forme normalisée)."""
    return _raw(rec, mapping, "nom") or rec.nom, _raw(rec, mapping, "prenom") or rec.prenom


def stats(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """(personnes, inscriptions, fichiers)."""
    return (
        conn.execute("SELECT count(*) FROM persons").fetchone()[0],
        conn.execute("SELECT count(*) FROM registrations").fetchone()[0],
        conn.execute("SELECT count(*) FROM source_files").fetchone()[0],
    )


def _read_known(conn: sqlite3.Connection) -> list[KnownPerson]:
    persons: dict[int, KnownPerson] = {}
    for pid, nom, prenom, nom_norm, prenom_norm, sexe in conn.execute(
        "SELECT id, nom, prenom, nom_norm, prenom_norm, sexe FROM persons ORDER BY id"
    ):
        persons[pid] = KnownPerson(
            id=pid, nom=nom_norm, prenom=prenom_norm,
            extra={"sexe": sexe, "_nom": nom, "_prenom": prenom},
        )
    for pid, email in conn.execute(
        "SELECT person_id, email FROM person_emails ORDER BY is_primary DESC, id"
    ):
        persons[pid].emails.append(email)
    for pid, phone in conn.execute(
        "SELECT person_id, phone FROM person_phones ORDER BY is_primary DESC, id"
    ):
        persons[pid].phones.append(phone)
    return list(persons.values())


def load_known(conn: sqlite3.Connection, replacing: list[int] | None = None) -> list[KnownPerson]:
    """Personnes de la base. `replacing` : fichiers qu'on s'apprête à remplacer, ignorés ici
    (on travaille sur une copie en mémoire, la vraie base n'est pas touchée)."""
    if not replacing:
        return _read_known(conn)
    copy = sqlite3.connect(":memory:")
    try:
        conn.backup(copy)
        remove_file_versions(copy, replacing)
        return _read_known(copy)
    finally:
        copy.close()


def known_as_record(kp: KnownPerson, mapping: dict[str, str]) -> NormalizedRecord:
    """Affichage d'une personne de la base dans la fenêtre de comparaison."""
    raw: dict = {}
    for field, value in (
        ("nom", kp.extra.get("_nom")),
        ("prenom", kp.extra.get("_prenom")),
        ("email", " | ".join(kp.emails) or None),
        ("telephone", " | ".join(kp.phones) or None),
    ):
        if field in mapping:
            raw[mapping[field]] = value
    return NormalizedRecord(
        row=0, nom=kp.nom, prenom=kp.prenom,
        email=kp.emails[0] if kp.emails else None,
        telephone=kp.phones[0] if kp.phones else None,
        extra={"_label": f"Personne déjà en base (n° {kp.id})"},
        raw=raw, emails=list(kp.emails), phones=list(kp.phones),
    )


def _add_contacts(conn: sqlite3.Connection, pid: int, emails: list[str], phones: list[str]) -> None:
    """Ajoute les nouveaux emails/téléphones à une personne. Une simple faute de frappe
    d'une valeur déjà connue n'est pas ajoutée (elle reste dans l'inscription)."""
    have_e = [r[0] for r in conn.execute("SELECT email FROM person_emails WHERE person_id = ?", (pid,))]
    have_p = [r[0] for r in conn.execute("SELECT phone FROM person_phones WHERE person_id = ?", (pid,))]
    for email in emails:
        if all((compare_email(email, h) or 0) < EMAIL_SIMILAR for h in have_e):
            conn.execute(
                "INSERT INTO person_emails (person_id, email, is_primary) VALUES (?, ?, ?)",
                (pid, email, int(not have_e)),
            )
            have_e.append(email)
    for phone in phones:
        if all(phone_distance(phone, h) == 2 for h in have_p):
            conn.execute(
                "INSERT INTO person_phones (person_id, phone, is_primary) VALUES (?, ?, ?)",
                (pid, phone, int(not have_p)),
            )
            have_p.append(phone)


def previous_versions(conn: sqlite3.Connection, filename: str) -> list[tuple[int, str, int]]:
    """Fichiers déjà enregistrés sous le même nom : (id, date d'enregistrement, nb de lignes)."""
    return conn.execute(
        "SELECT id, imported_at, row_count FROM source_files "
        "WHERE lower(filename) = lower(?) ORDER BY id",
        (filename,),
    ).fetchall()


def _contacts_from_cells(email_cells: list, phone_cells: list) -> tuple[list[str], list[str]]:
    """Mêmes règles qu'à l'import : on ne garde que les valeurs valides, sans doublon ni faute proche."""
    emails: list[str] = []
    phones: list[str] = []
    for cell in email_cells:
        for part in split_emails(cell):
            e = normalize_email(part)
            if e.is_valid and e.normalized and all(
                (compare_email(e.normalized, o) or 0) < EMAIL_SIMILAR for o in emails
            ):
                emails.append(e.normalized)
    for cell in phone_cells:
        for part in split_phones(cell):
            p = normalize_phone(part)
            if p.is_valid and p.normalized and all(
                phone_distance(p.normalized, o) == 2 for o in phones
            ):
                phones.append(p.normalized)
    return emails, phones


def rebuild_contacts(conn: sqlite3.Connection, person_id: int) -> None:
    """Recalcule les emails/téléphones d'une personne à partir de ses inscriptions restantes."""
    cells = conn.execute(
        "SELECT email_saisi, telephone_saisi FROM registrations WHERE person_id = ? ORDER BY id",
        (person_id,),
    ).fetchall()
    emails, phones = _contacts_from_cells([c[0] for c in cells], [c[1] for c in cells])
    conn.execute("DELETE FROM person_emails WHERE person_id = ?", (person_id,))
    conn.execute("DELETE FROM person_phones WHERE person_id = ?", (person_id,))
    for k, email in enumerate(emails):
        conn.execute(
            "INSERT INTO person_emails (person_id, email, is_primary) VALUES (?, ?, ?)",
            (person_id, email, int(k == 0)),
        )
    for k, phone in enumerate(phones):
        conn.execute(
            "INSERT INTO person_phones (person_id, phone, is_primary) VALUES (?, ?, ?)",
            (person_id, phone, int(k == 0)),
        )


def remove_file_versions(conn: sqlite3.Connection, file_ids: list[int]) -> None:
    """Retire des fichiers enregistrés et leurs inscriptions. Les personnes qui n'ont plus
    aucune inscription disparaissent ; les autres voient leurs contacts recalculés."""
    if not file_ids:
        return
    marks = ",".join("?" * len(file_ids))
    affected = [r[0] for r in conn.execute(
        f"SELECT DISTINCT person_id FROM registrations WHERE source_file_id IN ({marks})", file_ids
    )]
    conn.execute(f"DELETE FROM registrations WHERE source_file_id IN ({marks})", file_ids)
    conn.execute(f"DELETE FROM source_files WHERE id IN ({marks})", file_ids)
    for pid in affected:
        left = conn.execute(
            "SELECT count(*) FROM registrations WHERE person_id = ?", (pid,)
        ).fetchone()[0]
        if left:
            rebuild_contacts(conn, pid)
        else:
            conn.execute("DELETE FROM person_emails WHERE person_id = ?", (pid,))
            conn.execute("DELETE FROM person_phones WHERE person_id = ?", (pid,))
            conn.execute("DELETE FROM persons WHERE id = ?", (pid,))


def backup_to(target: Path, source: Path = DB_PATH) -> None:
    """Copie cohérente de la base (sûre même si elle vient d'être modifiée)."""
    with closing(connect(source)) as src:
        dest = sqlite3.connect(target)
        try:
            src.backup(dest)
        finally:
            dest.close()


def save_analysis(
    conn: sqlite3.Connection,
    path: str | Path,
    records: list[NormalizedRecord],
    final: DedupResult,
    mapping: dict[str, str],
    attach: dict[int, int] | None = None,
    replace: list[int] | None = None,
) -> SaveReport:
    """Enregistre le résultat d'une analyse. Tout ou rien : une erreur n'écrit rien.

    attach  : numéro de groupe -> id d'une personne déjà en base à laquelle le rattacher.
    replace : fichiers déjà enregistrés (anciennes versions) que celui-ci remplace.
    """
    attach = attach or {}
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if conn.execute("SELECT 1 FROM source_files WHERE file_hash = ?", (digest,)).fetchone():
        raise AlreadySavedError(f"« {path.name} » a déjà été enregistré (même contenu).")

    now = _now()
    with conn:   # une seule transaction : validée à la fin, annulée en cas d'erreur
        if replace:
            remove_file_versions(conn, replace)
        source_id = _insert(
            conn,
            "INSERT INTO source_files (filename, file_hash, imported_at, row_count) VALUES (?, ?, ?, ?)",
            (path.name, digest, now, len(records)),
        )
        db_id: dict[int, int] = {}
        created = 0
        for number in sorted(final.clusters):
            recs = [records[i] for i in final.clusters[number]]
            sexe = next((r.extra.get("sexe") for r in recs if r.extra.get("sexe")), None)
            if number in attach:
                pid = attach[number]
                if sexe:
                    conn.execute("UPDATE persons SET sexe = ? WHERE id = ? AND sexe IS NULL", (sexe, pid))
            else:
                nom, prenom = identity_of(recs[0], mapping)
                pid = _insert(
                    conn,
                    "INSERT INTO persons (nom, prenom, nom_norm, prenom_norm, sexe, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (nom, prenom, recs[0].nom, recs[0].prenom, sexe, now),
                )
                created += 1
            db_id[number] = pid
            _add_contacts(conn, pid, _collect_emails(recs), _collect_phones(recs))
        for i, rec in enumerate(records):
            conn.execute(
                "INSERT INTO registrations (person_id, source_file_id, source_row, formation, "
                "email_saisi, telephone_saisi, raw) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    db_id[final.person_of[i]], source_id, rec.row, rec.extra.get("formation"),
                    _raw(rec, mapping, "email"), _raw(rec, mapping, "telephone"),
                    json.dumps(rec.raw, ensure_ascii=False, default=str),
                ),
            )
    return SaveReport(source_id, created, len(final.clusters) - created, len(records))


def list_persons(conn: sqlite3.Connection) -> list[tuple]:
    """Une ligne par personne : (n°, nom, prénom, sexe, emails, téléphones, nb d'inscriptions)."""
    return conn.execute(
        """
        SELECT p.id, p.nom, p.prenom, COALESCE(p.sexe, ''),
          COALESCE((SELECT group_concat(email, ' | ') FROM
                      (SELECT email FROM person_emails WHERE person_id = p.id
                       ORDER BY is_primary DESC, id)), ''),
          COALESCE((SELECT group_concat(phone, ' | ') FROM
                      (SELECT phone FROM person_phones WHERE person_id = p.id
                       ORDER BY is_primary DESC, id)), ''),
          (SELECT count(*) FROM registrations WHERE person_id = p.id)
        FROM persons p ORDER BY p.id
        """
    ).fetchall()


def person_registrations(conn: sqlite3.Connection, person_id: int) -> list[tuple]:
    """Formations d'une personne : (formation, fichier d'origine, email saisi, téléphone saisi)."""
    return conn.execute(
        """
        SELECT COALESCE(r.formation, ''), f.filename,
               COALESCE(r.email_saisi, ''), COALESCE(r.telephone_saisi, '')
        FROM registrations r JOIN source_files f ON f.id = r.source_file_id
        WHERE r.person_id = ? ORDER BY r.id
        """,
        (person_id,),
    ).fetchall()