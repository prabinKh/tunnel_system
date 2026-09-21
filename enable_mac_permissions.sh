#!/usr/bin/env bash
# ==============================================================================
# Helper Script: Enable SSH & Full Disk Access on macOS
# ==============================================================================

echo "============================================================"
echo "  macOS Permission & SSH Setup Helper"
echo "============================================================"

# 1. Enable Remote Login (SSH)
echo "[INFO] Enabling Remote Login (SSH)..."
sudo launchctl load -w /System/Library/LaunchDaemons/ssh.plist 2>/dev/null || true
sudo systemsetup -setremotelogin on 2>/dev/null || true

# 2. Check Full Disk Access
echo "[INFO] Opening macOS System Settings to Full Disk Access..."
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"

echo ""
echo "============================================================"
echo "  IN SYSTEM SETTINGS:"
echo "  1. Look for 'sshd-keygen-wrapper' or 'sshd' or 'Terminal'"
echo "  2. Toggle the switch to ON 🟢"
echo "  3. If not in the list, click '+' and add: /usr/sbin/sshd"
echo "============================================================"
echo "[OK] Setup complete! You can now run ./host_a.sh"
