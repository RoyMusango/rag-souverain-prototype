# Transport de l'index depuis la machine de calcul vers le poste de redaction.
#
# Le rapport prevoit un index persiste et des embeddings precalcules une fois
# (section 4.1.3), ce qui rend le transport possible : la machine de
# redaction n'a jamais a recalculer.
#
# A executer sur la machine de calcul, apres build_index.py.

param(
    [string]$Destination = "export_index",
    [switch]$AvecEmbeddings
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

# 1. Index lexical et resultats : toujours transportes, ils sont legers.
Copy-Item -Recurse -Force "data\index_lexical" "$Destination\" -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force "resultats" "$Destination\" -ErrorAction SilentlyContinue

# 2. Vecteurs bruts : volumineux. Optionnels, car Qdrant les contient deja.
if ($AvecEmbeddings) {
    Copy-Item -Recurse -Force "data\embeddings" "$Destination\"
}

# 3. Collection Qdrant : instantane par l'API, plutot qu'une copie de fichiers
#    a chaud, qui produirait un index incoherent.
Write-Host "Instantane Qdrant..."
$snap = Invoke-RestMethod -Method Post `
    -Uri "http://localhost:6333/collections/rag_souverain/snapshots"
$nom = $snap.result.name
Invoke-WebRequest `
    -Uri "http://localhost:6333/collections/rag_souverain/snapshots/$nom" `
    -OutFile "$Destination\rag_souverain.snapshot"

# 4. Empreintes : sans elles, impossible d'affirmer que l'index transporte est
#    bien celui qui a produit les mesures (section 4.1.5).
Get-ChildItem -Recurse $Destination -File |
    Get-FileHash -Algorithm SHA256 |
    Select-Object Hash, Path |
    Export-Csv "$Destination\empreintes.csv" -NoTypeInformation

Write-Host "Export termine : $Destination"
Write-Host "Sur le poste de redaction, restaurer par :"
Write-Host "  Invoke-RestMethod -Method Post -Uri http://localhost:6333/collections/rag_souverain/snapshots/upload -InFile rag_souverain.snapshot"
