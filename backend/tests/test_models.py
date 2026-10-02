import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import (
    Formation, Person, PersonEmail, PersonPhone, Registration, SourceFile,
)


@pytest.fixture
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_one_person_many_registrations_and_two_emails(session):
    source = SourceFile(filename="demo.csv", row_count=3, status="done")
    formations = [Formation(nom=n) for n in ("Excel", "Python", "IA")]
    person = Person(nom="Rakoto", prenom="Jean", nom_norm="rakoto", prenom_norm="jean")
    person.emails = [
        PersonEmail(email="jean.rakoto@gmail.com", is_primary=True),
        PersonEmail(email="jean92@gmail.com"),
    ]
    person.phones = [PersonPhone(phone="+261341234567", is_primary=True)]
    session.add_all([source, *formations, person])
    session.flush()

    for f in formations:
        session.add(Registration(
            person_id=person.id, formation_id=f.id, source_file_id=source.id,
            email_submitted="jean.rakoto@gmail.com", raw={"nom": "Rakoto"},
        ))
    session.flush()

    count = session.scalar(
        select(func.count()).select_from(Registration).where(Registration.person_id == person.id)
    )
    assert count == 3
    assert len(person.emails) == 2
    