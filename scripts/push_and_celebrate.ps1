param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GitPushArgs
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "Running git push..."
& git push @GitPushArgs
$pushExit = $LASTEXITCODE
if ($pushExit -ne 0) {
    Write-Error "git push failed with exit code $pushExit; skipping celebration."
    exit $pushExit
}

$summary = "Successful git push from $RepoRoot at $(Get-Date -Format s)."
Write-Host "Push succeeded. Generating celebration song..."

& python -m session_to_song.cli celebrate-push --project "session-to-song" --summary $summary --play --no-block
$celebrateExit = $LASTEXITCODE
if ($celebrateExit -ne 0) {
    Write-Error "Push succeeded, but celebration failed with exit code $celebrateExit."
    exit $celebrateExit
}

exit 0
