#!/usr/bin/env bash
# ==============================================================================
# Host A - Native Bash Agent (Zero Python / Zero Pip required / Zero Passwords)
# Supports: macOS & Linux
# ==============================================================================

set -e

VPS_IP="144.91.72.44"
VPS_PORT="22"
VPS_USER="prabin"
SHARE_DIR="$HOME/shared_files"
MACHINE_NAME=$(hostname -s | tr ' ' '_')
OS_TYPE=$(uname -s)

# Master Keys
MASTER_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByK4+P+33oBAdWKWsYiUAAVcaxDY1NIpfR4Yyvvjh+B vps-tunnel-master"

# Compute deterministic port from hostname hash (22100 - 22599)
HASH_NUM=$(echo -n "$MACHINE_NAME" | cksum | awk '{print $1}')
TUNNEL_PORT=$((22100 + (HASH_NUM % 500)))

echo "============================================================"
echo "  Host A - Source Machine Agent (Native Bash - 100% Passwordless)"
echo "  Machine: $MACHINE_NAME | OS: $OS_TYPE"
echo "  Tunnel Port: $TUNNEL_PORT"
echo "============================================================"

# 1. Setup local master private key for passwordless VPS auth
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
KEY_FILE="$HOME/.ssh/vps_tunnel_master_key"

cat << 'EOF' > "$KEY_FILE"
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACAciuPj/t96AQHVilrGIlAAFXGsQ2NTSKX0eGMr744fgQAAAJgFEj2nBRI9
pwAAAAtzc2gtZWQyNTUxOQAAACAciuPj/t96AQHVilrGIlAAFXGsQ2NTSKX0eGMr744fgQ
AAAEDdxYkNehpMCzn3animpTCtL3svAS4VIBhfVbkjLRlF6hyK4+P+33oBAdWKWsYiUAAV
caxDY1NIpfR4Yyvvjh+BAAAAEXZwcy10dW5uZWwtbWFzdGVyAQIDBA==
-----END OPENSSH PRIVATE KEY-----
EOF
chmod 600 "$KEY_FILE"

# 2. Prepare share folder
mkdir -p "$SHARE_DIR"
chmod 755 "$SHARE_DIR" 2>/dev/null || true
echo "[OK] Share directory ready: $SHARE_DIR"

# 3. Ensure local SSH server is running
echo "[INFO] Checking local SSH server on port 22..."
if ! nc -z 127.0.0.1 22 2>/dev/null && ! (echo >/dev/tcp/127.0.0.1/22) 2>/dev/null; then
    echo "[WARN] Local SSH not running. Attempting to start..."
    if [ "$OS_TYPE" = "Darwin" ]; then
        sudo launchctl load -w /System/Library/LaunchDaemons/ssh.plist 2>/dev/null || true
    else
        sudo systemctl enable --now ssh 2>/dev/null || sudo systemctl enable --now sshd 2>/dev/null || sudo service ssh start 2>/dev/null || true
    fi
fi

# 4. Add Master Public Key to authorized_keys (allows Host B to connect passwordlessly)
AUTH_KEYS="$HOME/.ssh/authorized_keys"
touch "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

if ! grep -q "$MASTER_PUBKEY" "$AUTH_KEYS" 2>/dev/null; then
    echo "$MASTER_PUBKEY" >> "$AUTH_KEYS"
    echo "[OK] VPS Master key added to authorized_keys (Passwordless access ready)."
fi

# 5. Cleanup on exit
cleanup() {
    echo -e "\n[INFO] Disconnecting and unregistering..."
    ssh -i "$KEY_FILE" -p "$VPS_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$VPS_USER@$VPS_IP" \
        "rm -f /home/prabin/tunnel_system/registry/$MACHINE_NAME.json" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 6. Register on VPS
REG_JSON="{\"name\":\"$MACHINE_NAME\",\"tunnel_port\":$TUNNEL_PORT,\"share_root\":\"$SHARE_DIR\",\"username\":\"$USER\",\"os\":\"$OS_TYPE\",\"key_auth\":true,\"registered\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"heartbeat\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"

echo "[INFO] Registering machine on VPS (passwordless)..."
ssh -i "$KEY_FILE" -p "$VPS_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$VPS_USER@$VPS_IP" \
    "mkdir -p /home/prabin/tunnel_system/registry && echo '$REG_JSON' > /home/prabin/tunnel_system/registry/$MACHINE_NAME.json"
echo "[OK] Registered as $MACHINE_NAME on VPS registry!"

# 7. Open Reverse SSH Tunnel
echo "[OK] Opening Reverse SSH Tunnel to VPS on port $TUNNEL_PORT (Passwordless)..."
ssh -N \
    -i "$KEY_FILE" \
    -p "$VPS_PORT" \
    -R "$TUNNEL_PORT:localhost:22" \
    -o StrictHostKeyChecking=no \
    -o ServerAliveInterval=20 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    "$VPS_USER@$VPS_IP"
