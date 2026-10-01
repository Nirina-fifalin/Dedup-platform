from dataclasses import dataclass, field


def _default_weights() -> dict[str, float]:
    return {
        "telephone": 0.30,
        "email": 0.25,
        "nom": 0.20,
        "prenom": 0.20,
        "sexe": 0.03,
        "tranche_age": 0.02,
    }


@dataclass(frozen=True)
class MatchConfig:
    """Poids et seuils : provisoires, à calibrer sur les données réelles (§12)."""
    weights: dict[str, float] = field(default_factory=_default_weights)
    certain_threshold: float = 0.90
    probable_threshold: float = 0.70
    email_similar_threshold: float = 0.85   # en dessous : email "différent"
    name_conflict_threshold: float = 0.60   # similarité moyenne des noms
    phone_near_score: float = 0.80

    