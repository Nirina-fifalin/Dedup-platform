import re
import json
import tempfile
from pathlib import Path

from deduplication import ColumnMapping, MissingColumnsError
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..deps import get_session
from ..models import SourceFile
from ..schemas import ImportReportOut, SourceFileOut
from ..services.importer import AlreadyImportedError, import_file
from ..services.export import build_export

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_SUFFIXES = {".csv", ".xlsx"}
MAX_BYTES = 20 * 1024 * 1024

DEFAULT_MAPPING = {
    "nom": "nom", "prenom": "prenom", "email": "email", "telephone": "telephone",
    "sexe": "sexe", "formation": "formation", "annee": "annee",
    "date_inscription": "date_inscription",
}


@router.post("", response_model=ImportReportOut, status_code=201)
def upload_file(
    file: UploadFile = File(...),
    mapping: str | None = Form(None, description='JSON {"champ": "Nom de la colonne"}'),
    session: Session = Depends(get_session),
):
    name = Path(file.filename or "").name
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Format non supporté : utiliser .csv ou .xlsx")

    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"Fichier trop volumineux (max {MAX_BYTES // 1024 // 1024} Mo)")

    columns = DEFAULT_MAPPING
    if mapping:
        try:
            columns = json.loads(mapping)
            if not isinstance(columns, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in columns.items()
            ):
                raise ValueError
        except ValueError:
            raise HTTPException(422, "mapping : objet JSON {champ: colonne} attendu")
        if "nom" not in columns or "prenom" not in columns:
            raise HTTPException(422, "mapping : 'nom' et 'prenom' sont obligatoires")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(content)
        try:
            report = import_file(session, path, ColumnMapping(columns=columns))
        except AlreadyImportedError as e:
            raise HTTPException(409, str(e))
        except MissingColumnsError as e:
            raise HTTPException(422, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))

    return ImportReportOut(**report.to_dict())


@router.get("/{source_file_id}", response_model=SourceFileOut)
def get_file(source_file_id: int, session: Session = Depends(get_session)):
    sf = session.get(SourceFile, source_file_id)
    if sf is None:
        raise HTTPException(404, "Fichier source introuvable")
    return SourceFileOut(
        id=sf.id, filename=sf.filename, imported_at=sf.imported_at,
        row_count=sf.row_count, status=sf.status, report=sf.report,
    )


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/{source_file_id}/export")
def export_file(source_file_id: int, session: Session = Depends(get_session)):
    sf = session.get(SourceFile, source_file_id)
    if sf is None:
        raise HTTPException(404, "Fichier source introuvable")
    if sf.status != "done":
        raise HTTPException(409, f"Import non terminé (statut : {sf.status})")
    data = build_export(session, source_file_id)
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(sf.filename).stem) or "export"
    return Response(
        content=data, media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{stem}_nettoye.xlsx"'},
    )