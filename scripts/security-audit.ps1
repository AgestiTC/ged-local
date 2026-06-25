<#
.SYNOPSIS
  Audit sécurité on-demand de Matothèque : deps Python/Node + scan images + issues.
.DESCRIPTION
  - pip-audit sur backend/requirements.txt (via container Python si pip-audit absent)
  - npm audit sur frontend
  - docker scout cves sur l'image backend :latest (si docker scout dispo)
  - liste les issues GitHub label security (si gh dispo)
  Met à jour le marqueur .claude/.last-security-audit (consommé par le hook de rappel 30j).
.EXAMPLE
  .\scripts\security-audit.ps1
#>
param(
    [string]$Owner = 'agestitc'
)

$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repo

Write-Host "== pip-audit (backend) ==" -ForegroundColor Cyan
if (Get-Command pip-audit -ErrorAction SilentlyContinue) {
    & pip-audit -r backend/requirements.txt
} else {
    Write-Host "pip-audit absent localement -> via container python:3.11-slim" -ForegroundColor Gray
    & docker run --rm -v "${repo}:/src" -w /src python:3.11-slim `
        sh -c "pip install -q pip-audit && pip-audit -r backend/requirements.txt"
}

Write-Host "`n== npm audit (frontend) ==" -ForegroundColor Cyan
if (Test-Path "$repo\frontend\package-lock.json") {
    Push-Location "$repo\frontend"
    & npm audit --omit=dev
    Pop-Location
} else {
    Write-Host "Pas de package-lock.json -> npm audit ignoré." -ForegroundColor Gray
}

Write-Host "`n== docker scout (image backend :latest) ==" -ForegroundColor Cyan
& docker scout cves "ghcr.io/$Owner/docflow-backend:latest" --only-severity critical,high 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "docker scout indisponible ou image non publiée — ignoré." -ForegroundColor Gray }

Write-Host "`n== Issues GitHub label 'security' ==" -ForegroundColor Cyan
if (Get-Command gh -ErrorAction SilentlyContinue) {
    & gh issue list --label security
} else {
    Write-Host "gh CLI absent — vérifie l'onglet Security du repo." -ForegroundColor Gray
}

# Marqueur d'audit (consommé par le hook session-start-security-check.ps1)
$today = (Get-Date).ToString('yyyy-MM-dd')
Set-Content -Path "$repo\.claude\.last-security-audit" -Value $today -NoNewline -Encoding utf8
Write-Host "`n[OK] Audit terminé. Marqueur mis à jour : $today" -ForegroundColor Green
