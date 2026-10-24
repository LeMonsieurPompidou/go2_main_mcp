# Keep a foreground bridge attached to wsl.exe; a systemd-only service does not
# keep WSL alive after the last Windows client disconnects.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$go2Repository = Split-Path $PSScriptRoot -Parent
$go2Runtime = Join-Path $go2Repository '.runtime'
New-Item -ItemType Directory -Path $go2Runtime -Force | Out-Null
$go2Launcher = Join-Path $PSScriptRoot 'run-wsl-bridge.sh'
$go2LinuxLauncher = (& wsl.exe -d Ubuntu-24.04 --exec wslpath -a $go2Launcher).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve the WSL bridge launcher path' }

$go2Process = Start-Process -FilePath wsl.exe -WindowStyle Hidden -PassThru `
    -ArgumentList "-d Ubuntu-24.04 -u root --exec /bin/sh `"$go2LinuxLauncher`"" `
    -RedirectStandardOutput (Join-Path $go2Runtime 'bridge.stdout.log') `
    -RedirectStandardError (Join-Path $go2Runtime 'bridge.stderr.log')
$go2Process.Id | Set-Content (Join-Path $go2Runtime 'bridge-wsl.pid')
Write-Output "Go2 WSL bridge started (Windows PID $($go2Process.Id)). Logs: $go2Runtime"
