from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..deps import get_current_user, get_session
from ..models import MatchResultRecord, Person, Registration, User
from ..schemas import DecisionIn, PersonSummary, ReviewCase
from ..services.merge import MergeNotAllowed, merge_persons

router = APIRouter(prefix="/review", tags=["review"])


def _summary(session: Session, person_id: int | None) -> PersonSummary | None:
    if person_id is None:
        return None
    p = session.scalar(
        select(Person).where(Person.id == person_id)
        .options(selectinload(Person.emails), selectinload(Person.phones))
    )
    if p is None:
        return None
    n = session.scalar(
        select(func.count()).select_from(Registration).where(Registration.person_id == p.id)
    )
    return PersonSummary(
        id=p.id, nom=p.nom, prenom=p.prenom, sexe=p.sexe,
        emails=[e.email for e in p.emails], phones=[x.phone for x in p.phones],
        registrations=n or 0,
    )


def _case(session: Session, c: MatchResultRecord) -> ReviewCase:
    person_a = _summary(session, c.person_a_id)
    assert person_a is not None
    return ReviewCase(
        id=c.id, status=c.status, score=c.score, classification=c.classification,
        reasons=c.reasons or [], conflicts=c.conflicts or [],
        registration_id=c.registration_id, created_at=c.created_at,
        decided_at=c.decided_at, decided_by=c.decided_by,
        person_a=person_a, person_b=_summary(session, c.person_b_id),
    )


@router.get("", response_model=list[ReviewCase])
def list_cases(
    status: str = "pending",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    rows = session.scalars(
        select(MatchResultRecord).where(MatchResultRecord.status == status)
        .order_by(MatchResultRecord.score.desc(), MatchResultRecord.id)
        .limit(limit).offset(offset)
    ).all()
    return [_case(session, c) for c in rows]


@router.get("/{case_id}", response_model=ReviewCase)
def get_case(case_id: int, session: Session = Depends(get_session)):
    c = session.get(MatchResultRecord, case_id)
    if c is None:
        raise HTTPException(404, "Cas introuvable")
    return _case(session, c)


@router.post("/{case_id}/decision", response_model=ReviewCase)
def decide(case_id: int, body: DecisionIn, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    c = session.get(MatchResultRecord, case_id)
    if c is None:
        raise HTTPException(404, "Cas introuvable")
    if c.status not in ("pending", "postponed"):
        raise HTTPException(409, f"Cas déjà décidé : {c.status}")

    if body.decision == "merged":
        if c.person_b_id is None:
            raise HTTPException(422, "Ce cas n'a pas de personne existante avec laquelle fusionner")
        try:
            merge_persons(session, c.person_a_id, c.person_b_id,
                          performed_by=user.email, case=c)
        except MergeNotAllowed as e:
            session.rollback()
            raise HTTPException(409, str(e))
    else:
        c.status = body.decision
        c.decided_by = user.email
        c.decided_at = datetime.now(timezone.utc)

    session.commit()
    return _case(session, c)