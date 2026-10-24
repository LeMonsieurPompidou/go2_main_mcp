#Requires -RunAsAdministrator
<#
Configure the directly attached Go2 adapter for this Windows session.
Run from an Administrator PowerShell:
  .\scripts\Set-Go2Ethernet.ps1
Restore DHCP for this session:
  Use the interface index printed by this script in Remove-NetIPAddress and
  Set-NetIPInterface -Dhcp Enabled -PolicyStore ActiveStore.
#>
[CmdletBinding()]
param([string]$AdapterName)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Go2Network.ps1')
$go2Runtime = Join-Path (Split-Path $PSScriptRoot -Parent) '.runtime'
New-Item -ItemType Directory -Path $go2Runtime -Force | Out-Null
Start-Transcript -Path (Join-Path $go2Runtime 'network-repair.log') -Force | Out-Null
try {
$go2Adapter = Get-Go2EthernetAdapter -AdapterName $AdapterName
Write-Output "Selected $($go2Adapter.Name), interface $($go2Adapter.ifIndex), MAC $($go2Adapter.MacAddress)"

$go2Address = '192.168.123.100'
$go2Existing = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
    Where-Object IPAddress -eq $go2Address
if ($go2Existing) {
    if ($go2Existing.InterfaceIndex -ne $go2Adapter.ifIndex -or $go2Existing.PrefixLength -ne 24) {
        throw 'The requested IP is already configured differently. No settings changed.'
    }
    Write-Output 'Go2 Ethernet address is already configured.'
} else {
    # Change only the selected USB robot adapter; leave Wi-Fi and gateways alone.
    Set-NetIPInterface -InterfaceIndex $go2Adapter.ifIndex -AddressFamily IPv4 -Dhcp Disabled -PolicyStore ActiveStore
    New-NetIPAddress -InterfaceIndex $go2Adapter.ifIndex -IPAddress $go2Address -PrefixLength 24 -PolicyStore ActiveStore
}
Set-Go2DdsRules -AdapterName $go2Adapter.Name
Get-NetIPAddress -InterfaceIndex $go2Adapter.ifIndex -AddressFamily IPv4 |
    Format-Table IPAddress, PrefixLength, AddressState
Write-Output "$($go2Adapter.Name) configured as 192.168.123.100/24 for this session. Robot connectivity still needs verification."
Write-Output "Restore DHCP: Remove-NetIPAddress -InterfaceIndex $($go2Adapter.ifIndex) -IPAddress $go2Address -PolicyStore ActiveStore -Confirm:`$false"
Write-Output "Then: Set-NetIPInterface -InterfaceIndex $($go2Adapter.ifIndex) -AddressFamily IPv4 -Dhcp Enabled -PolicyStore ActiveStore"
} finally {
    Stop-Transcript | Out-Null
}
