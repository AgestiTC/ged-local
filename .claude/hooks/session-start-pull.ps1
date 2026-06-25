# session-start-pull.ps1 — Hook Claude Code SessionStart
# Fait un 'git pull' automatique au demarrage de chaque session Claude sur ce projet.
# Affiche le resultat via systemMessage pour que Claude voie l'etat git.
#
# Adapte du pattern Sapyn (cf. memory/feedback-dual-repo-choice ligne sync multi-poste).

$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$projectName = Split-Path $repo -Leaf

if (-not (Test-Path "$repo\.git")) {
    @{ systemMessage = "[$projectName] Repo introuvable a $repo - aucun pull effectue" } | ConvertTo-Json -Compress
    exit 0
}

$result = & git -C $repo pull *>&1 | Out-String
$result = $result.Trim()
if (-not $result) { $result = "(deja a jour)" }

$msg = "[$projectName] git pull au demarrage de session :`n$result"
@{ systemMessage = $msg } | ConvertTo-Json -Compress
