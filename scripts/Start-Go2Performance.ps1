# Runs in the current terminal so Ctrl+C can stop the routine.
[CmdletBinding()]
param(
    [double]$ClearanceCm = 10,
    [double]$PitchDegrees = 1.5,
    [double]$PeriodSeconds = 4,
    [double]$DurationSeconds = 180,
    [switch]$DryRun
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
& wsl.exe -d Ubuntu-24.04 -u root --exec /bin/sh $go2LinuxLauncher @go2Arguments
if ($LASTEXITCODE -eq 130) {
    Write-Output 'Performance cancelled.'
} elseif ($LASTEXITCODE -ne 0) {
    throw "Performance exited with code $LASTEXITCODE. Check the SDK result above."
}
