#Requires -RunAsAdministrator
# Permit DDS UDP only from the wired Go2; keep existing firewall policies.
[CmdletBinding()]
param([string]$AdapterName)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Go2Network.ps1')
$go2Runtime = Join-Path (Split-Path $PSScriptRoot -Parent) '.runtime'
New-Item -ItemType Directory -Path $go2Runtime -Force | Out-Null
Start-Transcript -Path (Join-Path $go2Runtime 'dds-firewall.log') -Force | Out-Null
try {
    $go2Adapter = Get-Go2EthernetAdapter -AdapterName $AdapterName
    Set-Go2DdsRules -AdapterName $go2Adapter.Name
    Write-Output 'To undo: Remove-NetFirewallRule -Name Go2-Wired-DDS-In'
    Write-Output 'To undo: Remove-NetFirewallHyperVRule -Name Go2-WSL-DDS-In'
} finally {
    Stop-Transcript | Out-Null
}
