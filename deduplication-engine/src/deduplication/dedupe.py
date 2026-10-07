from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .matching import Classification, Matcher, MatchResult
from .models import NormalizedRecord


@dataclass
class DedupResult:
    person_of: list[int]                         # numéro de personne de chaque ligne
    clusters: dict[int, list[int]]               # numéro de personne -> positions des lignes
    review: list[tuple[int, int, MatchResult]]   # paires "probables" à valider


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(b)] = self.find(a)


def _build(n: int, uf: _UnionFind, candidates: list[tuple[int, int, MatchResult]]) -> DedupResult:
    numbers: dict[int, int] = {}
    person_of: list[int] = []
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        num = numbers.setdefault(uf.find(i), len(numbers) + 1)
        person_of.append(num)
        clusters[num].append(i)
    # une paire déjà réunie par d'autres correspondances n'a plus besoin d'être vérifiée
    review = [(i, j, res) for i, j, res in candidates if uf.find(i) != uf.find(j)]
    return DedupResult(person_of, dict(clusters), review)


def _blocking_keys(r: Any) -> set[tuple]:
    keys: set[tuple] = set()
    for e in r.emails:
        keys.add(("email", e))
    for p in r.phones:
        keys.add(("tel", p))
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

    uf = _UnionFind(len(records))
    probable: list[tuple[int, int, MatchResult]] = []
    for i, j in sorted(pairs):
        res = matcher.compare_multi(records[i], records[j])
        if res.classification == Classification.CERTAIN:
            uf.union(i, j)
        elif res.classification == Classification.PROBABLE:
            probable.append((i, j, res))

    return _build(len(records), uf, probable)


def apply_same(result: DedupResult, same_pairs: Iterable[tuple[int, int]]) -> DedupResult:
    """Réunit les personnes dont un humain a confirmé qu'il s'agit de la même."""
    n = len(result.person_of)
    uf = _UnionFind(n)
    for members in result.clusters.values():
        for m in members[1:]:
            uf.union(members[0], m)
    for i, j in same_pairs:
        uf.union(i, j)
    return _build(n, uf, result.review)