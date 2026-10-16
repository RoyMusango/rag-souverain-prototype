# Diagnostic : liste les fichiers manquants de l'installation.
#
#     .\scripts\verifier_installation.ps1      (depuis la racine du depot)
#
# A lancer si installer_poc.ps1 signale des fichiers absents, ou apres avoir
# depose l'archive, pour verifier avant de continuer.

$ErrorActionPreference = "Continue"

if (-not (Test-Path "src\ingestion")) {
    Write-Host "src\ingestion introuvable : vous n'etes pas a la racine du depot." -ForegroundColor Red
    Write-Host "Placez-vous dans le dossier qui contient src\ et scripts\."
    exit 1
}

$attendus = @{
  "src\pipeline.py"                        = "pipeline de bout en bout"
  "src\commun\config.py"                   = "materiel, seuils, paliers"
  "src\commun\journal.py"                  = "manifeste, empreintes"
  "src\commun\profils.py"                  = "profils GPU / CPU"
  "src\confidentialite\anonymat.py"        = "|S|, hierarchies"
  "src\confidentialite\gabarit.py"         = "G(e) = f(e, kappa)"
  "src\confidentialite\budget.py"          = "registre d'exposition"
  "src\confidentialite\politique.py"       = "pilier 2 - orchestration"
  "src\confidentialite\verrou.py"          = "verrou de sortie + masquage"
  "src\routage\routeur.py"                 = "pilier 1 - cinq issues"
  "src\isolation\teinte.py"                = "pilier 3 - teinte, collusion"
  "src\provenance\politique.py"            = "pilier 4 - attribution"
  "src\index\embeddings.py"                = "BGE-M3, GPU, reprise"
  "src\index\qdrant_index.py"              = "index vectoriel"
  "src\index\lexical.py"                   = "BM25 + cross-encodeur"
  "src\index\hybride.py"                   = "fusion RRF"
  "src\index\recuperateurs.py"             = "raccord index / cascade"
  "src\fournisseur\base.py"                = "trois paliers"
  "src\simulateur\adverse.py"              = "support E3"
  "src\evaluation\e1_hybridation.py"       = "E1"
  "src\evaluation\e2_anonymat.py"          = "E2 - resultat principal"
  "src\evaluation\e3_injection.py"         = "E3"
  "src\evaluation\e4_provenance.py"        = "E4"
  "src\evaluation\e5_cout.py"              = "E5"
  "src\evaluation\e7_masquage.py"          = "E7"
  "src\evaluation\metriques.py"            = "Recall, nDCG, Ragas, ASR"
  "src\evaluation\parite.py"               = "parite materielle"
  "scripts\run_e2.py"                      = "lanceur E2"
  "scripts\run_e7.py"                      = "lanceur E7"
  "scripts\run_campagne.py"                = "lanceur E1, E4, E5"
  "scripts\build_index.py"                 = "index sur GPU"
  "scripts\build_index_cpu.py"             = "index sur processeur"
  "scripts\comparer_materiel.py"           = "comparaison de materiels"
  "scripts\preparer_shadow.ps1"            = "paquet pour la machine de calcul"
  "scripts\exporter_index.ps1"             = "export de l'index"
  "scripts\importer_index.ps1"             = "import de l'index"
}

$presents = @(); $absents = @()
foreach ($k in ($attendus.Keys | Sort-Object)) {
    if (Test-Path $k) { $presents += $k } else { $absents += $k }
}

Write-Host ""
Write-Host ("PRESENTS : {0} / {1}" -f $presents.Count, $attendus.Count) -ForegroundColor Green

if ($absents.Count -eq 0) {
    Write-Host ""
    Write-Host "Installation complete." -ForegroundColor Green
    Write-Host "Etape suivante : .\scripts\installer_poc.ps1"
    exit 0
}

Write-Host ""
Write-Host ("ABSENTS : {0}" -f $absents.Count) -ForegroundColor Red
foreach ($a in $absents) {
    Write-Host ("  {0,-42} {1}" -f $a, $attendus[$a]) -ForegroundColor Red
}

# Un fichier vide passe Test-Path, puisqu'il existe, mais fait echouer
# l'import avec un message peu clair. Un copier-coller interrompu en cree.
$vides = @($presents | Where-Object { (Get-Item $_).Length -lt 200 })
if ($vides.Count -gt 0) {
    Write-Host ""
    Write-Host "SUSPECTS (moins de 200 octets - copie incomplete ?) :" -ForegroundColor Yellow
    foreach ($v in $vides) {
        Write-Host ("  {0} : {1} octets" -f $v, (Get-Item $v).Length) -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Solution : deposez poc.zip a la racine du depot, puis" -ForegroundColor Cyan
Write-Host "  Expand-Archive -Path poc.zip -DestinationPath . -Force"
Write-Host "  .\scripts\installer_poc.ps1"
exit 1
