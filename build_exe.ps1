# Construit l'application Windows : dist\Deduplication\Deduplication.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install --quiet pyinstaller

$extra = @()
if (Test-Path "desktop\icon.ico") { $extra = @("--icon", "desktop\icon.ico") }

python -m PyInstaller desktop\app.py `
  --name Deduplication --noconfirm --clean --windowed `
  --paths deduplication-engine\src --paths desktop `
  --collect-all customtkinter --collect-all tkinterdnd2 `
  --collect-all phonenumbers --collect-all rapidfuzz @extra
if ($LASTEXITCODE -ne 0) { throw "La construction a échoué." }

# Garde-fou // aucune donnée (base, sauvegardes, fichiers Excel/CSV, journaux) ne doit être livrée //
$out = "dist\Deduplication"
$dataExt = @(".db", ".sqlite", ".sqlite3", ".csv", ".xlsx", ".xls", ".log")
$badFiles = Get-ChildItem $out -Recurse -File |
    Where-Object { ($dataExt -contains $_.Extension.ToLower()) -or ($_.Name -eq "column_mappings.json") }
$badDirs = Get-ChildItem $out -Recurse -Directory |
    Where-Object { @("samples", "sauvegardes") -contains $_.Name }
if ($badFiles -or $badDirs) {
    $badFiles | ForEach-Object { Write-Host "  fichier : $($_.FullName)" }
    $badDirs  | ForEach-Object { Write-Host "  dossier : $($_.FullName)" }
    throw "Des données se trouvent dans l'application : ne la livrez pas."
}
Write-Host "Contrôle : aucune donnée dans l'application."
Write-Host "Terminé : $out\Deduplication.exe"