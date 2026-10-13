import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from deduplication.normalization import (
    normalize_email, normalize_name, normalize_phone, split_emails, split_phones,
)

import store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class PersonDetails:
    id: int
    nom: str
    prenom: str
    sexe: str | None
    emails: list[str]
    phones: list[str]


@dataclass
class ParsedContacts:
    emails: list[str]
    phones: list[str]
    errors: list[str]
    suspected: list[tuple[str, str]]      # (email saisi, domaine proposé)


def parse_contacts(emails_text: str, phones_text: str) -> ParsedContacts:
    """Lit les zones de texte du formulaire : valeurs valides, erreurs, adresses suspectes."""
    emails: list[str] = []
    phones: list[str] = []
    errors: list[str] = []
    suspected: list[tuple[str, str]] = []
    for part in split_emails(emails_text):
        e = normalize_email(part)
        if not (e.is_valid and e.normalized):
            errors.append(f"Email incorrect : {part}")
            continue
        if e.suspected_domain:
            suspected.append((e.normalized, e.suspected_domain))
        if e.normalized not in emails:
            emails.append(e.normalized)
    for part in split_phones(phones_text):
        p = normalize_phone(part)
        if not (p.is_valid and p.normalized):
            errors.append(f"Téléphone incorrect : {part}")
            continue
        if p.normalized not in phones:
            phones.append(p.normalized)
    return ParsedContacts(emails, phones, errors, suspected)


def person_details(conn: sqlite3.Connection, person_id: int) -> PersonDetails:
    row = conn.execute(
        "SELECT nom, prenom, sexe FROM persons WHERE id = ?", (person_id,)
    ).fetchone()
    if row is None:
        raise LookupError("Personne introuvable")
    emails = [r[0] for r in conn.execute(
        "SELECT email FROM person_emails WHERE person_id = ? ORDER BY is_primary DESC, id", (person_id,)
    )]
    phones = [r[0] for r in conn.execute(
        "SELECT phone FROM person_phones WHERE person_id = ? ORDER BY is_primary DESC, id", (person_id,)
    )]
    return PersonDetails(person_id, row[0], row[1], row[2], emails, phones)


def update_person(
    conn: sqlite3.Connection, person_id: int, nom: str, prenom: str, sexe: str | None,
    emails: list[str], phones: list[str],
) -> list[str]:
    """Modifie une fiche. Retourne les champs modifiés. L'ancienne et la nouvelle valeur vont dans
    l'historique de la fiche ; le journal général ne reçoit que les noms des champs."""
    nom, prenom = nom.strip(), prenom.strip()
    if not nom or not prenom:
        raise ValueError("Le nom et le prénom sont obligatoires.")
    sexe = (sexe or "").strip() or None
    before = person_details(conn, person_id)

    changes: list[tuple[str, str, str]] = []
    if nom != before.nom:
        changes.append(("nom", before.nom, nom))
    if prenom != before.prenom:
        changes.append(("prénom", before.prenom, prenom))
    if sexe != before.sexe:
        changes.append(("sexe", before.sexe or "", sexe or ""))
    contacts_changed = False
    if emails != before.emails:
        changes.append(("emails", " | ".join(before.emails), " | ".join(emails)))
        contacts_changed = True
    if phones != before.phones:
        changes.append(("téléphones", " | ".join(before.phones), " | ".join(phones)))
        contacts_changed = True
    if not changes:
        return []

    status_before = store.contact_info(conn, person_id)[0]
    with conn:
        conn.execute(
            "UPDATE persons SET nom = ?, prenom = ?, nom_norm = ?, prenom_norm = ?, sexe = ?, "
            "contacts_locked = CASE WHEN ? THEN 1 ELSE contacts_locked END WHERE id = ?",
            (nom, prenom, normalize_name(nom), normalize_name(prenom), sexe,
             int(contacts_changed), person_id),
        )
        if contacts_changed:
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
        store.sync_suppression(conn)
        if store.contact_info(conn, person_id)[0] != status_before:
            changes.append(("contact", "contactable",
                            "ne pas contacter (adresse de la liste d'opposition)"))
        now = _now()
        for field, old, new in changes:
            conn.execute(
                "INSERT INTO edit_history (person_id, at, field, old_value, new_value) "
                "VALUES (?, ?, ?, ?, ?)",
                (person_id, now, field, old, new),
            )
        store.log_action(
            conn, "modification_personne",
            f"personne n° {person_id} : {', '.join(c[0] for c in changes)}",
        )
    return [c[0] for c in changes]


def shared_contacts(conn: sqlite3.Connection, person_id: int) -> set[tuple[str, str, int, str]]:
    """Emails/téléphones de cette fiche qui figurent aussi sur une autre :
    (type, valeur, n° de l'autre fiche, nom complet)."""
    found: set[tuple[str, str, int, str]] = set()
    for kind, table, column in (("email", "person_emails", "email"),
                                ("téléphone", "person_phones", "phone")):
        rows = conn.execute(
            f"SELECT o.{column}, p.id, p.nom, p.prenom FROM {table} m "
            f"JOIN {table} o ON o.{column} = m.{column} AND o.person_id != m.person_id "
            f"JOIN persons p ON p.id = o.person_id WHERE m.person_id = ?",
            (person_id,),
        )
        for value, pid, nom, prenom in rows:
            found.add((kind, value, pid, f"{nom} {prenom}"))
    return found


def edit_history(conn: sqlite3.Connection, person_id: int) -> list[tuple[str, str, str, str]]:
    """(date, champ, ancienne valeur, nouvelle valeur), du plus récent au plus ancien."""
    return conn.execute(
        "SELECT at, field, COALESCE(old_value, ''), COALESCE(new_value, '') "
        "FROM edit_history WHERE person_id = ? ORDER BY id DESC",
        (person_id,),
    ).fetchall()