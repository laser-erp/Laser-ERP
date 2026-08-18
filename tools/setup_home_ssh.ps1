#Requires -RunAsAdministrator
# OpenSSH Server only on 127.0.0.1. Reverse tunnel to VPS exposes it, not the internet.
$ErrorActionPreference = "Stop"

$Capability = "OpenSSH.Server~~~~0.0.1.0"
$cap = Get-WindowsCapability -Online -Name $Capability -ErrorAction SilentlyContinue
if (-not $cap -or $cap.State -ne "Installed") {
    Write-Host "Installing OpenSSH Server..."
    Add-WindowsCapability -Online -Name $Capability | Out-Null
}

Get-Service ssh-agent -ErrorAction SilentlyContinue | ForEach-Object {
    Set-Service -Name ssh-agent -StartupType Automatic
    Start-Service ssh-agent
}

$sshd = Get-Service sshd -ErrorAction SilentlyContinue
if (-not $sshd) {
    throw "sshd service not found after OpenSSH install"
}
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

$configPath = "C:\ProgramData\ssh\sshd_config"
if (-not (Test-Path $configPath)) {
    throw "sshd_config not found: $configPath"
}
Copy-Item $configPath "$configPath.bak" -Force
$cfg = Get-Content $configPath -Raw

function Set-SshdLine([string]$text, [string]$key, [string]$value) {
    $re = "(?m)^\s*#?\s*$([regex]::Escape($key))\b.*$"
    $line = "$key $value"
    if ([regex]::IsMatch($text, $re)) {
        return [regex]::Replace($text, $re, $line, 1)
    }
    return $text.TrimEnd() + "`r`n$line`r`n"
}

$cfg = Set-SshdLine $cfg "ListenAddress" "127.0.0.1"
$cfg = Set-SshdLine $cfg "PubkeyAuthentication" "yes"
$cfg = Set-SshdLine $cfg "PasswordAuthentication" "yes"
$cfg = Set-SshdLine $cfg "ChallengeResponseAuthentication" "no"
$cfg = Set-SshdLine $cfg "PermitEmptyPasswords" "no"
$cfg = Set-SshdLine $cfg "MaxAuthTries" "3"

# Administrators otherwise ignore ~/.ssh/authorized_keys
$cfg = [regex]::Replace(
    $cfg,
    "(?ms)^\s*Match Group administrators\s*\r?\n\s*AuthorizedKeysFile\s+__PROGRAMDATA__/ssh/administrators_authorized_keys\s*\r?\n",
    "# Match Group administrators`r`n#       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys`r`n"
)

Set-Content -Path $configPath -Value $cfg -Encoding ascii

$user = $env:USERNAME
$userProfile = "C:\Users\$user"
$authUser = Join-Path $userProfile ".ssh\authorized_keys"
$authAdmin = "C:\ProgramData\ssh\administrators_authorized_keys"
New-Item -ItemType Directory -Force -Path (Join-Path $userProfile ".ssh") | Out-Null

if (Test-Path $authUser) {
    Copy-Item $authUser $authAdmin -Force
    $acl = Get-Acl $authAdmin
    $acl.SetAccessRuleProtection($true, $false)
    $rules = @(
        (New-Object System.Security.AccessControl.FileSystemAccessRule("SYSTEM","FullControl","Allow")),
        (New-Object System.Security.AccessControl.FileSystemAccessRule("BUILTIN\Administrators","FullControl","Allow"))
    )
    foreach ($r in $rules) { $acl.AddAccessRule($r) }
    Set-Acl $authAdmin $acl
}

Restart-Service sshd
Write-Host "OpenSSH Server is listening on 127.0.0.1:22"
Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, State | Format-Table -AutoSize
