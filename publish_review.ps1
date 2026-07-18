<#
    publish_review.ps1
    -----------------------------------------------------------------------
    The automation bridge: takes the newest DIGEST Markdown your "AI in
    education reviews" task produces and pushes it into the repo's input/
    folder, which triggers the GitHub Actions pipeline that builds the episode
    and updates the podcast feed. No manual steps.

    Run it on a schedule a few minutes AFTER your digest task (see README).

    EDIT the paths below to match your machine, then you never touch it again.
#>

# === EDIT THESE ========================================================== #

# Your local clone of the repo (the folder that contains generate_podcast.py):
$RepoPath  = "C:\Users\avivb\ClaudeCode\AI-EDU-Podacast"

# The folder where your "AI in education reviews" task saves the .md digest:
$SourceDir = "C:\Users\avivb\ClaudeCode\AI-Edu-Publications"

# Only files matching this pattern are treated as digests to publish. This is
# what stops it from grabbing "AI_in_Education_Sources.md" or other stray files.
$DigestPattern = "AI_in_Education_Digest_*.md"

# ========================================================================= #

$ErrorActionPreference = "Continue"
$log = Join-Path $RepoPath "publish_review.log"

# Write to the log file and the console ONLY. It must NOT return anything into
# the pipeline, or it pollutes the exit codes of the git calls below.
function Log($m) {
    $line = "$(Get-Date -Format s)  $m"
    Add-Content -Path $log -Value $line
    Write-Host $line
}

# Run a git command, log all its output, and return its real exit code.
# Nothing here leaks into the pipeline except the final integer exit code.
function Invoke-Git {
    $out = & git @args 2>&1
    foreach ($line in $out) { Log "git: $line" }
    return $LASTEXITCODE
}

try {
    Set-Location $RepoPath

    # 1. Find the newest DIGEST file (ignores Sources and anything else).
    $newest = Get-ChildItem -Path $SourceDir -Filter $DigestPattern -File |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $newest) {
        Log "No files matching '$DigestPattern' in $SourceDir - nothing to do."
        exit 0
    }
    Log "Newest digest: $($newest.FullName)"

    # 2. Copy it into input\ .
    $dest = Join-Path $RepoPath "input\$($newest.Name)"
    if ($newest.FullName -ne $dest) {
        Copy-Item $newest.FullName $dest -Force
        Log "Copied to $dest"
    }

    # 3. Sync with GitHub first. The Actions workflow commits the generated MP3
    #    and feed.xml back to main, so the local clone is usually behind and a
    #    plain push would be rejected. Rebase local state on top of origin/main.
    if ((Invoke-Git fetch origin main) -ne 0) { Log "ERROR: git fetch failed."; exit 1 }
    if ((Invoke-Git pull --rebase --autostash origin main) -ne 0) {
        Log "ERROR: git pull --rebase failed."; exit 1
    }

    # 4. Stage ONLY this digest file (so stray files in input\ are left alone).
    if ((Invoke-Git add -- "input/$($newest.Name)") -ne 0) {
        Log "ERROR: git add failed."; exit 1
    }

    # Anything actually staged? (exit code 0 from --quiet means "no changes")
    & git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Log "No new digest to publish (already up to date)."
        exit 0
    }

    if ((Invoke-Git commit -m "Add digest $($newest.BaseName)") -ne 0) {
        Log "ERROR: git commit failed."; exit 1
    }

    # 5. Push, with a few retries for transient network hiccups.
    $pushed = $false
    for ($i = 1; $i -le 4; $i++) {
        if ((Invoke-Git push origin main) -eq 0) { $pushed = $true; break }
        $wait = [math]::Pow(2, $i)
        Log "Push attempt $i failed; retrying in ${wait}s..."
        Start-Sleep -Seconds $wait
        Invoke-Git pull --rebase --autostash origin main | Out-Null
    }

    if ($pushed) { Log "Pushed. GitHub Actions will now build the episode." }
    else { Log "ERROR: push failed after retries."; exit 1 }
}
catch {
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}
