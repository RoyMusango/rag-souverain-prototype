# Prepare le paquet a transferer vers la machine de calcul.
#
# Ne transporte que ce dont le calcul a besoin : le code et les corpus au
# schema commun. Les donnees brutes (CSV Synthea, parquet EnronQA, PDF
# EUR-Lex) restent sur le poste local : l'ingestion est faite et ne sera pas
# rejouee, et elles pesent plusieurs gigaoctets inutilement.
#
# Usage :
#   .\scripts\preparer_shadow.ps1
#   .\scripts\preparer_shadow.ps1 -Corpus eurlex,tatqa   # sous-ensemble

param(
    [string[]]$Corpus = @("synthea","finqa","tatqa","eurlex","pubmedqa","enronqa"),
    [string]$Destination = "paquet_shadow"
)

$ErrorActionPreference = "Stop"

$Schemas = @{
    "synthea"  = "data\synthea\synthea_schema.json"
    "finqa"    = "data\finqa\finqa_schema.json"
    "tatqa"    = "data\tatqa\tatqa_schema.json"
    "eurlex"   = "data\external\eurlex\eurlex_schema.json"
    "pubmedqa" = "data\pubmedqa\pubmedqa_schema.jsonl"
    "enronqa"  = "data\enronqa\enronqa_schema.jsonl"
}

Write-Host "Preparation du paquet pour la machine de calcul" -ForegroundColor Cyan
if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

# 1. Code source et scripts
Copy-Item -Recurse -Force "src"     "$Destination\src"
Copy-Item -Recurse -Force "scripts" "$Destination\scripts"
foreach ($f in @("requirements.txt","requirements-poc.txt","NOTICE.md")) {
    if (Test-Path $f) { Copy-Item -Force $f "$Destination\" }
}

# 2. Corpus au schema commun, en reconstruisant l'arborescence attendue
$total = 0
foreach ($nom in $Corpus) {
    $chemin = $Schemas[$nom]
    if (-not $chemin) { Write-Warning "corpus inconnu : $nom"; continue }
    if (-not (Test-Path $chemin)) {
        # Le validateur accepte indifferemment .json et .jsonl ; idem ici.
        $alt = [IO.Path]::ChangeExtension($chemin, `
               $(if ($chemin.EndsWith(".json")) { "jsonl" } else { "json" }))
        if (Test-Path $alt) { $chemin = $alt } else {
            Write-Warning "ABSENT : $nom ($chemin)"; continue
        }
    }
    $cible = Join-Path $Destination $chemin
    New-Item -ItemType Directory -Force -Path (Split-Path $cible) | Out-Null
    Copy-Item -Force $chemin $cible
    $mo = [math]::Round((Get-Item $chemin).Length / 1MB, 1)
    $total += $mo
    Write-Host ("  {0,-10} {1,8} Mo" -f $nom, $mo)
}

# 3. Empreintes : elles fondent la comparaison ulterieure, en permettant
#    d'etablir que les deux machines ont vu les memes corpus.
Get-ChildItem -Recurse $Destination -File -Include *.json,*.jsonl |
    Get-FileHash -Algorithm SHA256 |
    Select-Object Hash, @{N="Fichier";E={Resolve-Path -Relative $_.Path}} |
    Export-Csv "$Destination\empreintes_corpus.csv" -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host ("Total corpus : {0} Mo" -f [math]::Round($total,1)) -ForegroundColor Green
Write-Host "Paquet : $Destination"
Write-Host ""
Write-Host "Compression (recommandee avant transfert) :"
Write-Host "  Compress-Archive -Path $Destination\* -DestinationPath paquet_shadow.zip -CompressionLevel Optimal"
