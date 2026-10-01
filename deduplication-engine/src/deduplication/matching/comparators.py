from rapidfuzz.distance import Levenshtein


def text_similarity(a: str | None, b: str | None) -> float | None:
    """Similarité 0..1 insensible à l'ordre des mots. None si une valeur manque."""
    if not a or not b:
        return None
    a = " ".join(sorted(a.split()))
    b = " ".join(sorted(b.split()))
    return Levenshtein.normalized_similarity(a, b)


def compare_names(a, b) -> tuple[float | None, float | None, bool]:
    """Retourne (score_nom, score_prenom, ordre_inverse)."""
    straight = (text_similarity(a.nom, b.nom), text_similarity(a.prenom, b.prenom))
    swapped = (text_similarity(a.nom, b.prenom), text_similarity(a.prenom, b.nom))

    def total(pair):
        return sum(x or 0.0 for x in pair)

    if total(swapped) > total(straight):
        return swapped[0], swapped[1], True
    return straight[0], straight[1], False


def compare_email(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    if a == b:
        return 1.0
    return Levenshtein.normalized_similarity(a, b)


def compare_exact(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return 1.0 if a == b else 0.0

