from collections import defaultdict
from dataclasses import dataclass

from .dedupe import _blocking_keys
from .matching import Classification, Matcher, MatchResult
from .models import KnownPerson, NormalizedRecord

_ORDER = {Classification.CERTAIN: 2, Classification.PROBABLE: 1, Classification.NONE: 0}


def _rank(res: MatchResult) -> tuple[int, float]:
    return (_ORDER[res.classification], res.score)


class KnownIndex:
    """Index en mémoire des personnes connues : on ne compare qu'avec quelques candidats."""

    def __init__(self, persons: list[KnownPerson]):
        self.persons = persons
        self._blocks: dict[tuple, list[int]] = defaultdict(list)
        for k, p in enumerate(persons):
            for key in _blocking_keys(p):
                self._blocks[key].append(k)

    def candidates(self, record: NormalizedRecord) -> list[int]:
        found: set[int] = set()
        for key in _blocking_keys(record):
            found.update(self._blocks.get(key, ()))
        return sorted(found)


@dataclass
class GroupMatch:
    known_index: int | None      # position dans index.persons (None : aucune correspondance)
    record_index: int | None     # ligne du groupe qui a donné la meilleure correspondance
    result: MatchResult | None


def match_to_known(
    records: list[NormalizedRecord],
    groups: dict[int, list[int]],
    index: KnownIndex,
    matcher: Matcher | None = None,
) -> dict[int, GroupMatch]:
    """Cherche, pour chaque groupe de lignes (= une personne du fichier), la personne connue
    correspondante. On compare chaque ligne séparément et on garde la meilleure."""
    matcher = matcher or Matcher()
    out: dict[int, GroupMatch] = {}
    for number, members in groups.items():
        best: tuple[int, int, MatchResult] | None = None
        certain_known: set[int] = set()
        for i in members:
            for k in index.candidates(records[i]):
                res = matcher.compare_multi(records[i], index.persons[k])
                if res.classification == Classification.NONE:
                    continue
                if res.classification == Classification.CERTAIN:
                    certain_known.add(k)
                if best is None or _rank(res) > _rank(best[2]):
                    best = (i, k, res)
        if best is None:
            out[number] = GroupMatch(None, None, None)
            continue
        i, k, res = best
        if len(certain_known) > 1:
            # le groupe ressemble avec certitude à deux personnes déjà distinctes en base : à toi de voir
            res.classification = Classification.PROBABLE
            res.reasons.append("⚠ Ce groupe correspond aussi à une autre personne connue")
        out[number] = GroupMatch(k, i, res)
    return out