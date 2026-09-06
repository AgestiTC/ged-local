<#
.SYNOPSIS
  Vérifie qu'un déploiement a REELLEMENT eu lieu : registre à jour, puis prod à jour.

.DESCRIPTION
  Un bandeau « nouvelle version » ne peut pas détecter l'ABSENCE de nouvelle version :
  quand rien n'a été publié, il ne s'affiche pas, et son silence se lit « je suis à jour ».
  C'est exactement ce qui s'est produit le 06/09/2026 — `docker compose pull` a dit
  « Pulled », `up -d` et `restart` ont réussi, et /api/version répondait toujours 1.73.0,
  parce que `build-push.ps1` n'avait pas tourné et que le tag `latest` pointait encore sur
  l'ancien build. (Diagnostic structurel dû à la session FOULEE.)

  Ce script répond donc, dans l'ordre, aux trois questions qui font foi :

    1. le registre porte-t-il le tag que je crois avoir poussé ?
    2. `latest` pointe-t-il sur CE build, ou sur un ancien ? <- le piège du 06/09
    3. la prod sert-elle cette version ?

  Aucun de ces contrôles ne modifie quoi que ce soit. C'est un constat, pas une action.

.PARAMETER Version
  Version semver SANS préfixe v. Par défaut : le fichier VERSION du dépôt.

.PARAMETER Url
  Racine HTTP de la prod (frontend, qui proxifie /api). Défaut : le LXC 102.

.PARAMETER SansPresence
  Saute les contrôles de registre (utile hors ligne, ou sans docker login).

.EXAMPLE
  .\scripts\verifier-deploiement.ps1
  .\scripts\verifier-deploiement.ps1 -Version 1.76.0 -Url http://192.168.42.83:3003
#>
param(
    [string]$Version,
    [string]$Url       = 'http://192.168.42.83:3003',
    [string]$Registry  = 'git.agesti.fr',
    [string]$Namespace = 'agestitc',
    [switch]$SansPresence
)

$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path "$PSScriptRoot\..").Path

if (-not $Version) {
    $Version = (Get-Content "$repo\VERSION" -Raw).Trim()
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version invalide '$Version' — format attendu X.Y.Z (sans 'v')."
}
$tag = "v$Version"
$ok = $true

function Ecrire($etat, $texte) {
    $couleur = switch ($etat) { 'OK' { 'Green' } 'KO' { 'Red' } default { 'Yellow' } }
    Write-Host ("[{0}] {1}" -f $etat, $texte) -ForegroundColor $couleur
}

# Digest d'un manifeste, ou $null s'il est absent / inaccessible.
function Digest($image) {
    $json = & docker manifest inspect $image 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $json) { return $null }
    # Le digest du manifeste lui-même n'est pas dans la sortie : on hache la config,
    # ce qui suffit à comparer deux tags entre eux (même build = même config).
    try { return ($json | ConvertFrom-Json).config.digest } catch { return $null }
}

Write-Host "== Version attendue : $Version (tag d'image $tag) ==" -ForegroundColor Cyan

# ── 1 et 2. Le registre ───────────────────────────────────────────────────────
if (-not $SansPresence) {
    foreach ($nom in @('docflow-backend', 'docflow-frontend')) {
        $img    = "$Registry/$Namespace/$nom`:$tag"
        $imgLat = "$Registry/$Namespace/$nom`:latest"

        $dTag = Digest $img
        if (-not $dTag) {
            Ecrire 'KO' "$img absent du registre — build-push.ps1 n'a pas (encore) tourné."
            $ok = $false
            continue
        }
        Ecrire 'OK' "$img présent."

        # LE piège : compose tire `latest` par défaut. Un tag versionné poussé sans
        # republier `latest` donne un déploiement qui « réussit » sans rien changer.
        $dLat = Digest $imgLat
        if (-not $dLat) {
            Ecrire '??' "$imgLat introuvable — si le .env prod utilise 'latest', le pull ne trouvera rien."
        } elseif ($dLat -ne $dTag) {
            Ecrire 'KO' "$imgLat pointe sur un AUTRE build que $tag. Relance : .\build-push.ps1 -Version latest"
            $ok = $false
        } else {
            Ecrire 'OK' "$imgLat pointe bien sur le même build que $tag."
        }
    }
} else {
    Ecrire '??' 'Contrôles de registre sautés (-SansPresence).'
}

# ── 3. La prod ────────────────────────────────────────────────────────────────
Write-Host "`n== Version servie par $Url ==" -ForegroundColor Cyan
try {
    $r = Invoke-RestMethod -Uri "$Url/api/version" -TimeoutSec 8
    if ($r.version -eq $Version) {
        Ecrire 'OK' "La prod sert $($r.version)."
    } else {
        Ecrire 'KO' "La prod sert $($r.version), attendu $Version — le déploiement n'a pas pris."
        $ok = $false
    }
} catch {
    Ecrire '??' "$Url injoignable depuis ce poste ($($_.Exception.Message))."
}

Write-Host ""
if ($ok) {
    Write-Host "[OK] Chaîne complète vérifiée pour $tag." -ForegroundColor Green
} else {
    Write-Host "[A FAIRE] Voir les lignes KO ci-dessus. Rappel de l'ordre :" -ForegroundColor Yellow
    Write-Host "   1. .\build-push.ps1 -Version $tag   puis   .\build-push.ps1 -Version latest"
    Write-Host "   2. sur le LXC : docker compose pull ; docker compose up -d ; docker compose restart frontend"
    Write-Host "   3. relancer ce script"
    exit 1
}
