<#
    publish_review.ps1
    -----------------------------------------------------------------------
    The automation bridge: takes the digest Markdown your "AI in education
    reviews" task produces and pushes it into the repo's input/ folder, which
    triggers the GitHub Actions pipeline that builds the episode and updates
    the podcast feed. No manual steps.

    Run it on a schedule a few minutes AFTER your digest task (see README).

    EDIT the two paths below to match your machine, then you never touch it
    again.
#>

# === EDIT THESE TWO PATHS ================================================= #

# Your local clone of the repo (the folder that contains generate_podcast.py):
$RepoPath  = "C:\Users\Aviv\AI-EDU-Podacast"

# The folder where your "AI in education reviews" task saves the .md digest.
# If that task already writes straight into the repo's input\ folder, set this
# to "$RepoPath\input" and the copy step below becomes a harmless no-op.
$SourceDir = "C:\Users\Aviv\Documents\AI-Education-Reviews"

# ========================================================================= #

$ErrorActionPreference = "Stop"
$log = Join-Path $RepoPath "publish_review.log"
function Log($m) { "$(Get-Date -Format s)  $m" | Tee-Object -FilePath $log -Append }

try {
    Set-Location $RepoPath

    # 1. Find the newest .md the review task produced.
    $newest = Get-ChildItem -Path $SourceDir -Filter *.md -File |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $newest) { Log "No .md files found in $SourceDir - nothing to do."; exit 0 }
    Log "Newest digest: $($newest.FullName)"

    # 2. Copy it into input\ (skipped automatically if it's already there).
    $dest = Join-Path $RepoPath "input\$($newest.Name)"
    if ($newest.FullName -ne $dest) {
        Copy-Item $newest.FullName $dest -Force
        Log "Copied to $dest"
    }

    # 3. Sync with GitHub first. The Actions workflow commits the generated MP3
    #    and feed.xml back to main, so the local clone is usually behind and a
    #    plain push would be rejected. Rebase local state on top of origin/main.
    git fetch origin main 2>&1 | ForEach-Object { Log $_ }
    git pull --rebase --autostash origin main 2>&1 | ForEach-Object { Log $_ }

    # 4. Stage, commit, push only if there's actually a new/changed file.
    git add input 2>&1 | Out-Null
    $pending = git status --porcelain input
    if (-not $pending) { Log "No new digest to publish (input/ unchanged)."; exit 0 }

    git commit -m "Add digest $($newest.BaseName)" 2>&1 | ForEach-Object { Log $_ }

    # Push with a few retries in case of a transient network hiccup.
    $pushed = $false
    for ($i = 1; $i -le 4; $i++) {
        git push origin main 2>&1 | ForEach-Object { Log $_ }
        if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
        Log "Push attempt $i failed; retrying in $([math]::Pow(2,$i))s..."
        Start-Sleep -Seconds ([math]::Pow(2, $i))
        git pull --rebase --autostash origin main 2>&1 | ForEach-Object { Log $_ }
    }
    if ($pushed) { Log "Pushed. GitHub Actions will now build the episode." }
    else { Log "ERROR: push failed after retries."; exit 1 }
}
catch {
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}
