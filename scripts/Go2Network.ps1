# Shared helpers; dot-sourcing this file does not change any system settings.
function Get-Go2EthernetAdapter {
    [CmdletBinding()]
    param([string]$AdapterName)

    $go2Adapters = @(Get-NetAdapter -Physical -ErrorAction Stop)
    $go2Candidates = @($go2Adapters | Where-Object {
        $_.Status -eq 'Up' -and
        $_.InterfaceDescription -like 'ASIX AX88179*' -and
        (-not $AdapterName -or $_.Name -eq $AdapterName)
    })
    if ($go2Candidates.Count -ne 1) {
        $go2Names = ($go2Candidates | ForEach-Object { $_.Name }) -join ', '
        if (-not $go2Names) { $go2Names = '(none)' }
        throw "Expected one connected ASIX USB Ethernet adapter. Candidates: $go2Names. Use -AdapterName to select one when multiple are connected. No settings changed."
    }
    return $go2Candidates[0]
}

function Set-Go2DdsRules {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$AdapterName)

    $go2RuleName = 'Go2-Wired-DDS-In'
    if (Get-NetFirewallRule -Name $go2RuleName -ErrorAction SilentlyContinue) {
        # A USB adapter replacement can change its alias while the rule remains.
        Set-NetFirewallRule -Name $go2RuleName -InterfaceAlias $AdapterName `
            -Direction Inbound -Action Allow -Protocol UDP `
            -RemoteAddress 192.168.123.161 -Profile Any | Out-Null
    } else {
        New-NetFirewallRule -Name $go2RuleName -DisplayName 'Go2 wired DDS from robot' `
            -Direction Inbound -Action Allow -Protocol UDP -RemoteAddress 192.168.123.161 `
            -InterfaceAlias $AdapterName -Profile Any | Out-Null
    }
    if (-not (Get-NetFirewallHyperVRule -Name 'Go2-WSL-DDS-In' -ErrorAction SilentlyContinue)) {
        New-NetFirewallHyperVRule -Name 'Go2-WSL-DDS-In' -DisplayName 'Go2 DDS to WSL from robot' `
            -Direction Inbound -Action Allow -Protocol UDP -RemoteAddresses 192.168.123.161 `
            -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' | Out-Null
    }
    Write-Output "Go2 DDS rules configured for UDP from 192.168.123.161 on $AdapterName and WSL."
}
