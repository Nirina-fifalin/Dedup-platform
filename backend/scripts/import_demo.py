import sys
from collections import defaultdict
from pathlib import Path

from deduplication import ColumnMapping
from sqlalchemy import select

from app.db import SessionLocal
from app.models import MatchResultRecord, Registration
from app.services.importer import AlreadyImportedError, import_file

ROOT = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "synthetic" / "inscriptions_demo_hard.csv"

mapping = ColumnMapping(columns={
    "nom": "nom", "prenom": "prenom", "email": "email", "telephone": "telephone",
    "sexe": "sexe", "formation": "formation", "annee": "annee",
})

with SessionLocal() as s:
    try:
        report = import_file(s, path, mapping)
    except AlreadyImportedError as e:
        print(e)
        sys.exit(1)
    print(report)

    regs = s.execute(
        select(Registration.id, Registration.person_id, Registration.raw)
        .where(Registration.source_file_id == report.source_file_id)
    ).all()
    flagged = s.execute(
        select(MatchResultRecord.person_a_id, MatchResultRecord.person_b_id)
        .where(MatchResultRecord.registration_id.in_([r.id for r in regs]))
    ).all()

    truths_of_person = defaultdict(set)
    persons_of_truth = defaultdict(set)
    for _, pid, raw in regs:
        t = raw.get("_truth")
        truths_of_person[pid].add(t)
        persons_of_truth[t].add(pid)

    # Personnes distinctes fusionnées à tort (doit être 0)
    wrong_merges = [pid for pid, ts in truths_of_person.items() if len(ts) > 1]

    # Même personne éclatée en plusieurs : couverte par un cas à valider, ou silencieuse ?
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in flagged:
        parent[find(a)] = find(b)
    silent = [
        t for t, pids in persons_of_truth.items()
        if len(pids) > 1 and len({find(p) for p in pids}) > 1
    ]

    print(f"\nPersonnes en base (cette source)       : {len(truths_of_person)}")
    print(f"Personnes réelles dans le fichier      : {len(persons_of_truth)}")
    print(f"Fusions erronées (doit être 0)         : {len(wrong_merges)}")
    print(f"Doublons NON signalés (à minimiser)    : {len(silent)}")