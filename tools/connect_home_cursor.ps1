# One file for the laptop: downloads the SSH key, writes ~/.ssh/config,
# starts the RDP tunnel via VPS, then opens the remote desktop.
param(
    [string]$VpsHost = "aptown11.fvds.ru",
    [string]$VpsUser = "root",
    [int]$VpsPort = 22,
    [string]$HomeUser = "Жека",
    [int]$RemoteRdpPort = 3389,
    [int]$LocalRdpPort = 13389
)

$ErrorActionPreference = "Stop"

function Ensure-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Не найдена команда: $name. Установите OpenSSH Client в Windows."
    }
}

function Ensure-Dir($path) {
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
}

function Update-SshConfig($configPath, $keyPath, $vpsHost, $vpsUser, $vpsPort, $homeUser) {
    $block = @"
Host laser-vps
  HostName $vpsHost
  User $vpsUser
  Port $vpsPort
  IdentityFile $keyPath
  IdentitiesOnly yes

Host home-pc
  HostName 127.0.0.1
  User $homeUser
  Port 22022
  ProxyJump laser-vps
  IdentityFile $keyPath
  IdentitiesOnly yes
"@

    $existing = ""
    if (Test-Path $configPath) {
        $existing = Get-Content $configPath -Raw -Encoding UTF8
    }

    if ($existing -match "(?ms)^Host laser-vps\s+.*?^Host home-pc\s+.*?(?=^Host |\z)") {
        $updated = [regex]::Replace(
            $existing,
            "(?ms)^Host laser-vps\s+.*?^Host home-pc\s+.*?(?=^Host |\z)",
            ($block.TrimEnd() + "`r`n`r`n")
        )
    } else {
        if ($existing -and -not $existing.EndsWith("`n")) {
            $existing += "`r`n"
        }
        $updated = $existing + "`r`n" + $block.TrimEnd() + "`r`n"
    }

    Set-Content -Path $configPath -Value $updated -Encoding UTF8
}

Ensure-Command "ssh"
Ensure-Command "scp"
Ensure-Command "mstsc"

$sshDir = Join-Path $env:USERPROFILE ".ssh"
Ensure-Dir $sshDir

$keyPath = Join-Path $sshDir "id_ed25519_home"
$configPath = Join-Path $sshDir "config"
$remoteKey = "${VpsUser}@${VpsHost}:/root/home-pc-ssh/id_ed25519_home"

if (-not (Test-Path $keyPath)) {
    Write-Host ""
    Write-Host "Сейчас Windows попросит пароль от VPS один раз, чтобы скачать ключ." -ForegroundColor Yellow
    & scp -P $VpsPort $remoteKey $keyPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $keyPath)) {
        throw "Не удалось скачать ключ с VPS."
    }
}

Update-SshConfig $configPath $keyPath $VpsHost $VpsUser $VpsPort $HomeUser

$sshArgs = @(
    "-i", $keyPath,
    "-o", "IdentitiesOnly=yes",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "StrictHostKeyChecking=accept-new",
    "-N",
    "-L", "${LocalRdpPort}:127.0.0.1:${RemoteRdpPort}",
    "${VpsUser}@${VpsHost}"
)

Write-Host ""
Write-Host "Поднимаю защищённый туннель до домашнего ПК..." -ForegroundColor Cyan
$sshProc = Start-Process -FilePath "ssh" -ArgumentList $sshArgs -PassThru
Start-Sleep -Seconds 3

if ($sshProc.HasExited) {
    throw "SSH-туннель не запустился. Проверьте интернет и пароль/доступ к VPS."
}

Write-Host "Открываю удалённый рабочий стол. Логин: $HomeUser" -ForegroundColor Green
$rdpFile = Join-Path $env:TEMP "home-pc-tunnel.rdp"
$rdpBody = @"
full address:s:127.0.0.1:$LocalRdpPort
prompt for credentials:i:1
authentication level:i:0
enablecredsspsupport:i:0
negotiate security layer:i:1
"@
Set-Content -Path $rdpFile -Value $rdpBody -Encoding ASCII
Start-Process -FilePath "mstsc" -ArgumentList $rdpFile

Write-Host ""
Write-Host "Не закрывайте это окно PowerShell, пока работаете удаленно." -ForegroundColor Yellow
Write-Host "В удаленном рабочем столе откройте Cursor, этот чат будет там." -ForegroundColor Yellow
Write-Host ""

Wait-Process -Id $sshProc.Id
