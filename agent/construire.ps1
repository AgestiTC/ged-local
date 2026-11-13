<#
.SYNOPSIS
  Construit l'agent Windows : tests Go, exe avec sa version embarquée, vérification de cette
  version (un exe « dev » ne doit jamais partir), empreinte SHA-256 et archive prête à copier.

  Sortie : agent/dist/rangement-agent-<version>.zip
#>
$ErrorActionPreference = "Stop"
$ici = $PSScriptRoot
$version = (Get-Content (Join-Path $ici "VERSION") -Raw).Trim()
Push-Location $ici
try {
    go test ./...
    if ($LASTEXITCODE -ne 0) { throw "tests Go en échec" }
    New-Item -ItemType Directory -Force -Path dist | Out-Null
    $env:GOOS = "windows"; $env:GOARCH = "amd64"; $env:CGO_ENABLED = "0"
    try {
        go build -trimpath -ldflags "-s -w -X main.VersionAgent=$version" -o dist/rangement-agent.exe .
        if ($LASTEXITCODE -ne 0) { throw "compilation en échec" }
    } finally {
        Remove-Item Env:GOOS, Env:GOARCH, Env:CGO_ENABLED -ErrorAction SilentlyContinue
    }
    $vu = & .\dist\rangement-agent.exe -version
    if ($vu -ne "rangement-agent $version") { throw "version embarquée « $vu » au lieu de $version" }
    Copy-Item -Force installer-agent.ps1, desinstaller-agent.ps1 dist/
    $h = (Get-FileHash dist/rangement-agent.exe -Algorithm SHA256).Hash.ToLower()
    "$h  rangement-agent.exe" | Set-Content dist/SHA256SUMS.txt -Encoding ascii
    $zip = "dist/rangement-agent-$version.zip"
    Compress-Archive -Force -Path dist/rangement-agent.exe, dist/installer-agent.ps1, dist/desinstaller-agent.ps1, dist/SHA256SUMS.txt -DestinationPath $zip
    Write-Host "Agent $version construit : $zip (SHA-256 $h)" -ForegroundColor Green
} finally {
    Pop-Location
}
