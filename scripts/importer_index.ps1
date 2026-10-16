# Restaure sur le poste local l'index calcule sur la machine de calcul.
#
# A lancer depuis la racine du projet, apres avoir recupere et decompresse
# l'export produit par exporter_index.ps1.
#
# Usage :
#   .\scripts\importer_index.ps1 -Source export_index

param(
    [string]$Source = "export_index",
    [string]$Collection = "rag_souverain",
    [string]$Qdrant = "http://localhost:6333"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) { throw "introuvable : $Source" }

Write-Host "Import de l'index depuis $Source" -ForegroundColor Cyan

# 1. Verification des empreintes AVANT d'installer quoi que ce soit. Un index
#    abime pendant la copie donnerait des mesures fausses, sans aucun signe.
$manifeste = Join-Path $Source "empreintes.csv"
if (Test-Path $manifeste) {
    $ecarts = 0
    Import-Csv $manifeste | ForEach-Object {
        $f = $_.Path
        if (Test-Path $f) {
            $h = (Get-FileHash $f -Algorithm SHA256).Hash
            if ($h -ne $_.Hash) { Write-Warning "EMPREINTE DIFFERENTE : $f"; $ecarts++ }
        }
    }
    if ($ecarts -gt 0) { throw "$ecarts fichier(s) modifie(s) pendant la copie." }
    Write-Host "  empreintes verifiees" -ForegroundColor Green
} else {
    Write-Warning "  pas de manifeste d'empreintes : integrite non verifiee"
}

# 2. Vecteurs, index lexical, resultats
foreach ($d in @("embeddings","index_lexical")) {
    $src = Join-Path $Source $d
    if (Test-Path $src) {
        New-Item -ItemType Directory -Force -Path "data\$d" | Out-Null
        Copy-Item -Recurse -Force "$src\*" "data\$d\"
        Write-Host "  data\$d restaure"
    }
}
if (Test-Path (Join-Path $Source "resultats")) {
    New-Item -ItemType Directory -Force -Path "resultats" | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Source "resultats\*") "resultats\"
    Write-Host "  resultats restaures"
}

# 3. Instantane Qdrant
$snapshot = Join-Path $Source "$Collection.snapshot"
if (Test-Path $snapshot) {
    try { Invoke-RestMethod -Uri "$Qdrant/collections" -TimeoutSec 5 | Out-Null }
    catch { throw "Qdrant injoignable sur $Qdrant. Demarrez-le, puis relancez." }

    Write-Host "  televersement de l'instantane..."
    $form = @{ snapshot = Get-Item $snapshot }
    Invoke-RestMethod -Method Post -Form $form `
        -Uri "$Qdrant/collections/$Collection/snapshots/upload?priority=snapshot" | Out-Null

    $info = Invoke-RestMethod -Uri "$Qdrant/collections/$Collection"
    Write-Host ("  collection restauree : {0} points" -f $info.result.points_count) -ForegroundColor Green
}

Write-Host ""
Write-Host "Import termine. Verification suggeree :"
Write-Host "  py -3.11 -c `"from qdrant_client import QdrantClient; c=QdrantClient(url='$Qdrant'); print(c.get_collection('$Collection'))`""
