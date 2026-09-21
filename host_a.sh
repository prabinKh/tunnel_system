#!/usr/bin/env bash
# ==============================================================================
# Host A - Native Bash Agent (Zero Python / Zero Pip required)
# Supports: macOS & Linux
# ==============================================================================

set -e

VPS_IP="144.91.72.44"
VPS_PORT="22"
VPS_USER="prabin"
VPS_PASS="Prabin@1234#"
MASTER_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByK4+P+33oBAdWKWsYiUAAVcaxDY1NIpfR4Yyvvjh+B vps-tunnel-master"
SHARE_DIR="$HOME/shared_files"
MACHINE_NAME=$(hostname -s | tr ' ' '_')
OS_TYPE=$(uname -s)

# Compute deterministic port from hostname hash (22100 - 22599)
HASH_NUM=$(echo -n "$MACHINE_NAME" | cksum | awk '{print $1}')
TUNNEL_PORT=$((22100 + (HASH_NUM % 500)))

echo "============================================================"
echo "  Host A - Source Machine Agent (Native Bash)"
echo "  Machine: $MACHINE_NAME | OS: $OS_TYPE"
echo "  Tunnel Port: $TUNNEL_PORT"
echo "============================================================"

# 1. Prepare share folder
mkdir -p "$SHARE_DIR"
chmod 755 "$SHARE_DIR" 2>/dev/null || true
echo "[OK] Share directory ready: $SHARE_DIR"

# 2. Ensure local SSH server is running
echo "[INFO] Checking local SSH server on port 22..."
if ! nc -z 127.0.0.1 22 2>/dev/null && ! (echo >/dev/tcp/127.0.0.1/22) 2>/dev/null; then
    echo "[WARN] Local SSH not running. Attempting to start..."
    if [ "$OS_TYPE" = "Darwin" ]; then
        sudo launchctl load -w /System/Library/LaunchDaemons/ssh.plist 2>/dev/null || true
    else
        sudo systemctl enable --now ssh 2>/dev/null || sudo systemctl enable --now sshd 2>/dev/null || sudo service ssh start 2>/dev/null || true
    fi
fi

# 3. Add Master Public Key to authorized_keys
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
AUTH_KEYS="$HOME/.ssh/authorized_keys"
touch "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

if ! grep -q "$MASTER_PUBKEY" "$AUTH_KEYS" 2>/dev/null; then
    echo "$MASTER_PUBKEY" >> "$AUTH_KEYS"
    echo "[OK] VPS Master key added to authorized_keys (Passwordless access ready)."
fi

# 4. Cleanup on exit
cleanup() {
    echo -e "\n[INFO] Disconnecting and unregistering..."
    if command -v sshpass >/dev/null 2>&1; then
        sshpass -p "$VPS_PASS" ssh -p "$VPS_PORT" -o StrictHostKeyChecking=no "$VPS_USER@$VPS_IP" \
            "rm -f /home/prabin/tunnel_system/registry/$MACHINE_NAME.json" 2>/dev/null || true
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 5. Register on VPS
REG_JSON="{\"name\":\"$MACHINE_NAME\",\"tunnel_port\":$TUNNEL_PORT,\"share_root\":\"$SHARE_DIR\",\"username\":\"$USER\",\"os\":\"$OS_TYPE\",\"key_auth\":true,\"registered\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"heartbeat\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"

echo "[INFO] Registering machine on VPS..."
if command -v sshpass >/dev/null 2>&1; then
    sshpass -p "$VPS_PASS" ssh -p "$VPS_PORT" -o StrictHostKeyChecking=no "$VPS_USER@$VPS_IP" \
        "mkdir -p /home/prabin/tunnel_system/registry && echo '$REG_JSON' > /home/prabin/tunnel_system/registry/$MACHINE_NAME.json"
    echo "[OK] Registered as $MACHINE_NAME on VPS registry!"
fi

# 6. Open Reverse SSH Tunnel
echo "[OK] Opening Reverse SSH Tunnel to VPS on port $TUNNEL_PORT..."
if command -v sshpass >/dev/null 2>&1; then
    sshpass -p "$VPS_PASS" ssh -N \
        -p "$VPS_PORT" \
        -R "$TUNNEL_PORT:localhost:22" \
        -o StrictHostKeyChecking=no \
        -o ServerAliveInterval=20 \
        -o ServerAliveCountMax=3 \
        "$VPS_USER@$VPS_IP"
else
    echo "[INFO] Enter VPS password ($VPS_PASS) if prompted:"
    ssh -N \
        -p "$VPS_PORT" \
        -R "$TUNNEL_PORT:localhost:22" \
        -o StrictHostKeyChecking=no \
        -o ServerAliveInterval=20 \
        -o ServerAliveCountMax=3 \
        "$VPS_USER@$VPS_IP"
fi
