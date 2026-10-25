# Runs in the current terminal so Ctrl+C can stop the routine.
[CmdletBinding()]
param(
    [double]$ClearanceCm = 10,
    [double]$PitchDegrees = 1.5,
    [double]$PeriodSeconds = 4,
    [double]$DurationSeconds = 600,
    [switch]$DryRun,
    [switch]$Diagnostic,
    [switch]$SeparatedTest
)

$ErrorActionPreference = 'Stop'
$go2Repository = Split-Path $PSScriptRoot -Parent
$go2Culture = [System.Globalization.CultureInfo]::InvariantCulture
$go2Arguments = @(
    '--clearance-cm', $ClearanceCm.ToString($go2Culture),
    '--pitch-deg', $PitchDegrees.ToString($go2Culture),
    '--period', $PeriodSeconds.ToString($go2Culture),
    '--duration', $DurationSeconds.ToString($go2Culture)
)
if ($Diagnostic) { $go2Arguments += '--diagnostic' }
if ($SeparatedTest) { $go2Arguments += '--separated-test' }

if ($DryRun) {
    Push-Location $go2Repository
    try {
        & python -m go2_performance @go2Arguments --dry-run
        if ($LASTEXITCODE -ne 0) { throw 'Performance plan validation failed' }
    } finally {
        Pop-Location
    }
    return
}

$go2Launcher = Join-Path $PSScriptRoot 'run-wsl-performance.sh'
$go2LinuxLauncher = (& wsl.exe -d Ubuntu-24.04 --exec wslpath -a $go2Launcher).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve the WSL launcher path' }
$go2LogDirectory = Join-Path $go2Repository '.runtime'
New-Item -ItemType Directory -Path $go2LogDirectory -Force | Out-Null
$go2LogPath = Join-Path $go2LogDirectory ("performance-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$go2TracePath = [System.IO.Path]::ChangeExtension($go2LogPath, '.csv')
$go2LinuxTracePath = '/app/performance-logs/' + [System.IO.Path]::GetFileName($go2TracePath)
$go2Arguments += @('--trace-csv', $go2LinuxTracePath)
Start-Transcript -Path $go2LogPath | Out-Null
try {
    Write-Output "Test log: $go2LogPath"
    Write-Output "Pitch trace: $go2TracePath"
    Write-Output "SDK replies: $([System.IO.Path]::ChangeExtension($go2LogPath, '.sdk.jsonl'))"
    & wsl.exe -d Ubuntu-24.04 -u root --exec /bin/sh $go2LinuxLauncher @go2Arguments
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 130) {
        throw "Performance exited with code $LASTEXITCODE. Check the SDK result above."
    }
} finally {
    Stop-Transcript | Out-Null
}
