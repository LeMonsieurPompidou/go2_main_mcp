# Adapter selection regression tests. These mock enumeration; no settings change.
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts/Go2Network.ps1')

function Get-NetAdapter {
    [CmdletBinding()]
    param([switch]$Physical)
    return $script:go2TestAdapters
}
function Assert-Go2SelectionFails {
    param([string]$AdapterName)
    $go2Rejected = $false
    try { Get-Go2EthernetAdapter -AdapterName $AdapterName | Out-Null } catch { $go2Rejected = $true }
    if (-not $go2Rejected) { throw 'Expected adapter selection to fail' }
}

$go2Usb = [pscustomobject]@{ Name = 'Ethernet 3'; InterfaceDescription = 'ASIX AX88179 USB 3.0 to Gigabit Ethernet Adapter #2'; Status = 'Up'; ifIndex = 58 }
$go2OtherUsb = [pscustomobject]@{ Name = 'Ethernet 7'; InterfaceDescription = 'ASIX AX88179 USB 3.0 to Gigabit Ethernet Adapter #3'; Status = 'Up'; ifIndex = 70 }
$go2Wifi = [pscustomobject]@{ Name = 'Wi-Fi'; InterfaceDescription = 'Intel Wi-Fi'; Status = 'Up'; ifIndex = 13 }
$script:go2TestAdapters = @($go2Wifi, $go2Usb)
if ((Get-Go2EthernetAdapter).Name -ne 'Ethernet 3') { throw 'Renamed ASIX adapter was not selected' }
Assert-Go2SelectionFails -AdapterName 'Ethernet 2'
Assert-Go2SelectionFails -AdapterName 'Wi-Fi'
$script:go2TestAdapters = @($go2Usb, $go2OtherUsb, $go2Wifi)
Assert-Go2SelectionFails
if ((Get-Go2EthernetAdapter -AdapterName 'Ethernet 7').ifIndex -ne 70) { throw 'Explicit selection failed' }
$script:go2TestAdapters = @($go2Wifi)
Assert-Go2SelectionFails
$script:go2TestAdapters = @([pscustomobject]@{ Name = 'Ethernet 3'; InterfaceDescription = $go2Usb.InterfaceDescription; Status = 'Disconnected'; ifIndex = 58 })
Assert-Go2SelectionFails

# Ensure an existing DDS rule moves to the replacement adapter, while keeping
# the robot-specific source address. These functions intercept all mutations.
function Get-NetFirewallRule {
    [CmdletBinding()]
    param([string]$Name)
    if ($script:go2RuleExists) { return [pscustomobject]@{ Name = $Name } }
}
function Get-NetFirewallHyperVRule {
    [CmdletBinding()]
    param([string]$Name)
    return [pscustomobject]@{ Name = $Name }
}
function Set-NetFirewallRule {
    param($Name, $InterfaceAlias, $Direction, $Action, $Protocol, $RemoteAddress, $Profile)
    $script:go2UpdatedRule = $PSBoundParameters
}
function New-NetFirewallRule {
    param($Name, $DisplayName, $InterfaceAlias, $Direction, $Action, $Protocol, $RemoteAddress, $Profile)
    $script:go2NewRule = $PSBoundParameters
}
$script:go2RuleExists = $true
$script:go2UpdatedRule = $null
$script:go2NewRule = $null
Set-Go2DdsRules -AdapterName 'Ethernet 3' | Out-Null
if ($script:go2NewRule -or $script:go2UpdatedRule.InterfaceAlias -ne 'Ethernet 3' -or
    $script:go2UpdatedRule.RemoteAddress -ne '192.168.123.161' -or $script:go2UpdatedRule.Protocol -ne 'UDP') {
    throw 'Existing robot rule was not updated with the selected adapter and source scope'
}
$script:go2RuleExists = $false
$script:go2UpdatedRule = $null
Set-Go2DdsRules -AdapterName 'Ethernet 7' | Out-Null
if ($script:go2UpdatedRule -or $script:go2NewRule.InterfaceAlias -ne 'Ethernet 7' -or
    $script:go2NewRule.RemoteAddress -ne '192.168.123.161' -or $script:go2NewRule.Protocol -ne 'UDP') {
    throw 'Missing robot rule was not created with the selected adapter and source scope'
}
Write-Output 'PASS: 9 adapter/firewall checks; no network settings changed.'
