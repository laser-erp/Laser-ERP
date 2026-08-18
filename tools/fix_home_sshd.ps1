#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
Copy-Item "$env:USERPROFILE\.ssh\authorized_keys" "C:\ProgramData\ssh\administrators_authorized_keys" -Force
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /inheritance:r /grant "SYSTEM:(F)" /grant "BUILTIN\Administrators:(F)" | Out-Null
Restart-Service sshd
Get-NetFirewallRule | Where-Object { $_.DisplayName -match 'OpenSSH' } | Disable-NetFirewallRule
Write-Host "sshd restarted"
Get-NetTCPConnection -LocalPort 22 -State Listen | Select-Object LocalAddress, LocalPort | Format-Table -AutoSize
