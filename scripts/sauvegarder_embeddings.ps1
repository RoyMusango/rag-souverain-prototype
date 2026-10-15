# Sauvegarde incrementale des embeddings hors de la machine de calcul.
#
#     .\scripts\sauvegarder_embeddings.ps1 -Destination "D:\sauvegarde"
#     .\scripts\sauvegarder_embeddings.ps1 -Destination "$HOME\OneDrive\rag"
#
# A lancer sur la machine de calcul, pendant ou apres le calcul. La sauvegarde
# est incrementale : seules les tranches nouvelles ou modifiees sont copiees,
# ce qui permet de la relancer toutes les dix minutes sans surcout.
#
# CHOIX DE NE PAS UTILISER GIT
#
#   1. Volume. 419 342 documents x 1024 dimensions x 4 octets = 1,64 Go, dont
#      des fichiers .npy de plusieurs dizaines de Mo. GitHub refuse tout
#      fichier au-dela de 100 Mo et deconseille les depots au-dela de 1 Go.
#      Git LFS offre 1 Go de stockage et 1 Go de bande passante mensuelle en
#      formule gratuite : le premier clone epuiserait le quota.
#
#   2. Nature des donnees. Un embedding de texte peut etre inverse (Morris et
#      al., Song et Raghunathan, references de la section 3.3.1). Publier les
#      embeddings d'EnronQA reviendrait a publier les courriels dont ils
#      derivent, c'est-a-dire la correspondance de personnes physiques
#      reelles. Cela contredirait :
#         - NOTICE.md : « Ce depot ne redistribue aucun corpus »
#         - DATA_README.md : data/ volontairement absent du depot
#         - la qualification RGPD article 89 du memoire (usage strictement
#           local, aucune redistribution)
#      Cela contredirait surtout la these elle-meme, qui etablit qu'un
#      embedding est une donnee identifiante.
#
#   Le depot Git est reserve au code, aux scripts et aux resultats agreges
#   (voir pousser_journal.ps1).

param(
    [Parameter(Mandatory=$true)][string]$Destination,
    [string]$Source = "data\embeddings",
    [switch]$AvecResultats
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) { throw "introuvable : $Source" }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$debut = Get-Date
$copies = 0; $ignores = 0; $octets = 0

Write-Host "Sauvegarde incrementale : $Source -> $Destination" -ForegroundColor Cyan

Get-ChildItem -Recurse $Source -File | ForEach-Object {
    $relatif = $_.FullName.Substring((Resolve-Path $Source).Path.Length + 1)
    $cible = Join-Path $Destination $relatif
    $dossier = Split-Path $cible
    if (-not (Test-Path $dossier)) { New-Item -ItemType Directory -Force -Path $dossier | Out-Null }

    # Comparaison par taille et date : une empreinte complete sur 1,6 Go
    # couterait plusieurs minutes a chaque passage et empecherait les
    # relances frequentes, qui sont l'objet d'une sauvegarde incrementale.
    $aCopier = $true
    if (Test-Path $cible) {
        $c = Get-Item $cible
        if ($c.Length -eq $_.Length -and $c.LastWriteTimeUtc -ge $_.LastWriteTimeUtc) {
            $aCopier = $false
        }
    }

    if ($aCopier) {
        Copy-Item -Force $_.FullName $cible
        $copies++; $octets += $_.Length
        Write-Host ("  + {0} ({1:N1} Mo)" -f $relatif, ($_.Length/1MB))
    } else { $ignores++ }
}

if ($AvecResultats -and (Test-Path "resultats")) {
    Copy-Item -Recurse -Force "resultats" "$Destination\" -ErrorAction SilentlyContinue
    Write-Host "  + resultats\"
}

# Empreintes : elles permettront de verifier le transfert vers le poste de
# redaction, et de prouver que l'index mesure est celui qui a ete transporte.
Get-ChildItem -Recurse $Destination -File -Filter *.npy |
    Get-FileHash -Algorithm SHA256 |
    Select-Object Hash, Path |
    Export-Csv "$Destination\empreintes_embeddings.csv" -NoTypeInformation -Encoding UTF8

$duree = (Get-Date) - $debut
Write-Host ""
Write-Host ("{0} fichier(s) copie(s), {1} inchange(s), {2:N0} Mo en {3:N0}s" -f `
    $copies, $ignores, ($octets/1MB), $duree.TotalSeconds) -ForegroundColor Green

$total = (Get-ChildItem -Recurse $Destination -File | Measure-Object Length -Sum).Sum
Write-Host ("Sauvegarde totale : {0:N0} Mo" -f ($total/1MB))
Write-Host ""
Write-Host "Attendu apres le corpus complet : environ 1 640 Mo."
