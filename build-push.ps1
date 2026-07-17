# ============================================================
# build-push.ps1 — Build + push des images Matothèque (registre Gitea)
# ============================================================
# À lancer depuis le PC Windows, à la racine du projet :
#   powershell -ExecutionPolicy Bypass -File .\build-push.ps1
#   (ou .\build-push.ps1 -Version v1.11.0)
#
# Prérequis : Docker Desktop démarré. Le registre s'authentifie par token Gitea
# (write:package), PAS par clé RSA/SSH.
# ============================================================

param(
    [string]$Version   = "latest",          # ou "v1.11.0"
    [string]$Registry  = "git.agesti.fr",
    [string]$Namespace = "agestitc"          # MINUSCULES obligatoire (règle Docker)
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

# Version applicative EMBARQUÉE dans l'image backend (→ /api/version, affichée dans l'UI).
# Source de vérité = fichier VERSION, indépendante du TAG d'image : sans ce build-arg le
# Dockerfile retombe sur `ARG APP_VERSION=dev` → l'appli affiche « vdev » en prod.
$AppVersion = (Get-Content "$Root\VERSION" -Raw).Trim()
if (-not $AppVersion) { throw "Fichier VERSION vide ou introuvable : impossible d'embarquer la version." }

$backend  = "$Registry/$Namespace/docflow-backend:$Version"
$frontend = "$Registry/$Namespace/docflow-frontend:$Version"

Write-Host "== Login $Registry ==" -ForegroundColor Cyan
docker login $Registry
if ($LASTEXITCODE -ne 0) { throw "docker login a échoué" }

Write-Host "== Build + push backend  ($backend, APP_VERSION=$AppVersion) ==" -ForegroundColor Cyan
docker build --build-arg APP_VERSION=$AppVersion -t $backend "$Root\backend"
if ($LASTEXITCODE -ne 0) { throw "build backend a échoué" }
docker push $backend
if ($LASTEXITCODE -ne 0) { throw "push backend a échoué" }

Write-Host "== Build + push frontend ($frontend) ==" -ForegroundColor Cyan
# VITE_API_URL vide → nginx proxifie /api vers le backend (pas d'IP figée dans le build)
docker build --build-arg VITE_API_URL="" -t $frontend "$Root\frontend"
if ($LASTEXITCODE -ne 0) { throw "build frontend a échoué" }
docker push $frontend
if ($LASTEXITCODE -ne 0) { throw "push frontend a échoué" }

Write-Host ""
Write-Host "OK — images poussées :" -ForegroundColor Green
Write-Host "   $backend"
Write-Host "   $frontend"
Write-Host "Packages privés : la VM doit avoir 'docker login git.agesti.fr'." -ForegroundColor Yellow
