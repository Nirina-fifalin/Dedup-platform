# Construit l'application Windows : dist\Deduplication\Deduplication.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install --quiet pyinstaller
python -m PyInstaller desktop\app.py `
  --name Deduplication --noconfirm --clean --windowed `
  --paths deduplication-engine\src --paths desktop `
  --collect-all customtkinter --collect-all tkinterdnd2 `
  --collect-all phonenumbers --collect-all rapidfuzz
if ($LASTEXITCODE -ne 0) { throw "La construction a échoué." }
Write-Host "Terminé : dist\Deduplication\Deduplication.exe"