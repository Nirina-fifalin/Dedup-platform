import os
import sys
from pathlib import Path

APP_NAME = "DeduplicationInscriptions"


def is_frozen() -> bool:
    """Vrai quand l'application tourne sous forme de .exe."""
    return bool(getattr(sys, "frozen", False))


def data_dir() -> Path:
    """Dossier permanent des données : base, sauvegardes, colonnes mémorisées, journal d'erreurs."""
    override = os.environ.get("DEDUP_DATA_DIR")      # pour tester sans toucher aux vraies données
    if override:
        return Path(override)
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path(__file__).resolve().parent / "data"