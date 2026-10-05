from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ImportReportOut(BaseModel):
    source_file_id: int
    rows: int
    new_persons: int
    matched_existing: int
    to_review: int
    skipped: int
    issues: dict[str, int]


class SourceFileOut(BaseModel):
    id: int
    filename: str
    imported_at: datetime
    row_count: int
    status: str
    report: dict | None


class PersonSummary(BaseModel):
    id: int
    nom: str
    prenom: str
    sexe: str | None
    emails: list[str]
    phones: list[str]
    registrations: int


class ReviewCase(BaseModel):
    id: int
    status: str
    score: float
    classification: str
    reasons: list[str]
    conflicts: list[str]
    registration_id: int | None
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    person_a: PersonSummary
    person_b: PersonSummary | None 


class DecisionIn(BaseModel):
    decision: Literal["kept_separate", "postponed", "merged"]
    decided_by: str | None = None


class UndoIn(BaseModel):
    undone_by: str | None = None


class MergeOut(BaseModel):
    id: int
    source_person_id: int
    target_person_id: int
    case_id: int | None
    performed_at: datetime
    performed_by: str | None
    undone_at: datetime | None
    undone_by: str | None
    registrations_moved: int
    emails_moved: int
    phones_moved: int

