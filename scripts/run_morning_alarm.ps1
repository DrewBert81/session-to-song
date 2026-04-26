param(
  [string]$RepoRoot = "C:\Users\dbagl\.openclaw\workspace\session-to-song",
  [string]$TargetDir = "G:\My Drive\Sessiontosong Alarms",
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

$logDir = Join-Path $RepoRoot "content\output\morning-alarm\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdout = Join-Path $logDir "$stamp.stdout.log"
$stderr = Join-Path $logDir "$stamp.stderr.log"

try {
  $ffmpeg = Get-Command ffmpeg -ErrorAction Stop
} catch {
  "ffmpeg is required and was not found on PATH." | Tee-Object -FilePath $stderr
  exit 1
}

$args = @(
  "-m", "session_to_song.cli", "morning-alarm",
  "--target-dir", $TargetDir
)

$process = Start-Process -FilePath $Python -ArgumentList $args -WorkingDirectory $RepoRoot -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
if ($process.ExitCode -ne 0) {
  Write-Error "session-to-song morning alarm failed with exit code $($process.ExitCode). See $stderr"
  exit $process.ExitCode
}

Get-Content $stdout
exit 0
