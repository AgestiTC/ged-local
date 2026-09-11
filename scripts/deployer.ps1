<#
.SYNOPSIS
  Déploie Matothèque de bout en bout : build + push des images, déploiement sur le LXC,
  puis VÉRIFICATION. Une seule commande, un seul rail.

.DESCRIPTION
  Calqué sur le rail de Foulée (projet voisin, même conteneur LXC) : « livré » ne veut pas
  dire « poussé », il veut dire « servi par la prod, et vérifié ». Tant que /api/version
  n'a pas répondu le bon numéro, rien n'est livré.

  Ce script remplace l'enchaînement à la main qui a coûté plusieurs incidents :

  - **une seule construction, deux étiquettes** (`X.Y.Z` et `latest`) au lieu de deux
    passes de `build-push.ps1`. Deux passes produisent deux manifestes différents — le
    second build change l'attestation même à couches identiques — et `latest` finit par
    désigner un autre build que la version. C'est exactement le piège du 06/09, où
    `pull` + `up -d` + `restart` ont tous « réussi » sans rien changer ;
  - **recette de l'image avant publication** : on vérifie qu'`APP_VERSION` est bien
    embarquée. Sans elle l'UI affiche « vdev », et ça ne se voit qu'une fois en prod ;
  - **déploiement par SSH** (clé `id_proxmox`), donc scriptable, donc reproductible ;
  - **vérification finale obligatoire** par `verifier-deploiement.ps1`.

.PARAMETER Version
  Version semver SANS préfixe « v » (le tag d'IMAGE est nu ; le tag GIT, lui, porte le v).
  Par défaut : le fichier VERSION du dépôt.

.PARAMETER SansCache
  Reconstruit sans cache. À utiliser si un fichier arrive vide dans le contexte Docker
  (symptôme : erreurs TypeScript « Invalid character » en masse sur un fichier pourtant
  sain) : BuildKit réutilise sinon son instantané périmé.

.PARAMETER SansDeploiement
  S'arrête après le push : construit, éprouve et publie, sans toucher à la prod.

.EXAMPLE
  .\scripts\deployer.ps1
  .\scripts\deployer.ps1 -Version 1.90.0 -SansCache
#>
param(
    [string]$Version,
    [string]$Registre = 'git.agesti.fr',
    [string]$Espace   = 'agestitc',
    [string]$Hote     = 'root@192.168.42.83',
    [string]$Cle      = "$HOME\.ssh\id_proxmox",
    [string]$Dossier  = '/opt/docflow',
    [switch]$SansCache,
    [switch]$SansDeploiement
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repo

function Etape($texte) { Write-Host "`n== $texte ==" -ForegroundColor Cyan }
function Ok($texte)    { Write-Host "[OK] $texte" -ForegroundColor Green }

if (-not $Version) { $Version = (Get-Content "$repo\VERSION" -Raw).Trim() }
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version invalide '$Version' — format attendu X.Y.Z, SANS « v » (convention du registre)."
}

$backend  = "$Registre/$Espace/docflow-backend"
$frontend = "$Registre/$Espace/docflow-frontend"
$cache    = if ($SansCache) { @('--no-cache') } else { @() }

# ── 1. Registre ──────────────────────────────────────────────────────────────
Etape "Login $Registre"
docker login $Registre
if ($LASTEXITCODE -ne 0) { throw "docker login a échoué." }

# ── 2. Backend : une construction, deux étiquettes ───────────────────────────
# APP_VERSION est lue par config.py → /api/version → numéro affiché dans l'UI. Le fichier
# VERSION n'est PAS dans le contexte ./backend : sans ce build-arg, l'image dit « dev ».
Etape "Build backend $Version (+ latest)"
docker build @cache --build-arg APP_VERSION=$Version -t "${backend}:$Version" -t "${backend}:latest" "$repo\backend"
if ($LASTEXITCODE -ne 0) { throw "build backend a échoué." }

# Recette locale — l'équivalent du job `verify` de Foulée, avant publication et sans
# base de données : on lit la version embarquée plutôt que de démarrer l'application.
Etape "Recette de l'image backend"
$embarquee = (docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${backend}:$Version" |
              Select-String '^APP_VERSION=' | ForEach-Object { $_.ToString().Split('=', 2)[1] }).Trim()
if ($embarquee -ne $Version) {
    throw "L'image embarque APP_VERSION='$embarquee' au lieu de '$Version' — l'UI afficherait un faux numéro."
}
Ok "APP_VERSION=$embarquee embarquée dans l'image."

Etape "Push backend"
docker push "${backend}:$Version"; if ($LASTEXITCODE -ne 0) { throw "push backend $Version a échoué." }
docker push "${backend}:latest"; if ($LASTEXITCODE -ne 0) { throw "push backend latest a échoué." }

# ── 3. Frontend ──────────────────────────────────────────────────────────────
# VITE_API_URL vide → URLs relatives, nginx proxifie /api. Y mettre une IP la figerait
# dans le bundle et casserait la prod pour tout autre poste.
Etape "Build frontend $Version (+ latest)"
docker build @cache --build-arg VITE_API_URL="" -t "${frontend}:$Version" -t "${frontend}:latest" "$repo\frontend"
if ($LASTEXITCODE -ne 0) { throw "build frontend a échoué (voir « Invalid character » → relancer avec -SansCache)." }

Etape "Push frontend"
docker push "${frontend}:$Version"; if ($LASTEXITCODE -ne 0) { throw "push frontend $Version a échoué." }
docker push "${frontend}:latest"; if ($LASTEXITCODE -ne 0) { throw "push frontend latest a échoué." }

if ($SansDeploiement) {
    Ok "Images publiées. Déploiement non demandé (-SansDeploiement) — la prod n'a PAS bougé."
    exit 0
}

# ── 4. Déploiement sur le LXC ────────────────────────────────────────────────
# `restart frontend` est obligatoire, pas prudentiel : sans lui le nginx du frontend garde
# l'ANCIENNE IP du backend → « tout rouge », alors que rien n'est perdu.
#
# ⚠️ ON NE TIRE QUE `backend` ET `frontend`, et c'est délibéré. Ce sont les SEULES images que
# ce script publie, et elles viennent de Gitea — un registre du réseau local. Un `pull` nu
# tire aussi tika, pgvector et clamav depuis Docker Hub : le déploiement dépendait donc d'une
# sortie Internet et d'une résolution DNS depuis le LXC, pour des images DÉJÀ PRÉSENTES et qui
# n'ont pas changé. Le 11/09/2026, deux déploiements d'affilée ont échoué sur
# « lookup auth.docker.io … i/o timeout » alors que les images utiles étaient publiées et que
# rien, dans l'application, ne clochait.
#
# Effet de bord assumé, et souhaitable : une nouvelle version de tika ou de postgres n'arrive
# plus par surprise à l'occasion d'un déploiement applicatif. Ces images sont épinglées ; les
# mettre à jour est une décision, et elle se prend à part (`docker compose pull tika`).
Etape "Déploiement sur ${Hote}:${Dossier}"
if (-not (Test-Path $Cle)) {
    throw "Clé SSH introuvable ($Cle). Déployer à la main : ssh $Hote puis cd $Dossier ; docker compose pull backend frontend ; docker compose up -d ; docker compose restart frontend"
}
ssh -i $Cle -o BatchMode=yes $Hote "cd $Dossier && docker compose pull backend frontend && docker compose up -d && docker compose restart frontend"
if ($LASTEXITCODE -ne 0) { throw "Le déploiement distant a échoué — la prod sert probablement encore l'ancienne version." }

# ── 5. Le seul verdict qui compte ────────────────────────────────────────────
Etape "Vérification"
& "$repo\scripts\verifier-deploiement.ps1" -Version $Version
if ($LASTEXITCODE -ne 0) {
    throw "Déploiement NON confirmé — voir les lignes KO ci-dessus. Ne pas annoncer la livraison."
}
Ok "Matothèque $Version est en production, et vérifiée."
