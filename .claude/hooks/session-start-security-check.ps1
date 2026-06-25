# session-start-security-check.ps1 — Hook Claude Code SessionStart additionnel
# Verifie la date du dernier audit securite (.claude/.last-security-audit) et alerte
# si > 30 jours. Silencieux si OK.
#
# Cf. memory/feedback-security-maintained : audit on-demand via scripts/security-audit.ps1
# + CI hebdo + rappel humain 30j (ce hook).

$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$projectName = Split-Path $repo -Leaf
$marker = Join-Path $repo ".claude\.last-security-audit"

$maxDays = 30

if (-not (Test-Path $marker)) {
    $msg = "[$projectName SECURITE] Aucun audit securite n'a encore ete effectue sur ce projet.`n" +
           "  Lance : .\scripts\security-audit.ps1`n" +
           "  Cadence cible : tous les 3 mois ou avant chaque release majeure."
    @{ systemMessage = $msg } | ConvertTo-Json -Compress
    exit 0
}

try {
    $lastDateStr = (Get-Content $marker -Raw).Trim()
    $lastDate = [datetime]::ParseExact($lastDateStr, "yyyy-MM-dd", $null)
} catch {
    # Si le marker est corrompu, traite comme absent
    $msg = "[$projectName SECURITE] Marker corrompu ($marker = '$lastDateStr')`n" +
           "  Relance : .\scripts\security-audit.ps1 (regenere le marker)."
    @{ systemMessage = $msg } | ConvertTo-Json -Compress
    exit 0
}

$daysSince = [int]((Get-Date) - $lastDate).TotalDays

if ($daysSince -le $maxDays) {
    # Audit recent : silencieux
    exit 0
}

$msg = "[$projectName SECURITE] Dernier audit : $($lastDate.ToString('yyyy-MM-dd')) ($daysSince jours).`n" +
       "  -> Relance : .\scripts\security-audit.ps1`n" +
       "  Verifie aussi les Dependabot alerts sur github.com/AgestiTC/<projet>/security/dependabot"
@{ systemMessage = $msg } | ConvertTo-Json -Compress
