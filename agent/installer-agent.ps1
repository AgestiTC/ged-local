<#
.SYNOPSIS
  Installe — ou met à jour — l'agent de poste de « rangement » en service Windows.

.DESCRIPTION
  1. copie rangement-agent.exe dans « Program Files\Rangement Agent » ;
  2. écrit sa configuration dans « ProgramData\Rangement\agent.json » (serveur, jeton, dossiers
     autorisés), dossier réservé à SYSTEM et aux Administrateurs : le jeton n'est lisible que d'eux ;
  3. crée le service « RangementAgent » (démarrage automatique, relance en cas d'arrêt) et le démarre.

  Mise à jour : relancer le script SANS -Jeton garde la configuration existante et ne
  remplace que l'exe.

  L'identité Windows (nom du service, dossiers) est propre à rangement : elle ne touche
  jamais à un autre agent installé sur le poste (NetSight, etc.). Elle doit rester
  identique à agent/identite.go — un test Go le vérifie.

.EXAMPLE
  .\installer-agent.ps1 -Serveur http://192.168.42.83:3003 -Jeton mato_xxx -Racines "C:\Users","D:\"

.EXAMPLE
  .\installer-agent.ps1        # mise à jour de l'exe, configuration conservée
#>
[CmdletBinding()]
param(
    [string]$Serveur,
    [string]$Jeton,
    [string[]]$Racines = @("C:\Users"),
    [string]$Exe = (Join-Path $PSScriptRoot "rangement-agent.exe"),
    [string]$DossierProgramme = (Join-Path $env:ProgramFiles "Rangement Agent"),
    [string]$DossierDonnees = (Join-Path $env:ProgramData "Rangement"),
    # Essais : copie, configuration et droits, sans créer ni démarrer le service.
    [switch]$SansService
)
$ErrorActionPreference = "Stop"
$NomService = "RangementAgent"
$NomAffiche = "Rangement - agent de poste"

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $SansService -and -not (Test-Admin)) {
    throw "Lancez ce script dans un PowerShell « Exécuter en tant qu'administrateur »."
}
if (-not (Test-Path $Exe)) { throw "Exe introuvable : $Exe" }
$version = & $Exe -version
Write-Host "Agent : $version"

$cheminConfig = Join-Path $DossierDonnees "agent.json"
$nouvelleConfig = [bool]$Jeton
if (-not $nouvelleConfig -and -not (Test-Path $cheminConfig)) {
    throw "Première installation : -Serveur et -Jeton sont obligatoires (le jeton s'obtient dans Carte → Postes)."
}
if ($nouvelleConfig) {
    if (-not $Serveur -or $Serveur -notmatch '^https?://[^/\s]+') { throw "-Serveur doit être une adresse http(s) complète." }
    if ($Jeton -notmatch '^mato_[A-Za-z0-9_\-]+$') { throw "Jeton invalide (il commence par « mato_ »)." }
    foreach ($r in $Racines) {
        if ($r -notmatch '^[A-Za-z]:\\') { throw "Racine « $r » : chemin complet sur un disque local attendu (ex. C:\Users)." }
    }
}

# 1. Arrêt du service s'il existe (mise à jour).
$service = Get-Service -Name $NomService -ErrorAction SilentlyContinue
if ($service -and -not $SansService -and $service.Status -ne "Stopped") {
    Stop-Service -Name $NomService -Force
    $service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
}

# 2. Programme.
New-Item -ItemType Directory -Force -Path $DossierProgramme | Out-Null
$exeInstalle = Join-Path $DossierProgramme "rangement-agent.exe"
Copy-Item -Force $Exe $exeInstalle

# 3. Dossier des données, et ses droits AVANT d'y écrire le jeton : SYSTEM (S-1-5-18) et
# Administrateurs (S-1-5-32-544) seulement — le jeton est un secret. En essai,
# l'utilisateur courant garde l'accès pour pouvoir relire et nettoyer.
New-Item -ItemType Directory -Force -Path $DossierDonnees | Out-Null
$droits = @("*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F")
if ($SansService) {
    $droits += "*$([Security.Principal.WindowsIdentity]::GetCurrent().User.Value):(OI)(CI)F"
}
& icacls $DossierDonnees /inheritance:r /grant:r @droits | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls a échoué ($LASTEXITCODE) : droits du dossier $DossierDonnees non posés." }
# Un agent.json existant (mise à jour) reprend l'héritage restreint du dossier.
if (Test-Path $cheminConfig) { & icacls $cheminConfig /reset | Out-Null }

# 4. Configuration : UTF-8 SANS BOM (le lecteur JSON de l'agent refuse le BOM).
if ($nouvelleConfig) {
    $config = [ordered]@{ serveur_url = $Serveur.TrimEnd("/"); jeton = $Jeton; racines_autorisees = @($Racines) }
    $json = $config | ConvertTo-Json -Depth 3
    [IO.File]::WriteAllText($cheminConfig, $json, (New-Object Text.UTF8Encoding $false))
}

if ($SansService) {
    Write-Host "Essai : fichiers et droits en place, service non créé." -ForegroundColor Yellow
    return
}

# 5. Service.
if (-not $service) {
    New-Service -Name $NomService -BinaryPathName "`"$exeInstalle`"" -DisplayName $NomAffiche `
        -StartupType Automatic -Description "Inventaire des dossiers de ce PC pour rangement (lecture seule)." | Out-Null
    # Relance automatique : 1 min, 1 min, puis 10 min ; compteur remis à zéro chaque jour.
    & sc.exe failure $NomService reset= 86400 actions= restart/60000/restart/60000/restart/600000 | Out-Null
}
Start-Service -Name $NomService
Write-Host "Service $NomService démarré. Journal : $(Join-Path $DossierDonnees 'agent.log')" -ForegroundColor Green
