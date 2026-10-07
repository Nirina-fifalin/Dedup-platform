from dataclasses import dataclass, field


@dataclass(frozen=True)
class Correction:
    """Une valeur modifiée par la normalisation (trace pour l'export)."""
    row: int
    field: str
    original: str
    normalized: str | None


@dataclass(frozen=True)
class Issue:
    """Un problème de qualité détecté (rien n'est corrigé automatiquement)."""
    row: int
    field: str
    code: str
    message: str


@dataclass
class NormalizedRecord:
    row: int
    nom: str
    prenom: str
    email: str | None
    telephone: str | None
    extra: dict[str, str | None] = field(default_factory=dict)  # ville, sexe, formation...
    raw: dict = field(default_factory=dict)                     # ligne d'origine, intacte
    corrections: list[Correction] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)   # tous les emails valides de la ligne
    phones: list[str] = field(default_factory=list)   # tous les téléphones (E.164)


@dataclass
class KnownPerson:
    """Une personne déjà connue, avec toutes ses valeurs historiques."""
    id: object
    nom: str 
    prenom: str
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)   # E.164
    extra: dict[str, str | None] = field(default_factory=dict)


