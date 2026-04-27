param(
  [string]$RepoRoot = "C:\Users\dbagl\.openclaw\workspace\session-to-song",
  [string]$TargetDir = "G:\My Drive\Sessiontosong Alarms",
  [string]$Python = "python",
  [switch]$SmokeTestArgumentQuoting
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

$logDir = Join-Path $RepoRoot "content\output\morning-alarm\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdout = Join-Path $logDir "$stamp.stdout.log"
$stderr = Join-Path $logDir "$stamp.stderr.log"

if (-not $SmokeTestArgumentQuoting) {
  try {
    $ffmpeg = Get-Command ffmpeg -ErrorAction Stop
  } catch {
    "ffmpeg is required and was not found on PATH." | Tee-Object -FilePath $stderr
    exit 1
  }
}

if ($SmokeTestArgumentQuoting) {
  $cliArgs = @(
    "-c", "import sys; raise SystemExit(0 if len(sys.argv) == 4 and sys.argv[2] == sys.argv[3] else 2)",
    "--target-dir", $TargetDir, $TargetDir
  )
} else {
  $cliArgs = @(
    "-m", "session_to_song.cli", "morning-alarm",
    "--target-dir", $TargetDir
  )
}

if ($PSVersionTable.PSVersion.Major -ge 6) {
  $process = Start-Process -FilePath $Python -ArgumentList $cliArgs -WorkingDirectory $RepoRoot -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
} else {
  # Windows PowerShell 5.1 flattens ArgumentList and splits unquoted paths with spaces
  # (for example: G:\My Drive\Sessiontosong Alarms). Quote each argument explicitly.
  $argumentLine = ($cliArgs | ForEach-Object {
    if ($_ -match '[\s"]') {
      '"' + ($_ -replace '"', '\"') + '"'
    } else {
      $_
    }
  }) -join " "
  $process = Start-Process -FilePath $Python -ArgumentList $argumentLine -WorkingDirectory $RepoRoot -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
}
if ($process.ExitCode -ne 0) {
  Write-Error "session-to-song morning alarm failed with exit code $($process.ExitCode). See $stderr"
  exit $process.ExitCode
}

if ($SmokeTestArgumentQuoting) {
  Write-Host "Argument quoting smoke passed for target path: $TargetDir"
  exit 0
}

Get-Content $stdout
exit 0
