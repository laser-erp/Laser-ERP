#Requires -RunAsAdministrator
# RDP only via SSH tunnel (3389 not exposed to LAN/internet).
$ErrorActionPreference = "Stop"

Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" -Name "fDenyTSConnections" -Value 0
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp" -Name "UserAuthentication" -Value 0
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp" -Name "SecurityLayer" -Value 0

Enable-NetFirewallRule -DisplayGroup "Remote Desktop" -ErrorAction SilentlyContinue

# Block direct RDP from network; tunnel uses localhost on this PC.
New-NetFirewallRule -DisplayName "Block RDP inbound (use SSH tunnel)" `
    -Direction Inbound -Action Block -Protocol TCP -LocalPort 3389 `
    -Profile Any -ErrorAction SilentlyContinue | Out-Null
Set-NetFirewallRule -DisplayName "Block RDP inbound (use SSH tunnel)" -Enabled True -ErrorAction SilentlyContinue

Set-Service TermService -StartupType Automatic
Start-Service TermService

Write-Host "RDP enabled without NLA. Direct inbound 3389 blocked - connect via SSH tunnel only."
