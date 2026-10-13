import sqlite3
from contextlib import closing
from datetime import datetime

import store

ACTION_LABELS = {
    "import_fichier": "Fichier enregistré",
    "remplacement_fichier": "Fichier remplacé",
    "suppression_fichier": "Fichier supprimé",
    "suppression_personne": "Personne supprimée",
    "modification_personne": "Fiche modifiée",
    "ne_plus_contacter": "Ne plus contacter",
    "contact_reautorise": "Contact réautorisé",
    "restauration": "Base restaurée",
    "export_liste": "Liste exportée",
    "export_fichier_nettoye": "Fichier nettoyé exporté",
    "sauvegarde_manuelle": "Sauvegarde manuelle",
}


def fmt_datetime(iso: str) -> str:
    """Date et heure locales (le journal est enregistré en UTC)."""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def record_action(action: str, detail: str) -> None:
    """Note une action au journal (ouvre sa propre connexion). Jamais de données personnelles."""
    with closing(store.connect()) as conn:
        with conn:
            store.log_action(conn, action, detail)


def list_audit(conn: sqlite3.Connection, limit: int = 2000) -> list[tuple[str, str, str]]:
    """(date, action, détail), de la plus récente à la plus ancienne."""
    return conn.execute(
        "SELECT at, action, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()