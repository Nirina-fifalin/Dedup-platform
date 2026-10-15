import os
import sys
from pathlib import Path

APP_NAME = "DeduplicationInscriptions"


def is_frozen() -> bool:
    """Vrai quand l'application tourne sous forme de .exe."""
    return bool(getattr(sys, "frozen", False))


def data_dir() -> Path:
    """Dossier permanent des données : base, sauvegardes, colonnes mémorisées, journal d'erreurs.
    Le développement a son propre dossier : les données de test ne se mélangent jamais aux vraies."""
    override = os.environ.get("DEDUP_DATA_DIR")      # pour tester sans toucher aux vraies données
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / (APP_NAME if is_frozen() else APP_NAME + "-dev")