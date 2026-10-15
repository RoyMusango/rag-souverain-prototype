$ErrorActionPreference = "Stop"
$adaptateurs = @("synthea", "finqa", "tatqa", "eurlex", "pubmedqa", "enronqa")
foreach ($a in $adaptateurs) {
    Write-Host "=== $a ===" -ForegroundColor Cyan
    $debut = Get-Date
    python "src\ingestion\$a.py"
    $duree = (Get-Date) - $debut
    Write-Host ("  duree : {0:mm}m{0:ss}s" -f $duree) -ForegroundColor DarkGray
}
Write-Host "=== validation ===" -ForegroundColor Cyan
python scripts\validate_schema.py
