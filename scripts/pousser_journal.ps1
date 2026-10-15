# Pousse vers le depot Git ce qui doit y figurer : code, scripts et artefacts
# d'audit legers. Jamais les corpus ni les embeddings.
#
#     .\scripts\pousser_journal.ps1 -Message "index eurlex calcule sur GPU"
#
# Ce qui part :
#   src\, scripts\, requirements*.txt, docs\
#   resultats\*\execution.json          manifeste, empreintes, mesures
#   data\embeddings\*\etat.json         avancement du calcul
#
# Ce qui n'est jamais pousse : *.npy, *.pkl, les instantanes Qdrant,
# data\<corpus>\. Le motif est detaille dans sauvegarder_embeddings.ps1 : un
# embedding peut etre inverse en texte, et le depot ne redistribue aucun corpus.

param(
    [string]$Message = "avancement",
    [switch]$SansPush
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".git")) { throw "pas un depot Git. Lancez depuis la racine." }

# Garde-fou : verifier que .gitignore couvre les artefacts volumineux avant
# tout ajout. Un oubli est difficile a corriger, car un fichier pousse reste
# dans l'historique meme apres suppression.
$motifs = @("data/", "*.npy", "*.pkl", "*.snapshot", ".venv/")
$gitignore = if (Test-Path ".gitignore") { Get-Content ".gitignore" -Raw } else { "" }
$absents = @($motifs | Where-Object { $gitignore -notmatch [regex]::Escape($_) })

if ($absents.Count -gt 0) {
    Write-Host "Motifs absents de .gitignore :" -ForegroundColor Yellow
    $absents | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    $r = Read-Host "Les ajouter maintenant ? [O/n]"
    if ($r -ne "n") {
        Add-Content ".gitignore" "`n# ajoute par pousser_journal.ps1"
        $absents | ForEach-Object { Add-Content ".gitignore" $_ }
        Write-Host "  .gitignore complete" -ForegroundColor Green
    }
}

git add src scripts requirements*.txt docs 2>$null

# Les artefacts d'audit sont ajoutes en forcant, car data/ est ignore : ce
# sont des fichiers de quelques kilo-octets qui portent la reproductibilite
# (hash de manifeste, hash de commit, avancement des tranches).
Get-ChildItem -Recurse "resultats" -Filter "execution.json" -ErrorAction SilentlyContinue |
    ForEach-Object { git add -f $_.FullName 2>$null }
Get-ChildItem -Recurse "data\embeddings" -Filter "etat.json" -ErrorAction SilentlyContinue |
    ForEach-Object { git add -f $_.FullName 2>$null }

# Derniere verification : rien de volumineux ne doit etre indexe.
$gros = git diff --cached --name-only | ForEach-Object {
    if (Test-Path $_) {
        $f = Get-Item $_
        if ($f.Length -gt 5MB) { "{0} ({1:N1} Mo)" -f $_, ($f.Length/1MB) }
    }
}
if ($gros) {
    Write-Host ""
    Write-Host "REFUS : fichiers de plus de 5 Mo indexes" -ForegroundColor Red
    $gros | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "  git reset  pour annuler l'index, puis verifiez .gitignore."
    exit 1
}

$n = (git diff --cached --name-only | Measure-Object).Count
if ($n -eq 0) { Write-Host "Rien a valider."; exit 0 }

Write-Host "$n fichier(s) a valider :"
git diff --cached --name-only | ForEach-Object { Write-Host "  $_" }

git commit -m $Message
if (-not $SansPush) {
    git push
    Write-Host "Pousse vers l'origine." -ForegroundColor Green
} else {
    Write-Host "Valide localement (--SansPush)." -ForegroundColor Green
}
