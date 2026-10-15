# Cree l'arborescence du POC et verifie que tout est importable.
#
# A executer depuis la racine du projet :
#     cd C:\Dev\rag-souverain
#     .\scripts\installer_poc.ps1
#
# Idempotent : une relance ne modifie rien d'existant. Ne touche ni a
# src\ingestion\, ni a data\, ni aux scripts existants.

$ErrorActionPreference = "Stop"

if (-not (Test-Path "src\ingestion")) {
    throw "src\ingestion introuvable. Lancez ce script depuis la racine du projet (C:\Dev\rag-souverain)."
}

Write-Host "Creation des paquets Python" -ForegroundColor Cyan

$paquets = @("commun","confidentialite","routage","isolation","provenance",
             "index","fournisseur","simulateur","evaluation")

New-Item -ItemType File -Force -Path "src\__init__.py" | Out-Null
Write-Host "  src\__init__.py"

foreach ($p in $paquets) {
    New-Item -ItemType Directory -Force -Path "src\$p" | Out-Null
    New-Item -ItemType File -Force -Path "src\$p\__init__.py" | Out-Null
    Write-Host "  src\$p\__init__.py"
}

# src\ingestion NE DOIT PAS recevoir de __init__.py : les adaptateurs et
# build_index.py l'importent par sys.path, pas comme paquet. Un __init__.py
# y changerait la resolution des imports.
if (Test-Path "src\ingestion\__init__.py") {
    Write-Warning "src\ingestion\__init__.py existe : verifiez que l'ingestion fonctionne toujours."
}

foreach ($d in @("resultats","data\embeddings","data\index_lexical")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

Write-Host ""
Write-Host "Verification des fichiers attendus" -ForegroundColor Cyan

$attendus = @(
  "src\pipeline.py",
  "src\commun\config.py", "src\commun\journal.py", "src\commun\profils.py",
  "src\confidentialite\anonymat.py", "src\confidentialite\gabarit.py",
  "src\confidentialite\budget.py", "src\confidentialite\politique.py",
  "src\confidentialite\verrou.py",
  "src\routage\routeur.py",
  "src\isolation\teinte.py",
  "src\provenance\politique.py",
  "src\index\embeddings.py", "src\index\qdrant_index.py",
  "src\index\lexical.py", "src\index\hybride.py",
  "src\index\recuperateurs.py",
  "src\fournisseur\base.py",
  "src\simulateur\adverse.py",
  "src\evaluation\e1_hybridation.py", "src\evaluation\e2_anonymat.py",
  "src\evaluation\e3_injection.py", "src\evaluation\e4_provenance.py",
  "src\evaluation\e5_cout.py", "src\evaluation\e7_masquage.py",
  "src\evaluation\metriques.py", "src\evaluation\parite.py",
  "scripts\run_e2.py", "scripts\run_e7.py", "scripts\run_campagne.py",
  "scripts\build_index.py", "scripts\build_index_cpu.py",
  "scripts\comparer_materiel.py",
  "scripts\preparer_shadow.ps1", "scripts\exporter_index.ps1",
  "scripts\importer_index.ps1"
)

$absents = @($attendus | Where-Object { -not (Test-Path $_) })

if ($absents.Count -gt 0) {
    Write-Host ("  {0} fichier(s) MANQUANT(S) sur {1} :" -f $absents.Count, $attendus.Count) -ForegroundColor Red
    foreach ($a in $absents) { Write-Host "    $a" -ForegroundColor Red }
    Write-Host ""
    Write-Host "  Deposez l'archive complete du POC avant de continuer :" -ForegroundColor Yellow
    Write-Host "    Expand-Archive -Path poc.zip -DestinationPath . -Force"
    Write-Host ""
    Write-Host "  Les imports ne sont pas testes tant que des fichiers manquent :"
    Write-Host "  ils produiraient des erreurs en cascade sans interet diagnostique."
    exit 1
}
Write-Host ("  {0} fichiers presents" -f $attendus.Count) -ForegroundColor Green

Write-Host ""
Write-Host "Verification des imports" -ForegroundColor Cyan

$code = @'
import sys
sys.path.insert(0, ".")
modules = [
    "src.commun.config", "src.commun.journal", "src.commun.profils",
    "src.confidentialite.anonymat", "src.confidentialite.gabarit",
    "src.confidentialite.budget", "src.confidentialite.politique",
    "src.confidentialite.verrou",
    "src.routage.routeur", "src.isolation.teinte",
    "src.provenance.politique",
    "src.index.hybride", "src.index.lexical", "src.index.recuperateurs",
    "src.fournisseur.base", "src.simulateur.adverse",
    "src.evaluation.e1_hybridation", "src.evaluation.e2_anonymat",
    "src.evaluation.e3_injection", "src.evaluation.e4_provenance",
    "src.evaluation.e5_cout", "src.evaluation.e7_masquage",
    "src.evaluation.metriques", "src.evaluation.parite",
    "src.pipeline",
]
manquants = []
for m in modules:
    try:
        __import__(m)
    except Exception as e:
        manquants.append(f"{m} : {type(e).__name__} {e}")
if manquants:
    print("ECHEC")
    for x in manquants:
        print("   " + x)
    sys.exit(1)
print(f"OK : {len(modules)} modules importes")
'@

$code | Out-File -Encoding UTF8 -FilePath "$env:TEMP\verif_poc.py"
py -3.11 "$env:TEMP\verif_poc.py"
Remove-Item "$env:TEMP\verif_poc.py" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Modules a dependances lourdes, verifies separement :" -ForegroundColor Cyan
$ancien = $ErrorActionPreference
$ErrorActionPreference = "Continue"
foreach ($m in @("src.index.embeddings","src.index.qdrant_index")) {
    # 2>&1 fusionne les flux, et ErrorActionPreference doit etre relache :
    # sinon PowerShell transforme la sortie d'erreur de py en exception
    # bloquante, alors qu'une dependance absente est ici un cas attendu.
    $null = py -3.11 -c "import sys; sys.path.insert(0,'.'); import $m" 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host "  OK   $m" -ForegroundColor Green }
    else { Write-Host "  --   $m (dependance absente : normal avant pip install)" }
}
$ErrorActionPreference = $ancien

Write-Host ""
Write-Host "Installation terminee." -ForegroundColor Green
Write-Host "Etape suivante : py -3.11 scripts\run_e2.py --entites 4"
