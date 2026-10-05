from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_session
from ..models import PersonMerge
from ..schemas import MergeOut, UndoIn
from ..services.merge import MergeNotAllowed, undo_merge

router = APIRouter(prefix="/merges", tags=["merges"])


def _out(m: PersonMerge) -> MergeOut:
    s = m.snapshot
    return MergeOut(
        id=m.id, source_person_id=m.source_person_id, target_person_id=m.target_person_id,
        case_id=m.case_id, performed_at=m.performed_at, performed_by=m.performed_by,
        undone_at=m.undone_at, undone_by=m.undone_by,
        registrations_moved=len(s.get("registrations", [])),
        emails_moved=len(s.get("emails_moved", [])),
        phones_moved=len(s.get("phones_moved", [])),
    )


@router.get("", response_model=list[MergeOut])
def list_merges(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    rows = session.scalars(
        select(PersonMerge).order_by(PersonMerge.id.desc()).limit(limit).offset(offset)
    ).all()
    return [_out(m) for m in rows]


@router.post("/{merge_id}/undo", response_model=MergeOut)
def undo(merge_id: int, body: UndoIn, session: Session = Depends(get_session)):
    try:
        m = undo_merge(session, merge_id, undone_by=body.undone_by)
    except LookupError as e:
        session.rollback()
        raise HTTPException(404, str(e))
    except MergeNotAllowed as e:
        session.rollback()
        raise HTTPException(409, str(e))
    session.commit()
    return _out(m)

