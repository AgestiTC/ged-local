<#
.SYNOPSIS
  Release Matothèque : bump VERSION + sync sources + commit + tag annoté + push --follow-tags.
.DESCRIPTION
  Rail unique tag-driven : pousser un tag v* déclenche la CI (build + verify) qui
  publie les images backend/frontend sur GHCR.
  À lancer depuis main (après merge de develop) — la CI ne build que sur tag.
.PARAMETER Version
  Version semver SANS préfixe v (ex : 1.4.0).
.PARAMETER Message
  Message court décrivant la release (objet du tag annoté).
.EXAMPLE
  .\scripts\release.ps1 -Version 1.4.0 -Message "Rapport comparatif multi-groupes"
#>
param(
    [Parameter(Mandatory = $true)] [string]$Version,
    [Parameter(Mandatory = $true)] [string]$Message
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repo

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version invalide '$Version' — format attendu : X.Y.Z (sans 'v')."
}

# Garde-fou : working tree propre
$dirty = (& git status --porcelain)
if ($dirty) { throw "Working tree non propre. Commit/stash avant de release.`n$dirty" }

# Garde-fou : on release depuis main
$branch = (& git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne 'main') {
    Write-Warning "Tu es sur '$branch', pas 'main'. La release se pose normalement sur main."
}

# Garde-fou : tag inexistant
$tag = "v$Version"
$existing = & git tag --list $tag
if ($existing) { throw "Le tag $tag existe déjà." }

# Écriture UTF-8 SANS BOM (Set-Content -Encoding utf8 ajoute un BOM en PS 5.1,
# qui se retrouverait dans la version exposée → "﻿1.8.0").
$utf8NoBom = New-Object System.Text.UTF8Encoding $false

# 1. Bump VERSION (source de vérité)
[System.IO.File]::WriteAllText("$repo\VERSION", $Version, $utf8NoBom)
# 2. Bump package.json frontend (cohérence affichage UI)
$pkgPath = "$repo\frontend\package.json"
if (Test-Path $pkgPath) {
    $pkg = Get-Content $pkgPath -Raw
    $pkg = $pkg -replace '("version"\s*:\s*")[^"]*(")', "`${1}$Version`${2}"
    [System.IO.File]::WriteAllText($pkgPath, $pkg, $utf8NoBom)
}

# 3. Commit + tag annoté + push
& git add VERSION frontend/package.json
& git commit -m "chore(release): v$Version — $Message"
& git tag -a $tag -m $Message
& git push --follow-tags

Write-Host ""
Write-Host "[OK] Tag $tag poussé. La CI build + verify les images puis publie sur GHCR." -ForegroundColor Green
Write-Host "     Suivi : .\scripts\check-image-ready.ps1 $Version" -ForegroundColor Green
