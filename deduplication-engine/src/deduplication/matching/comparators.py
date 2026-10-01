from rapidfuzz.distance import DamerauLevenshtein, Levenshtein


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
    """1.0 identique ; ~0.9 faute de frappe ; <= 0.5 différent.

    On compare séparément la partie locale et le domaine : un domaine ou un
    nom de famille commun ne doit pas masquer un prénom différent.
    """
    if not a or not b:
        return None
    if a == b:
        return 1.0
    la, _, da = a.partition("@")
    lb, _, db = b.partition("@")
    local_sim = DamerauLevenshtein.normalized_similarity(la, lb)
    domain_sim = DamerauLevenshtein.normalized_similarity(da, db)
    combined = 0.8 * local_sim + 0.2 * domain_sim
    if local_sim >= 0.90 and domain_sim >= 0.75:
        return combined
    return min(combined, 0.5)


def compare_exact(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return 1.0 if a == b else 0.0

def phone_distance(a: str | None, b: str | None) -> int | None:
    """0 = identique, 1 = une faute de frappe, 2 = différent. None si absent."""
    if not a or not b:
        return None
    if a == b:
        return 0
    if min(len(a), len(b)) >= 8 and DamerauLevenshtein.distance(a, b) <= 1:
        return 1
    return 2