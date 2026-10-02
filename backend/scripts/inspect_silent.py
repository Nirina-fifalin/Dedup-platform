from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.models import MatchResultRecord, Person, Registration, SourceFile

with SessionLocal() as s:
    source_id = s.scalar(
        select(SourceFile.id).where(SourceFile.status == "done").order_by(SourceFile.id.desc())
    )
    regs = s.scalars(
        select(Registration).where(Registration.source_file_id == source_id)
        .options(selectinload(Registration.person).selectinload(Person.emails),
                 selectinload(Registration.person).selectinload(Person.phones))
    ).all()
    flagged = s.execute(
        select(MatchResultRecord.person_a_id, MatchResultRecord.person_b_id)
        .where(MatchResultRecord.registration_id.in_([r.id for r in regs]))
    ).all()

    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in flagged:
        parent[find(a)] = find(b)

    by_truth = defaultdict(list)
    for r in regs:
        by_truth[r.raw.get("_truth")].append(r)

    for truth, rs in by_truth.items():
        pids = {r.person_id for r in rs}
        if len(pids) > 1 and len({find(p) for p in pids}) > 1:
            print(f"Personne réelle #{truth} éclatée en {len(pids)} personnes SANS signalement :")
            for r in sorted(rs, key=lambda r: r.source_row):
                print(f"  ligne {r.source_row:>3} → Person {r.person_id:<4} "
                      f"{r.nom_submitted} {r.prenom_submitted} | {r.email_submitted} | {r.phone_submitted}")
