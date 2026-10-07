import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from deduplication import DedupResult, KnownPerson, NormalizedRecord
from deduplication.matching.comparators import compare_email, phone_distance

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


def load_known(conn: sqlite3.Connection) -> list[KnownPerson]:
    """Toutes les personnes de la base, avec tous leurs emails et téléphones."""
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


def save_analysis(
    conn: sqlite3.Connection,
    path: str | Path,
    records: list[NormalizedRecord],
    final: DedupResult,
    mapping: dict[str, str],
    attach: dict[int, int] | None = None,
) -> SaveReport:
    """Enregistre le résultat d'une analyse. Tout ou rien : une erreur n'écrit rien.

    attach : numéro de groupe -> id d'une personne déjà en base à laquelle le rattacher.
    """
    attach = attach or {}
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if conn.execute("SELECT 1 FROM source_files WHERE file_hash = ?", (digest,)).fetchone():
        raise AlreadySavedError(f"« {path.name} » a déjà été enregistré (même contenu).")

    now = _now()
    with conn:   # une seule transaction : validée à la fin, annulée en cas d'erreur
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