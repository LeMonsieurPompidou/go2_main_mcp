#Requires -RunAsAdministrator
# Permit DDS UDP only from the wired Go2; keep existing firewall policies.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$go2Runtime = Join-Path (Split-Path $PSScriptRoot -Parent) '.runtime'
New-Item -ItemType Directory -Path $go2Runtime -Force | Out-Null
Start-Transcript -Path (Join-Path $go2Runtime 'dds-firewall.log') -Force | Out-Null
try {
    $go2RuleName = 'Go2-Wired-DDS-In'
    if (-not (Get-NetFirewallRule -Name $go2RuleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name $go2RuleName -DisplayName 'Go2 wired DDS from robot' `
            -Direction Inbound -Action Allow -Protocol UDP -RemoteAddress 192.168.123.161 `
            -InterfaceAlias 'Ethernet 2' -Profile Any | Out-Null
    }
    $go2WslRuleName = 'Go2-WSL-DDS-In'
    if (-not (Get-NetFirewallHyperVRule -Name $go2WslRuleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallHyperVRule -Name $go2WslRuleName -DisplayName 'Go2 DDS to WSL from robot' `
            -Direction Inbound -Action Allow -Protocol UDP -RemoteAddresses 192.168.123.161 `
            -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' | Out-Null
    }
    Write-Output 'Go2 DDS rules configured for UDP from 192.168.123.161 only.'
    Write-Output 'To undo: Remove-NetFirewallRule -Name Go2-Wired-DDS-In'
    Write-Output 'To undo: Remove-NetFirewallHyperVRule -Name Go2-WSL-DDS-In'
} finally {
    Stop-Transcript | Out-Null
}
