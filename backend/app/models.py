from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String,
    UniqueConstraint, func, Text, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    report: Mapped[dict | None] = mapped_column(JSONB)


class Formation(Base):
    __tablename__ = "formations"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200))
    date_debut: Mapped[date | None] = mapped_column(Date)
    date_fin: Mapped[date | None] = mapped_column(Date)


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (
        Index("ix_persons_names_norm", "nom_norm", "prenom_norm"),
        Index(
            "ix_persons_nom_trgm", "nom_norm",
            postgresql_using="gin", postgresql_ops={"nom_norm": "gin_trgm_ops"},
        ),
        Index(
            "ix_persons_prenom_trgm", "prenom_norm",
            postgresql_using="gin", postgresql_ops={"prenom_norm": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200))
    prenom: Mapped[str] = mapped_column(String(200))
    nom_norm: Mapped[str] = mapped_column(String(200))
    prenom_norm: Mapped[str] = mapped_column(String(200))
    sexe: Mapped[str | None] = mapped_column(String(10))
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    emails: Mapped[list["PersonEmail"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    phones: Mapped[list["PersonPhone"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    registrations: Mapped[list["Registration"]] = relationship(back_populates="person")


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    formation_id: Mapped[int | None] = mapped_column(ForeignKey("formations.id"), index=True)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"), index=True)
    source_row: Mapped[int | None] = mapped_column(Integer)
    date_inscription: Mapped[date | None] = mapped_column(Date)
    # valeurs telles que saisies ce jour-là (jamais écrasées)
    nom_submitted: Mapped[str | None] = mapped_column(String(200))
    prenom_submitted: Mapped[str | None] = mapped_column(String(200))
    email_submitted: Mapped[str | None] = mapped_column(String(320))
    phone_submitted: Mapped[str | None] = mapped_column(String(50))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    person: Mapped["Person"] = relationship(back_populates="registrations")


class PersonEmail(Base):
    __tablename__ = "person_emails"
    __table_args__ = (UniqueConstraint("person_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id"))

    person: Mapped["Person"] = relationship(back_populates="emails")


class PersonPhone(Base):
    __tablename__ = "person_phones"
    __table_args__ = (UniqueConstraint("person_id", "phone"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)   # E.164
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id"))

    person: Mapped["Person"] = relationship(back_populates="phones")


class MatchResultRecord(Base):
    """Cas soumis à validation humaine, et leur décision (§19)."""
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id"))
    person_a_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    person_b_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    classification: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    conflicts: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(100))


class PersonMerge(Base):
    """Journal des fusions, avec de quoi les annuler (§17, §37)."""
    __tablename__ = "person_merges"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    target_person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("match_results.id"))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    performed_by: Mapped[str | None] = mapped_column(String(100))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by: Mapped[str | None] = mapped_column(String(100))
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)


class ImportLogEntry(Base):
    """Corrections de normalisation et problèmes de données, par ligne (§21)."""
    __tablename__ = "import_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    source_row: Mapped[int | None] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20))
    original: Mapped[str | None] = mapped_column(Text)
    normalized: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str | None] = mapped_column(Text)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'reviewer')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())