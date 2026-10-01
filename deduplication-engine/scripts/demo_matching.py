import csv
import itertools
import sys
from collections import Counter
from pathlib import Path

from deduplication import ColumnMapping, RecordNormalizer
from deduplication.matching import Classification, Matcher

ROOT = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "synthetic" / "inscriptions_demo.csv"

mapping = ColumnMapping(columns={
    "nom": "nom", "prenom": "prenom", "email": "email",
    "telephone": "telephone", "sexe": "sexe",
})
normalizer = RecordNormalizer(mapping)

with path.open(encoding="utf-8") as f:
    records = list(normalizer.normalize_rows(csv.DictReader(f)))
truth = {r.row: r.raw["_truth"] for r in records}

matcher = Matcher()
stats = Counter()
false_certain, missed, probables = [], [], []

for a, b in itertools.combinations(records, 2):
    res = matcher.compare(a, b)
    same = truth[a.row] == truth[b.row]
    stats[(res.classification.value, "same" if same else "diff")] += 1
    if res.classification == Classification.CERTAIN and not same:
        false_certain.append((a, b, res))
    elif res.classification == Classification.NONE and same:
        missed.append((a, b, res))
    elif res.classification == Classification.PROBABLE:
        probables.append((a, b, res, same))


def show(a, b, res):
    print(f"  L{a.row} {a.nom} {a.prenom} | {a.email} | {a.telephone}")
    print(f"  L{b.row} {b.nom} {b.prenom} | {b.email} | {b.telephone}")
    print(f"  score={res.score:.2f}  {' ; '.join(res.reasons)}\n")


print(f"{len(records)} inscriptions, {len(records) * (len(records) - 1) // 2} paires comparées\n")
print(f"{'classification':<12} {'même personne':>14} {'personnes différentes':>22}")
for cls in ("certain", "probable", "none"):
    print(f"{cls:<12} {stats[(cls, 'same')]:>14} {stats[(cls, 'diff')]:>22}")

print(f"\n=== FAUX POSITIFS 'certain' (doit être 0) : {len(false_certain)}")
for a, b, res in false_certain[:5]:
    show(a, b, res)

print(f"=== MANQUÉS (même personne classée 'none') : {len(missed)}")
for a, b, res in missed[:5]:
    show(a, b, res)

print(f"=== PROBABLES à valider : {len(probables)} (5 premiers)")
for a, b, res, same in probables[:5]:
    print(f"  [vérité : {'même personne' if same else 'personnes différentes'}]")
    show(a, b, res)

bad = [p for p in probables if not p[3]]
print(f"=== PROBABLES qui sont en réalité des personnes différentes : {len(bad)}")
for a, b, res, _ in bad[:5]:
    show(a, b, res)