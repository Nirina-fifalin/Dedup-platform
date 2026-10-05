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
    decision: Literal["kept_separate", "postponed"]
    decided_by: str | None = None

