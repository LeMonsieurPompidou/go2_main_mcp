#Requires -RunAsAdministrator
<#
Configure the directly attached Go2 adapter for this Windows session.
Run from an Administrator PowerShell:
  .\scripts\Set-Go2Ethernet.ps1
Restore DHCP for this session:
  Remove-NetIPAddress -InterfaceAlias 'Ethernet 2' -IPAddress 192.168.123.100 -PolicyStore ActiveStore -Confirm:$false
  Set-NetIPInterface -InterfaceAlias 'Ethernet 2' -AddressFamily IPv4 -Dhcp Enabled -PolicyStore ActiveStore
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$go2Runtime = Join-Path (Split-Path $PSScriptRoot -Parent) '.runtime'
New-Item -ItemType Directory -Path $go2Runtime -Force | Out-Null
Start-Transcript -Path (Join-Path $go2Runtime 'network-repair.log') -Force | Out-Null
try {
$go2Adapter = Get-NetAdapter -Name 'Ethernet 2'
if ($go2Adapter.InterfaceDescription -notlike 'ASIX AX88179*' -or $go2Adapter.Status -ne 'Up') {
    throw 'Expected the connected ASIX USB Ethernet adapter named Ethernet 2. No settings changed.'
}

$go2Address = '192.168.123.100'
$go2Existing = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
    Where-Object IPAddress -eq $go2Address
if ($go2Existing) {
    if ($go2Existing.InterfaceIndex -ne $go2Adapter.ifIndex -or $go2Existing.PrefixLength -ne 24) {
        throw 'The requested IP is already configured differently. No settings changed.'
    }
    Write-Output 'Go2 Ethernet address is already configured.'
    return
}

# Change only the dedicated robot adapter; leave Wi-Fi and gateways alone.
Set-NetIPInterface -InterfaceIndex $go2Adapter.ifIndex -AddressFamily IPv4 -Dhcp Disabled -PolicyStore ActiveStore
New-NetIPAddress -InterfaceIndex $go2Adapter.ifIndex -IPAddress $go2Address -PrefixLength 24 -PolicyStore ActiveStore
Get-NetIPAddress -InterfaceIndex $go2Adapter.ifIndex -AddressFamily IPv4 |
    Format-Table IPAddress, PrefixLength, AddressState
Write-Output 'Ethernet 2 configured as 192.168.123.100/24 for this session. Robot connectivity still needs verification.'
} finally {
    Stop-Transcript | Out-Null
}
