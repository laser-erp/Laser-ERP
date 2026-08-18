# Persistent reverse tunnel: VPS 127.0.0.1:22022 -> this PC 127.0.0.1:22
$ErrorActionPreference = "Continue"
$key = Join-Path $env:USERPROFILE ".ssh\id_ed25519_vps_tunnel"
$domain = if ($env:LASER_SSH_HOST) { $env:LASER_SSH_HOST } else { "aptown11.fvds.ru" }
$user = if ($env:LASER_SSH_USER) { $env:LASER_SSH_USER } else { "root" }
$port = if ($env:LASER_SSH_PORT) { $env:LASER_SSH_PORT } else { "22" }
$listen = if ($env:LASER_TUNNEL_PORT) { $env:LASER_TUNNEL_PORT } else { "22022" }
$rdpListen = if ($env:LASER_RDP_TUNNEL_PORT) { $env:LASER_RDP_TUNNEL_PORT } else { "3389" }

if (-not (Test-Path $key)) {
    Write-Error "Missing tunnel key: $key"
    exit 1
}

$ssh = "$env:WINDIR\System32\OpenSSH\ssh.exe"
$args = @(
    "-N",
    "-i", $key,
    "-p", $port,
    "-o", "IdentitiesOnly=yes",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "StrictHostKeyChecking=accept-new",
    "-R", "127.0.0.1:${listen}:127.0.0.1:22",
    "-R", "127.0.0.1:${rdpListen}:127.0.0.1:3389",
    "${user}@${domain}"
)

while ($true) {
    Write-Host "$(Get-Date -Format o) tunnel start $user@$domain -> 127.0.0.1:$listen"
    & $ssh @args
    Write-Host "$(Get-Date -Format o) tunnel exit $LASTEXITCODE, retry in 5s"
    Start-Sleep -Seconds 5
}
