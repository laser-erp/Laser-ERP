# Apply Yandex app password to the Laser ERP VPS without putting it in Cursor chat.
# Run on the home Windows PC (PowerShell). Password is typed locally and sent over SSH stdin.
#
# Example:
#   .\tools\apply_yandex_smtp_from_pc.ps1 -VpsHost YOUR_VPS_HOST
#
param(
    [Parameter(Mandatory = $true)]
    [string]$VpsHost,
    [string]$User = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_ed25519_home"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $IdentityFile)) {
    throw "SSH key not found: $IdentityFile"
}

$secure = Read-Host "Yandex app password (input hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
$plain = -join ($plain.ToCharArray() | Where-Object { $_ -notmatch '\s' })
if ([string]::IsNullOrWhiteSpace($plain)) {
    throw "Empty password"
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "ssh"
$psi.Arguments = "-i `"$IdentityFile`" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new $User@$VpsHost python3 /usr/local/sbin/apply-yandex-smtp.py"
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$p = [System.Diagnostics.Process]::Start($psi)
$p.StandardInput.WriteLine($plain)
$p.StandardInput.Close()
$plain = $null
$stdout = $p.StandardOutput.ReadToEnd()
$stderr = $p.StandardError.ReadToEnd()
$p.WaitForExit()
Write-Output $stdout
if ($stderr) { Write-Host $stderr -ForegroundColor Yellow }
if ($p.ExitCode -ne 0) { exit $p.ExitCode }
Write-Host "Done. Check https://laser-erp.armada.sx/admin/password_reset/ (Email field if SMTP_OK)."
