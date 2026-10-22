"""Structure d'un classeur : feuilles, nombre de lignes, NOMS de colonnes (aucune donnée)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import file_reader                                    # noqa: E402
from deduplication.normalization import normalize_name  # noqa: E402

sheets = file_reader.read_workbook(sys.argv[1])
reference = None
for sheet in sheets:
    people = file_reader.looks_like_registrations(sheet)
    print(f"\n{sheet.name} — {len(sheet.rows)} lignes — "
          f"{'liste de personnes' if people else 'autre type de données'}")
    print("  colonnes :", " | ".join(sheet.headers))
    if not people:
        continue
    names = {normalize_name(h): h for h in sheet.headers}
    if reference is None:
        reference = (sheet.name, names)
        continue
    ref_name, ref_cols = reference
    missing = [ref_cols[k] for k in ref_cols if k not in names]
    extra = [names[k] for k in names if k not in ref_cols]
    print(f"  par rapport à « {ref_name} » — absentes : {missing or 'aucune'} ; en plus : {extra or 'aucune'}")