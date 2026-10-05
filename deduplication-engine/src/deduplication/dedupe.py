from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from .matching import Classification, Matcher, MatchResult
from .models import NormalizedRecord


@dataclass
class DedupResult:
    person_of: list[int]                         # numéro de personne de chaque ligne
    clusters: dict[int, list[int]]               # numéro de personne -> positions des lignes
    review: list[tuple[int, int, MatchResult]]   # paires "probables" à valider


def _blocking_keys(r: NormalizedRecord) -> set[tuple]:
    keys: set[tuple] = set()
    if r.email:
        keys.add(("email", r.email))
    if r.telephone:
        keys.add(("tel", r.telephone))
    if r.nom and r.prenom:
        # insensible à l'ordre nom/prénom, tolère une faute après le 3e caractère
        keys.add(("nom", *sorted((r.nom[:3], r.prenom[:3]))))
    return keys


def deduplicate(records: list[NormalizedRecord], matcher: Matcher | None = None) -> DedupResult:
    matcher = matcher or Matcher()

    blocks: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        for key in _blocking_keys(r):
            blocks[key].append(i)

    pairs: set[tuple[int, int]] = set()
    for members in blocks.values():
        pairs.update(combinations(members, 2))

    parent = list(range(len(records)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    probable: list[tuple[int, int, MatchResult]] = []
    for i, j in sorted(pairs):
        res = matcher.compare(records[i], records[j])
        if res.classification == Classification.CERTAIN:
            parent[find(j)] = find(i)
        elif res.classification == Classification.PROBABLE:
            probable.append((i, j, res))

    numbers: dict[int, int] = {}
    person_of: list[int] = []
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        n = numbers.setdefault(find(i), len(numbers) + 1)
        person_of.append(n)
        clusters[n].append(i)

    # une paire déjà réunie par d'autres correspondances n'a plus besoin d'être vérifiée
    review = [(i, j, res) for i, j, res in probable if find(i) != find(j)]
    return DedupResult(person_of, dict(clusters), review)