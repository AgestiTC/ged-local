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
  .\scripts\verifier-deploiement.ps1 -Version 1.76.1 -Url http://192.168.42.83:3003
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
# Convention RÉELLE du registre : le tag d'image est la version NUE, sans « v ».
# Vérifié le 06/09 : « 1.73.0 » est présent, « v1.73.0 » n'existe pas. Les tags GIT,
# eux, portent bien le « v » — les deux ne se confondent pas.
$tag = $Version
$ok = $true

function Ecrire($etat, $texte) {
    $couleur = switch ($etat) { 'OK' { 'Green' } 'KO' { 'Red' } default { 'Yellow' } }
    Write-Host ("[{0}] {1}" -f $etat, $texte) -ForegroundColor $couleur
}

# Empreinte d'une image du registre, ou $null si elle est absente / inaccessible.
#
# ⚠️ NE PAS lire `.config.digest` : nos images sont publiées en **index OCI**
# (`application/vnd.oci.image.index.v1+json`), qui porte un tableau `manifests[]` et
# AUCUN champ `config`. Une première version de ce script le lisait quand même, obtenait
# `$null`, et déclarait donc « absent du registre » des images fraîchement poussées —
# un outil de vérification qui ment est pire que pas d'outil. (Constaté le 06/09, sur des
# images dont le `docker push` venait de rendre le digest.)
#
# ⚠️ NE PAS comparer le texte entier du manifeste non plus : buildx joint à chaque build un
# **manifeste d'attestation** (provenance), qui change à CHAQUE invocation même quand toutes
# les couches sont en cache. Comparer l'index complet déclarait donc « latest pointe sur un
# autre build » alors que les deux images étaient rigoureusement identiques (constaté le 06/09).
# On isole l'image réelle : les attestations se reconnaissent à `platform.architecture = unknown`.
function Empreinte($image) {
    $json = (& docker manifest inspect $image 2>$null) -join "`n"
    if ($LASTEXITCODE -ne 0 -or -not $json.Trim()) { return $null }
    try {
        $index = $json | ConvertFrom-Json
        if ($index.manifests) {
            $reel = $index.manifests | Where-Object { $_.platform.architecture -ne 'unknown' }
            if ($reel) { return ($reel.digest -join ',') }
        }
    } catch { }
    return $json   # image simple (pas un index) : le texte fait l'affaire
}

Write-Host "== Version attendue : $Version (tag d'image $tag) ==" -ForegroundColor Cyan

# ── 1 et 2. Le registre ───────────────────────────────────────────────────────
if (-not $SansPresence) {
    foreach ($nom in @('docflow-backend', 'docflow-frontend')) {
        $img    = "$Registry/$Namespace/$nom`:$tag"
        $imgLat = "$Registry/$Namespace/$nom`:latest"

        $dTag = Empreinte $img
        if (-not $dTag) {
            Ecrire 'KO' "$img absent du registre — build-push.ps1 n'a pas (encore) tourné."
            $ok = $false
            continue
        }
        Ecrire 'OK' "$img présent."

        # LE piège : compose tire `latest` par défaut. Un tag versionné poussé sans
        # republier `latest` donne un déploiement qui « réussit » sans rien changer.
        $dLat = Empreinte $imgLat
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
# On RÉESSAIE : juste après un `up -d`, le backend redémarre et le nginx du frontend
# répond 502 pendant quelques secondes. Interroger une seule fois donnait un verdict qui
# dépendait de la seconde où on tombait (vécu le 07/09 : 502 à la vérification, 1.90.0
# servie trente secondes plus tard).
Write-Host "`n== Version servie par $Url ==" -ForegroundColor Cyan
$servie = $null
$dernierEchec = ''
foreach ($essai in 1..6) {
    try {
        $servie = (Invoke-RestMethod -Uri "$Url/api/version" -TimeoutSec 8).version
        break
    } catch {
        $dernierEchec = $_.Exception.Message
        if ($essai -lt 6) {
            Write-Host "   … démarrage en cours ($dernierEchec) — nouvel essai dans 5 s" -ForegroundColor DarkGray
            Start-Sleep -Seconds 5
        }
    }
}

if ($null -eq $servie) {
    # 🔴 KO, et surtout PAS un simple avertissement : une prod qu'on n'a pas pu interroger
    # n'est pas une prod vérifiée. Le rendre « ?? » faisait conclure « chaîne complète
    # vérifiée » sans avoir obtenu le seul verdict qui compte (défaut constaté le 07/09).
    Ecrire 'KO' "$Url injoignable après 6 essais ($dernierEchec) — version NON vérifiée."
    $ok = $false
} elseif ($servie -eq $Version) {
    Ecrire 'OK' "La prod sert $servie."
} else {
    Ecrire 'KO' "La prod sert $servie, attendu $Version — le déploiement n'a pas pris."
    $ok = $false
}

Write-Host ""
if ($ok) {
    Write-Host "[OK] Chaîne complète vérifiée pour $tag." -ForegroundColor Green
} else {
    Write-Host "[A FAIRE] Voir les lignes KO ci-dessus. Une seule commande fait tout :" -ForegroundColor Yellow
    Write-Host "   .\scripts\deployer.ps1            # build + push (X.Y.Z ET latest) + LXC + vérification"
    Write-Host "   (si un build échoue sur des « Invalid character » : .\scripts\deployer.ps1 -SansCache)"
    exit 1
}
