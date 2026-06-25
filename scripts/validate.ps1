<#
.SYNOPSIS
  Valide une instance déployée de Matothèque (smoke test runtime).
.DESCRIPTION
  Interroge /healthz, /api/version et /health sur l'hôte cible et affiche le résultat.
.PARAMETER TargetHost
  Hôte ou IP du backend (défaut : localhost).
.PARAMETER Port
  Port HTTP du backend (défaut : 8000).
.EXAMPLE
  .\scripts\validate.ps1 -TargetHost 192.168.42.200 -Port 8000
#>
param(
    [string]$TargetHost = 'localhost',
    [int]$Port = 8000
)

$ErrorActionPreference = 'Continue'
$base = "http://${TargetHost}:${Port}"
$fail = $false

function Test-Endpoint($path, [int]$expected = 200) {
    $url = "$base$path"
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
        if ($resp.StatusCode -eq $expected) {
            Write-Host "[OK] $path -> $($resp.StatusCode)" -ForegroundColor Green
            return $resp.Content
        }
        Write-Host "[KO] $path -> $($resp.StatusCode) (attendu $expected)" -ForegroundColor Red
    } catch {
        Write-Host "[KO] $path -> injoignable ($($_.Exception.Message))" -ForegroundColor Red
    }
    $script:fail = $true
    return $null
}

Write-Host "== Validation $base ==" -ForegroundColor Cyan
Test-Endpoint '/healthz' | Out-Null
$ver = Test-Endpoint '/api/version'
if ($ver) { Write-Host "    version : $ver" -ForegroundColor Gray }
Test-Endpoint '/health' | Out-Null

Write-Host ""
if ($fail) { Write-Host "[ECHEC] Au moins un endpoint KO." -ForegroundColor Red; exit 1 }
Write-Host "[OK] Instance saine." -ForegroundColor Green
