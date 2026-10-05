from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import (
    MatchResultRecord, Person, PersonEmail, PersonMerge, PersonPhone, Registration,
)


class MergeNotAllowed(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _move_contacts(session: Session, source: Person, target: Person, collection: str, attr: str):
    """Déplace emails/téléphones de source vers target.

    Retourne (déplacés, supprimés-car-déjà-présents) pour pouvoir annuler.
    """
    tgt_items = getattr(target, collection)
    known = {getattr(i, attr) for i in tgt_items}
    has_primary = any(i.is_primary for i in tgt_items)
    moved, dropped = [], []
    for item in list(getattr(source, collection)):
        value = getattr(item, attr)
        if value in known:
            dropped.append({
                attr: value, "is_primary": item.is_primary,
                "first_seen_registration_id": item.first_seen_registration_id,
            })
            session.delete(item)
            continue
        moved.append({"id": item.id, "was_primary": item.is_primary})
        item.person = target
        item.is_primary = item.is_primary and not has_primary
        has_primary = has_primary or item.is_primary
        known.add(value)
    return moved, dropped


def merge_persons(
    session: Session,
    source_id: int,
    target_id: int,
    performed_by: str | None = None,
    case: MatchResultRecord | None = None,
) -> PersonMerge:
    """Absorbe `source` dans `target`. Ne fait pas de commit (c'est l'appelant qui décide)."""
    if source_id == target_id:
        raise MergeNotAllowed("Impossible de fusionner une personne avec elle-même")

    # Verrou dans un ordre stable pour éviter les blocages entre deux fusions simultanées
    people = {pid: session.get(Person, pid, with_for_update=True)
              for pid in sorted((source_id, target_id))}
    source, target = people[source_id], people[target_id]
    if source is None or target is None:
        raise LookupError("Personne introuvable")
    if source.merged_into_id is not None:
        raise MergeNotAllowed(f"La personne {source.id} a déjà été fusionnée")
    if target.merged_into_id is not None:
        raise MergeNotAllowed(f"La personne cible {target.id} a déjà été fusionnée dans une autre")

    reg_ids = list(session.scalars(
        select(Registration.id).where(Registration.person_id == source.id)
    ))
    session.execute(
        update(Registration).where(Registration.person_id == source.id).values(person_id=target.id)
    )
    emails_moved, emails_dropped = _move_contacts(session, source, target, "emails", "email")
    phones_moved, phones_dropped = _move_contacts(session, source, target, "phones", "phone")

    sexe_set = target.sexe is None and source.sexe is not None
    if sexe_set:
        target.sexe = source.sexe

    source.merged_into_id = target.id
    merge = PersonMerge(
        source_person_id=source.id, target_person_id=target.id,
        case_id=case.id if case else None, performed_by=performed_by,
        snapshot={
            "registrations": reg_ids,
            "emails_moved": emails_moved, "emails_dropped": emails_dropped,
            "phones_moved": phones_moved, "phones_dropped": phones_dropped,
            "sexe_set": sexe_set,
        },
    )
    session.add(merge)
    if case is not None:
        case.status = "merged"
        case.decided_by = performed_by
        case.decided_at = _now()
    session.flush()
    return merge


def _collect(session: Session, model, entries: list[dict], target_id: int):
    items = []
    for e in entries:
        item = session.get(model, e["id"])
        if item is None or item.person_id != target_id:
            raise MergeNotAllowed("Des contacts ont été modifiés depuis la fusion")
        items.append((item, e["was_primary"]))
    return items


def undo_merge(session: Session, merge_id: int, undone_by: str | None = None) -> PersonMerge:
    """Annule une fusion. Toutes les vérifications ont lieu AVANT la première modification."""
    m = session.get(PersonMerge, merge_id)
    if m is None:
        raise LookupError("Fusion introuvable")
    if m.undone_at is not None:
        raise MergeNotAllowed("Cette fusion a déjà été annulée")

    source = session.get(Person, m.source_person_id, with_for_update=True)
    target = session.get(Person, m.target_person_id, with_for_update=True)
    if source is None or target is None:
        raise LookupError("Personne introuvable")
    if target.merged_into_id is not None:
        raise MergeNotAllowed(
            f"La personne cible {target.id} a elle-même été fusionnée : annuler d'abord cette fusion"
        )
    if source.merged_into_id != target.id:
        raise MergeNotAllowed("L'état actuel ne correspond plus à cette fusion")

    snap = m.snapshot
    still_there = set(session.scalars(
        select(Registration.id).where(
            Registration.id.in_(snap["registrations"]), Registration.person_id == target.id
        )
    ))
    if still_there != set(snap["registrations"]):
        raise MergeNotAllowed("Des inscriptions ont été déplacées depuis la fusion")
    emails = _collect(session, PersonEmail, snap["emails_moved"], target.id)
    phones = _collect(session, PersonPhone, snap["phones_moved"], target.id)

    # --- Vérifications passées : on restaure
    session.execute(
        update(Registration).where(Registration.id.in_(snap["registrations"]))
        .values(person_id=source.id)
    )
    for item, was_primary in (*emails, *phones):
        item.person = source
        item.is_primary = was_primary
    for d in snap["emails_dropped"]:
        session.add(PersonEmail(person_id=source.id, **d))
    for d in snap["phones_dropped"]:
        session.add(PersonPhone(person_id=source.id, **d))
    if snap["sexe_set"]:
        target.sexe = None
    source.merged_into_id = None

    m.undone_at = _now()
    m.undone_by = undone_by
    if m.case_id is not None:
        case = session.get(MatchResultRecord, m.case_id)
        if case is not None and case.status == "merged":
            case.status = "pending"
            case.decided_at = None
            case.decided_by = None
    session.flush()
    return m