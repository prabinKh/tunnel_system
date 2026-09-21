<#
==============================================================================
 Host A - Native PowerShell Agent (Zero Python / Zero Pip required)
 Supports: Windows 10 / 11 / Server (with built-in OpenSSH)
==============================================================================
#>

$ErrorActionPreference = "SilentlyContinue"

$VPS_IP      = "144.91.72.44"
$VPS_PORT    = "22"
$VPS_USER    = "prabin"
$VPS_PASS    = "Prabin@1234#"
$MASTER_PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByK4+P+33oBAdWKWsYiUAAVcaxDY1NIpfR4Yyvvjh+B vps-tunnel-master"
$SHARE_DIR   = "$HOME\shared_files"
$MACHINE_NAME = $env:COMPUTERNAME.Replace(" ", "_")

# Compute deterministic port from hostname hash (22100 - 22599)
$bytes = [System.Text.Encoding]::UTF8.GetBytes($MACHINE_NAME)
$hash = [System.Security.Cryptography.MD5]::Create().ComputeHash($bytes)
$portOffset = [BitConverter]::ToUInt16($hash, 0) % 500
$TUNNEL_PORT = 22100 + $portOffset

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Host A - Source Machine Agent (Native Windows PowerShell)" -ForegroundColor Cyan
Write-Host "  Machine: $MACHINE_NAME | Tunnel Port: $TUNNEL_PORT" -ForegroundColor Cyan
Write-Host "============================================================"

# 1. Create Share Folder
if (!(Test-Path $SHARE_DIR)) {
    New-Item -ItemType Directory -Path $SHARE_DIR -Force | Out-Null
}
Write-Host "[OK] Share directory ready: $SHARE_DIR" -ForegroundColor Green

# 2. Check / Start OpenSSH Server
Write-Host "[INFO] Checking OpenSSH server on Windows..." -ForegroundColor Yellow
Start-Service sshd -ErrorAction SilentlyContinue
Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue

# 3. Add Master Public Key to authorized_keys
$sshDir = "$HOME\.ssh"
if (!(Test-Path $sshDir)) {
    New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
}
$authKeys = "$sshDir\authorized_keys"
if (Test-Path $authKeys) {
    $existing = Get-Content $authKeys -Raw
    if ($existing -notmatch "vps-tunnel-master") {
        Add-Content -Path $authKeys -Value "`n$MASTER_PUBKEY`n"
    }
} else {
    Set-Content -Path $authKeys -Value "$MASTER_PUBKEY`n"
}

# Also add to administrators_authorized_keys if exists
$adminAuthKeys = "$env:ProgramData\ssh\administrators_authorized_keys"
if (Test-Path (Split-Path $adminAuthKeys)) {
    if (Test-Path $adminAuthKeys) {
        $existingAdmin = Get-Content $adminAuthKeys -Raw
        if ($existingAdmin -notmatch "vps-tunnel-master") {
            Add-Content -Path $adminAuthKeys -Value "`n$MASTER_PUBKEY`n"
        }
    } else {
        Set-Content -Path $adminAuthKeys -Value "$MASTER_PUBKEY`n"
    }
}
Write-Host "[OK] Master public key installed in authorized_keys." -ForegroundColor Green

# 4. Open Reverse SSH Tunnel
Write-Host "[INFO] Opening Reverse SSH Tunnel to VPS on port $TUNNEL_PORT..." -ForegroundColor Green
Write-Host "[INFO] Use password: $VPS_PASS if prompted." -ForegroundColor Yellow

ssh -N -p $VPS_PORT -R "$($TUNNEL_PORT):localhost:22" -o StrictHostKeyChecking=no -o ServerAliveInterval=20 "$VPS_USER@$VPS_IP"
