# session-end-warn.ps1 — Hook Claude Code SessionEnd
# Warn s'il reste des modifs non commitees, des commits non pushes, ou si du code
# a ete commit depuis le dernier tag (rappel release tag = rail unique tag-driven).
# Silencieux si tout est propre.
#
# Adapte du pattern Sapyn (cf. memory/feedback-workflow-unique : evite NetSight v0.4.3->v0.4.9
# 8 commits sans tag => NAS bloque sur v0.4.2).
#
# Source canonique : _modele-claude/claude-config/.claude/hooks/session-end-warn.ps1
# Ne pas modifier ce fichier dans un projet client sans le re-merger dans le modele.

$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$projectName = Split-Path $repo -Leaf

if (-not (Test-Path "$repo\.git")) { exit 0 }

$status = (& git -C $repo status --porcelain) -join "`n"

$ahead = 0
$aheadRaw = & git -C $repo rev-list --count '@{u}..HEAD' 2>$null
if ($aheadRaw) { try { $ahead = [int]$aheadRaw } catch {} }

# Commits de code (non-.md) depuis le dernier tag
$untaggedCode = $false
$untaggedCount = 0
$lastTag = & git -C $repo describe --tags --abbrev=0 2>$null
if ($LASTEXITCODE -eq 0 -and $lastTag) {
    $shas = (& git -C $repo log "$lastTag..HEAD" --format='%H' 2>$null) -split "`n" |
        Where-Object { $_ -and $_.Trim() }
    $untaggedCount = $shas.Count
    foreach ($sha in $shas) {
        $files = (& git -C $repo show --name-only --format= $sha 2>$null) -split "`n"
        foreach ($f in $files) {
            $f = $f.Trim()
            if ($f -and -not $f.EndsWith('.md')) {
                $untaggedCode = $true
                break
            }
        }
        if ($untaggedCode) { break }
    }
}

$lines = @()
if ($status) {
    $lines += "Modifs non commitees dans $projectName :"
    $lines += ($status -split "`n" | ForEach-Object { "  $_" })
    $lines += ""
}
if ($ahead -gt 0) {
    $lines += "$ahead commit(s) local(aux) non pousse(s) sur origin/main."
}
if ($untaggedCode) {
    $lines += "$untaggedCount commit(s) depuis le tag $lastTag dont des changements de code."
    $lines += "  -> Pense au release tag (sinon NAS ne pull pas le :latest) :"
    $lines += "     .\scripts\release.ps1 -Version X.Y.Z -Message '<sujet>'"
    $lines += ""
}

if ($lines.Count -eq 0) { exit 0 }

if ($status -or $ahead -gt 0) {
    $lines += "Pour synchroniser avant de quitter :"
    $lines += "  git add . ; git commit -m '...' ; git push"
}

$msg = "[$projectName RAPPEL avant de quitter]`n" + ($lines -join "`n")
@{ systemMessage = $msg } | ConvertTo-Json -Compress
