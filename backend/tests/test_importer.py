import pytest
from deduplication import ColumnMapping
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Formation, MatchResultRecord, Registration
from app.services.importer import import_file

MAPPING = ColumnMapping(columns={
    "nom": "nom", "prenom": "prenom", "email": "email",
    "telephone": "telephone", "formation": "formation", "annee": "annee",
})

CSV = """nom,prenom,email,telephone,formation,annee
Testnom,Alpha,alpha.testnom@example.test,0349900001,Excel,2024
TESTNOM,Alpha,alpha.testnom@exmple.test,034 99 000 01,Python,2025
Testnom,Beta,beta.testnom@example.test,0349900002,IA,2026
Testnom,Alpha,alpha.testnom@example.test,0349900099,Data,2026
,,,,Excel,2024
"""


@pytest.fixture
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_import_creates_persons_registrations_and_review_cases(session, tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(CSV, encoding="utf-8")

    report = import_file(session, f, MAPPING, commit=False)

    assert report.rows == 5
    assert report.skipped == 1
    assert report.new_persons == 3          # Alpha, Beta, Alpha provisoire
    assert report.matched_existing == 1     # ligne 2 rattachée à Alpha
    assert report.to_review == 1            # ligne 4 : téléphone en conflit

    regs = session.scalars(
        select(Registration).where(Registration.source_file_id == report.source_file_id)
    ).all()
    assert len(regs) == 4
    assert len({r.person_id for r in regs}) == 3

    # La ligne 2 garde ce qui a été saisi, y compris la faute de domaine
    line2 = next(r for r in regs if r.source_row == 3)
    assert line2.email_submitted == "alpha.testnom@exmple.test"
    assert line2.person_id == next(r for r in regs if r.source_row == 2).person_id

    # La faute de domaine n'a pas créé un second email pour la personne
    assert len(line2.person.emails) == 1

    cases = session.scalars(
        select(MatchResultRecord).where(MatchResultRecord.registration_id.in_([r.id for r in regs]))
    ).all()
    assert len(cases) == 1
    assert cases[0].status == "pending"
    assert "telephone_conflict" in cases[0].conflicts

    assert session.scalar(
        select(func.count()).select_from(Formation).where(Formation.nom == "Excel 2024")
    ) == 1

CSV_TYPO = """nom,prenom,email,telephone
Testrako,Lalaina,lalaina.testrako@example.test,0349911119
Testrakoo,Lalaina,lalaina.testrako@exmple.test,034 99 111 29
"""


def test_typo_in_name_email_and_phone_is_flagged_for_review(session, tmp_path):
    f = tmp_path / "typo.csv"
    f.write_text(CSV_TYPO, encoding="utf-8")

    report = import_file(session, f, MAPPING, commit=False)

    assert report.new_persons == 2      # pas de fusion automatique
    assert report.to_review == 1        # mais le cas est signalé