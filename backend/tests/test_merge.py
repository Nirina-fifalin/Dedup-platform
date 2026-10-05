import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Person, PersonEmail, PersonPhone, Registration
from app.services.merge import MergeNotAllowed, merge_persons, undo_merge


@pytest.fixture
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def make_person(session, prenom, emails=(), phones=(), n_regs=1, sexe=None):
    p = Person(nom="Mergetest", prenom=prenom, nom_norm="mergetest",
               prenom_norm=prenom.lower(), sexe=sexe)
    p.emails = [PersonEmail(email=e, is_primary=(i == 0)) for i, e in enumerate(emails)]
    p.phones = [PersonPhone(phone=x, is_primary=(i == 0)) for i, x in enumerate(phones)]
    session.add(p)
    session.flush()
    for _ in range(n_regs):
        session.add(Registration(person_id=p.id))
    session.flush()
    return p


def emails_of(session, pid):
    return set(session.scalars(select(PersonEmail.email).where(PersonEmail.person_id == pid)))


def phones_of(session, pid):
    return set(session.scalars(select(PersonPhone.phone).where(PersonPhone.person_id == pid)))


def reg_count(session, pid):
    return session.scalar(
        select(func.count()).select_from(Registration).where(Registration.person_id == pid)
    )


def test_merge_moves_everything_and_undo_restores(session):
    a = make_person(session, "A", ["shared@example.test", "a@example.test"], ["+261340000001"], n_regs=2)
    b = make_person(session, "B", ["shared@example.test", "b@example.test"], ["+261340000002"],
                    n_regs=1, sexe="F")

    m = merge_persons(session, source_id=b.id, target_id=a.id, performed_by="test")

    assert b.merged_into_id == a.id
    assert (reg_count(session, a.id), reg_count(session, b.id)) == (3, 0)
    assert emails_of(session, a.id) == {"shared@example.test", "a@example.test", "b@example.test"}
    assert emails_of(session, b.id) == set()
    assert phones_of(session, a.id) == {"+261340000001", "+261340000002"}
    assert a.sexe == "F"

    undo_merge(session, m.id, undone_by="test")

    assert b.merged_into_id is None
    assert (reg_count(session, a.id), reg_count(session, b.id)) == (2, 1)
    assert emails_of(session, a.id) == {"shared@example.test", "a@example.test"}
    assert emails_of(session, b.id) == {"shared@example.test", "b@example.test"}
    assert phones_of(session, b.id) == {"+261340000002"}
    primary_b = session.scalar(
        select(PersonEmail.email).where(PersonEmail.person_id == b.id, PersonEmail.is_primary)
    )
    assert primary_b == "shared@example.test"
    assert a.sexe is None


def test_cannot_merge_with_self_or_into_merged_person(session):
    a, b, c = (make_person(session, n) for n in "ABC")
    with pytest.raises(MergeNotAllowed):
        merge_persons(session, a.id, a.id)
    merge_persons(session, b.id, a.id)
    with pytest.raises(MergeNotAllowed):
        merge_persons(session, c.id, b.id)      # cible déjà absorbée
    with pytest.raises(MergeNotAllowed):
        merge_persons(session, b.id, c.id)      # source déjà absorbée


def test_chained_merges_must_be_undone_in_reverse_order(session):
    a, b, c = (make_person(session, n) for n in "ABC")
    m_cb = merge_persons(session, c.id, b.id)
    m_ba = merge_persons(session, b.id, a.id)
    assert reg_count(session, a.id) == 3

    with pytest.raises(MergeNotAllowed):
        undo_merge(session, m_cb.id)            # b est lui-même absorbé

    undo_merge(session, m_ba.id)
    undo_merge(session, m_cb.id)
    assert [reg_count(session, p.id) for p in (a, b, c)] == [1, 1, 1]
    assert all(p.merged_into_id is None for p in (a, b, c))


def test_undo_twice_is_rejected(session):
    a, b = make_person(session, "A"), make_person(session, "B")
    m = merge_persons(session, b.id, a.id)
    undo_merge(session, m.id)
    with pytest.raises(MergeNotAllowed):
        undo_merge(session, m.id)

