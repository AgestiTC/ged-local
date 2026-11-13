<#
.SYNOPSIS
  Désinstalle l'agent de poste de « rangement » : arrête et supprime le service « RangementAgent »,
  puis efface le programme. Avec -Tout, efface aussi la configuration (jeton) et le journal.

  Ne touche à rien d'autre : l'identité (service, dossiers) est propre à rangement.
#>
[CmdletBinding()]
param(
    [switch]$Tout,
    [string]$DossierProgramme = (Join-Path $env:ProgramFiles "Rangement Agent"),
    [string]$DossierDonnees = (Join-Path $env:ProgramData "Rangement")
)
$ErrorActionPreference = "Stop"
$NomService = "RangementAgent"

$service = Get-Service -Name $NomService -ErrorAction SilentlyContinue
if ($service) {
    if ($service.Status -ne "Stopped") {
        Stop-Service -Name $NomService -Force
        $service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
    }
    & sc.exe delete $NomService | Out-Null
    Write-Host "Service $NomService supprimé."
}
if (Test-Path $DossierProgramme) { Remove-Item -Recurse -Force $DossierProgramme }
if ($Tout -and (Test-Path $DossierDonnees)) {
    Remove-Item -Recurse -Force $DossierDonnees
    Write-Host "Configuration et journal effacés. Pensez à désactiver le poste dans Carte → Postes."
}
