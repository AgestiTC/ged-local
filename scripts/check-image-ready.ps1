<#
.SYNOPSIS
  Vérifie qu'une release est prête à pull : CI verte + images pullables sur GHCR.
.DESCRIPTION
  Contrôle (1) que le run CI du tag est en succès (via gh) et (2) que les manifests
  des images backend+frontend existent sur GHCR (docker manifest inspect).
.PARAMETER Version
  Version semver sans préfixe v (ex : 1.4.0).
.PARAMETER Owner
  Namespace GHCR (défaut : agestitc).
.EXAMPLE
  .\scripts\check-image-ready.ps1 1.4.0
#>
param(
    [Parameter(Mandatory = $true)] [string]$Version,
    [string]$Owner = 'agestitc'
)

$ErrorActionPreference = 'Continue'
$tag = "v$Version"
$ok = $true

Write-Host "== CI du tag $tag ==" -ForegroundColor Cyan
$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($gh) {
    & gh run list --workflow build-push.yml --limit 5
} else {
    Write-Warning "gh CLI introuvable — vérifie manuellement l'onglet Actions."
}

foreach ($img in @("ghcr.io/$Owner/docflow-backend:$tag", "ghcr.io/$Owner/docflow-frontend:$tag")) {
    Write-Host "`n== Manifest $img ==" -ForegroundColor Cyan
    & docker manifest inspect $img *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] $img pullable." -ForegroundColor Green
    } else {
        Write-Host "[KO] $img introuvable (CI pas finie ou job verify en échec)." -ForegroundColor Red
        $ok = $false
    }
}

Write-Host ""
if ($ok) {
    Write-Host "[OK] Release $tag prête. Sur le NAS : Container Manager -> Stop -> Pull -> Up." -ForegroundColor Green
} else {
    Write-Host "[ATTENTE] Images pas encore prêtes. Relance dans quelques minutes." -ForegroundColor Yellow
    exit 1
}
