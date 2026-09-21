#!/usr/bin/env python3
"""
One-time VPS setup script.
- Connects to VPS
- Creates project folder
- Uploads vps_bridge.py
- Installs requirements
- Generates master SSH key pair
- Reads back keys
- Patches host_a.py and host_b.py with VPS IP + embedded key paths
"""

import os
import sys
import time
import json
import paramiko
from scp import SCPClient

# ── VPS credentials ───────────────────────────────────────────
VPS_IP       = "144.91.72.44"
VPS_USER     = "prabin"
VPS_PASSWORD = "Prabin@1234#"
VPS_PORT     = 22

# ── VPS project folder ────────────────────────────────────────
VPS_PROJECT_DIR  = "/home/prabin/tunnel_system"
VPS_REGISTRY_DIR = "/home/prabin/tunnel_system/registry"
MASTER_KEY       = "/home/prabin/tunnel_system/registry/master_key"
MASTER_KEY_PUB   = "/home/prabin/tunnel_system/registry/master_key.pub"

# ── Local script paths ────────────────────────────────────────
SCRIPT_DIR = "/Users/prabinkhadka/Documents/tunnel connection"

R="\033[0m"; GRN="\033[92m"; RED="\033[91m"; CYN="\033[96m"; YEL="\033[93m"; BOLD="\033[1m"
def ok(m):   print(f"{GRN}[ OK ]{R} {m}")
def info(m): print(f"{CYN}[INFO]{R} {m}")
def fail(m): print(f"{RED}[FAIL]{R} {m}"); sys.exit(1)
def warn(m): print(f"{YEL}[WARN]{R} {m}")
def step(n, m): print(f"\n{BOLD}{CYN}── Step {n}: {m}{R}")


def run(client, cmd, check=True):
    """Run command on VPS, print output, return stdout."""
    _, stdout, stderr = client.exec_command(cmd, get_pty=True)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    if out: print(f"   {out}")
    if err and "WARNING" not in err and "warning" not in err:
        print(f"   {YEL}{err}{R}")
    return out


def main():
    print(f"\n{BOLD}{'='*60}")
    print(f"  VPS AUTO-SETUP  →  {VPS_USER}@{VPS_IP}")
    print(f"{'='*60}{R}\n")

    # ── Connect ───────────────────────────────────────────────
    step(1, "Connecting to VPS")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(VPS_IP, port=VPS_PORT, username=VPS_USER,
                    password=VPS_PASSWORD, timeout=20)
        ok(f"Connected to {VPS_USER}@{VPS_IP}")
    except Exception as e:
        fail(f"Cannot connect to VPS: {e}")

    # ── Create project directories ────────────────────────────
    step(2, "Creating project directories on VPS")
    run(ssh, f"mkdir -p {VPS_PROJECT_DIR} {VPS_REGISTRY_DIR}")
    run(ssh, f"chmod 755 {VPS_PROJECT_DIR}")
    run(ssh, f"chmod 777 {VPS_REGISTRY_DIR}")
    ok(f"Created: {VPS_PROJECT_DIR}")
    ok(f"Created: {VPS_REGISTRY_DIR}")

    # ── Upload vps_bridge.py ──────────────────────────────────
    step(3, "Uploading vps_bridge.py to VPS")
    local_bridge = os.path.join(SCRIPT_DIR, "vps_bridge.py")
    remote_bridge = f"{VPS_PROJECT_DIR}/vps_bridge.py"

    # First update the registry path inside vps_bridge.py for this VPS
    with open(local_bridge) as f:
        bridge_code = f.read()

    # Patch registry paths to match VPS
    bridge_code = bridge_code.replace(
        '"/tmp/tunnel_registry"', f'"{VPS_REGISTRY_DIR}"')
    bridge_code = bridge_code.replace(
        '"/tmp/tunnel_registry/master_key"', f'"{MASTER_KEY}"')
    bridge_code = bridge_code.replace(
        '"/tmp/tunnel_registry/master_key.pub"', f'"{MASTER_KEY_PUB}"')
    bridge_code = bridge_code.replace(
        '"/tmp/vps_relay_stage"', f'"{VPS_PROJECT_DIR}/relay_stage"')

    # Write patched version to temp file
    tmp_bridge = "/tmp/vps_bridge_patched.py"
    with open(tmp_bridge, "w") as f:
        f.write(bridge_code)

    with SCPClient(ssh.get_transport()) as scp:
        scp.put(tmp_bridge, remote_bridge)
    ok(f"Uploaded: {remote_bridge}")

    # ── Install Python + pip + requirements ───────────────────
    step(4, "Installing Python requirements on VPS")
    run(ssh, "which python3 || apt-get install -y python3 python3-pip 2>&1 | tail -5")
    run(ssh, "pip3 install --quiet paramiko scp 2>&1 | tail -5")
    ok("paramiko and scp installed on VPS")

    # ── Generate master SSH key pair ──────────────────────────
    step(5, "Generating master SSH key pair")
    check = run(ssh, f"test -f {MASTER_KEY} && echo EXISTS || echo NOTFOUND")

    if "EXISTS" in check:
        warn("Master key already exists — reusing it.")
    else:
        run(ssh, f'ssh-keygen -t ed25519 -N "" -f {MASTER_KEY} -C "vps-tunnel-master" -q')
        run(ssh, f"chmod 600 {MASTER_KEY}")
        run(ssh, f"chmod 644 {MASTER_KEY_PUB}")
        ok("Master key pair generated!")

    # ── Read back the keys ────────────────────────────────────
    step(6, "Reading master keys from VPS")
    _, stdout_priv, _ = ssh.exec_command(f"cat {MASTER_KEY}")
    master_privkey = stdout_priv.read().decode(errors="replace").strip()

    _, stdout_pub, _ = ssh.exec_command(f"cat {MASTER_KEY_PUB}")
    master_pubkey = stdout_pub.read().decode(errors="replace").strip()

    if not master_privkey or not master_pubkey:
        fail("Could not read master keys from VPS!")

    ok("Master private key read.")
    ok(f"Master public key: {master_pubkey[:60]}...")

    # ── Save keys locally for embedding ───────────────────────
    step(7, "Saving keys locally")
    local_key_dir = os.path.join(SCRIPT_DIR, ".tunnel_keys")
    os.makedirs(local_key_dir, exist_ok=True)

    local_priv = os.path.join(local_key_dir, "master_key")
    local_pub  = os.path.join(local_key_dir, "master_key.pub")

    with open(local_priv, "w") as f:
        f.write(master_privkey + "\n")
    os.chmod(local_priv, 0o600)

    with open(local_pub, "w") as f:
        f.write(master_pubkey + "\n")

    ok(f"Private key saved: {local_priv}")
    ok(f"Public key saved : {local_pub}")

    # ── Patch host_a.py ───────────────────────────────────────
    step(8, "Patching host_a.py with VPS IP + registry paths")
    host_a_path = os.path.join(SCRIPT_DIR, "host_a.py")
    with open(host_a_path) as f:
        ha = f.read()

    ha = ha.replace('"your_vps_ip"', f'"{VPS_IP}"')
    ha = ha.replace('"VPS_USER":      "root"', f'"VPS_USER":      "{VPS_USER}"')
    ha = ha.replace('"VPS_PASSWORD":  ""', f'"VPS_PASSWORD":  "{VPS_PASSWORD}"')
    ha = ha.replace(
        '"VPS_REGISTRY_DIR":   "/tmp/tunnel_registry"',
        f'"VPS_REGISTRY_DIR":   "{VPS_REGISTRY_DIR}"')
    ha = ha.replace(
        '"VPS_MASTER_PUBKEY":  "/tmp/tunnel_registry/master_key.pub"',
        f'"VPS_MASTER_PUBKEY":  "{MASTER_KEY_PUB}"')

    with open(host_a_path, "w") as f:
        f.write(ha)
    ok(f"host_a.py patched with VPS_IP={VPS_IP} and registry paths")

    # ── Patch host_b.py ───────────────────────────────────────
    step(9, "Patching host_b.py with VPS IP + master key path")
    host_b_path = os.path.join(SCRIPT_DIR, "host_b.py")
    with open(host_b_path) as f:
        hb = f.read()

    hb = hb.replace('"your_vps_ip"', f'"{VPS_IP}"')
    hb = hb.replace('"VPS_USER":     "root"', f'"VPS_USER":     "{VPS_USER}"')
    hb = hb.replace('"VPS_PASSWORD": ""', f'"VPS_PASSWORD": "{VPS_PASSWORD}"')
    hb = hb.replace(
        '"VPS_REGISTRY_DIR":    "/tmp/tunnel_registry"',
        f'"VPS_REGISTRY_DIR":    "{VPS_REGISTRY_DIR}"')
    hb = hb.replace(
        '"VPS_MASTER_KEY_FILE": "/tmp/tunnel_registry/master_key"',
        f'"VPS_MASTER_KEY_FILE": "{MASTER_KEY}"')

    # Also update local key cache to use our local saved path
    local_cache_escaped = local_priv.replace('"', '\\"')
    hb = hb.replace(
        '"LOCAL_KEY_CACHE": os.path.expanduser("~/.ssh/tunnel_master_key")',
        f'"LOCAL_KEY_CACHE": "{local_priv}"')

    with open(host_b_path, "w") as f:
        f.write(hb)
    ok(f"host_b.py patched with VPS_IP={VPS_IP} and master key path")

    # ── Verify VPS setup ──────────────────────────────────────
    step(10, "Verifying VPS setup")
    files = run(ssh, f"ls -la {VPS_PROJECT_DIR}/ {VPS_REGISTRY_DIR}/")
    ok("VPS directory listing shown above")

    # ── Final summary ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"{BOLD}{GRN}  SETUP COMPLETE!{R}")
    print(f"{'='*60}")
    print(f"""
  VPS Details:
    IP       : {VPS_IP}
    User     : {VPS_USER}
    Project  : {VPS_PROJECT_DIR}
    Registry : {VPS_REGISTRY_DIR}
    Master key: {MASTER_KEY}

  Local files updated:
    host_a.py  → VPS_IP, registry paths, password pre-filled
    host_b.py  → VPS_IP, master key path, password pre-filled
    .tunnel_keys/master_key     → private key cached locally
    .tunnel_keys/master_key.pub → public key cached locally

  {BOLD}NEXT STEPS:{R}
    1. On VPS      : python3 {VPS_PROJECT_DIR}/vps_bridge.py
    2. Each source : python3 host_a.py   (on machines to share)
    3. Controller  : python3 host_b.py   (on THIS machine)

  {YEL}No passwords needed after setup is complete!{R}
""")
    ssh.close()


if __name__ == "__main__":
    main()
