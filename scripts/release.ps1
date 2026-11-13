<#
.SYNOPSIS
  Release Matothèque : bump VERSION + sync sources + commit + tag annoté + push --follow-tags.
.DESCRIPTION
  Marque la release dans Git : bump VERSION, commit, tag annoté, push --follow-tags.
  À lancer depuis main (après merge de develop).

  🔴 CE SCRIPT NE PUBLIE AUCUNE IMAGE. Le workflow GitHub déclenché par le tag pousse sur
  GHCR, que personne ne tire — le registre réel est Gitea, alimenté depuis Windows. Croire
  l'inverse fait annoncer une livraison qui n'existe pas (l'en-tête précédent promettait
  « la CI publie les images sur GHCR »).
  Les images se publient et se déploient avec : .\scripts\deployer.ps1
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

# 3. Commit + tag annoté + push — vers GITEA, explicitement.
# Avant : `git push --follow-tags` poussait vers le dépôt SUIVI par la branche, qui est `origin`
# (GitHub, vestige) dans la plupart des arbres : on aurait publié des dizaines de commits sur
# GitHub, et laissé Gitea — le seul dépôt réel — sans le tag (constaté le 13/11/2026).
$remote = 'gitea'
if (-not (& git remote | Where-Object { $_ -eq $remote })) {
    throw "Remote '$remote' absent : ajouter git.agesti.fr (git remote add gitea https://git.agesti.fr/AgestiTC/GED-LOCAL.git)."
}
& git add VERSION frontend/package.json
& git commit -m "chore(release): v$Version — $Message"
& git tag -a $tag -m $Message
& git push $remote "HEAD:refs/heads/main" "refs/tags/$tag"
if ($LASTEXITCODE -ne 0) { throw "Push vers $remote refusé — la release n'est PAS publiée." }

Write-Host ""
Write-Host "[OK] Tag $tag poussé — la release est MARQUÉE dans Git, rien n'est publié." -ForegroundColor Green
Write-Host "     Le tag ne construit AUCUNE image utilisable : le registre réel est Gitea," -ForegroundColor Yellow
Write-Host "     alimenté depuis Windows. La prod sert encore la version précédente." -ForegroundColor Yellow
Write-Host "     Publier + déployer : .\scripts\deployer.ps1" -ForegroundColor Green
