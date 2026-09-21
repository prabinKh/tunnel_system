#!/usr/bin/env python3
"""
============================================================
  VPS BRIDGE  —  Persistent Auto-Monitor Server
  Run this ONCE on your VPS. Keep it running forever.

  What it does automatically:
    - Generates a master SSH key pair (once, on first run)
    - Scans tunnel ports every 5s to detect new Host A machines
    - Updates live dashboard when machines connect/disconnect
    - Host A machines add the VPS master public key to their
      authorized_keys so Host B never needs a password
    - Host B downloads the master private key to connect to any
      Host A machine automatically

  USAGE:
    python3 vps_bridge.py           # interactive dashboard
    python3 vps_bridge.py --watch   # auto-refresh display only
============================================================
  REQUIRES: pip install paramiko scp
============================================================
"""

import os
import sys
import json
import time
import socket
import argparse
import threading
import subprocess
import paramiko
from scp import SCPClient

# ─────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────
CONFIG = {
    # Registry directory (must match host_a.py / host_b.py)
    "VPS_REGISTRY_DIR":  "/tmp/tunnel_registry",
    "TEMP_STAGE_DIR":    "/tmp/vps_relay_stage",

    # Master key files (auto-generated on first run)
    "MASTER_KEY_FILE":   "/tmp/tunnel_registry/master_key",
    "MASTER_PUBKEY_FILE":"/tmp/tunnel_registry/master_key.pub",

    # How often to scan ports for new machines (seconds)
    "SCAN_INTERVAL_S":   5,

    # A machine is "stale" if no heartbeat for this many seconds
    "STALE_THRESHOLD_S": 90,
}
# ─────────────────────────────────────────────────────────────

BANNER = r"""
 __   _____  ___   ___ ___ ___ ___   ___ ___
 \ \ / / _ \/ __| | _ ) _ \_ _|   \ / __| __|
  \ V /|  _/\__ \ | _ \   /| || |) | (_ | _|
   \_/ |_|  |___/ |___/_|_\___|___/ \___|___|

  Auto-Monitor  |  Master Key Manager  |  Live Dashboard
"""

R="\033[0m"; BOLD="\033[1m"; BLU="\033[94m"; GRN="\033[92m"
YEL="\033[93m"; RED="\033[91m"; CYN="\033[96m"; DIM="\033[2m"; MAG="\033[95m"

def info(m):  print(f"{BLU}[INFO]{R}  {m}")
def ok(m):    print(f"{GRN}[ OK ]{R}  {m}")
def warn(m):  print(f"{YEL}[WARN]{R}  {m}")
def fail(m):  print(f"{RED}[FAIL]{R}  {m}")
def sep(ch="─", w=70): print(ch * w)
def title(m): print(f"\n{BOLD}{CYN}{m}{R}")


# ═══════════════════════════════════════════════════════════════
#  MASTER KEY MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def ensure_master_key():
    """
    Generate the master SSH key pair if it doesn't exist yet.
    This key pair is created ONCE. The public key is given to
    all Host A machines. The private key is used by Host B.
    """
    key_file = CONFIG["MASTER_KEY_FILE"]
    pub_file = CONFIG["MASTER_PUBKEY_FILE"]
    reg_dir  = CONFIG["VPS_REGISTRY_DIR"]

    os.makedirs(reg_dir, exist_ok=True)
    os.chmod(reg_dir, 0o755)

    if os.path.exists(key_file) and os.path.exists(pub_file):
        ok(f"Master key already exists: {key_file}")
        return

    info("Generating master SSH key pair (first-time setup)...")
    result = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key_file,
         "-C", "vps-tunnel-master"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        fail(f"ssh-keygen failed: {result.stderr}")
        sys.exit(1)

    os.chmod(key_file, 0o600)
    os.chmod(pub_file, 0o644)
    ok(f"Master key pair generated:")
    ok(f"  Private key: {key_file}  (used by Host B)")
    ok(f"  Public key : {pub_file}  (added to Host A machines)")


def get_master_pubkey():
    """Return the VPS master public key string."""
    pub_file = CONFIG["MASTER_PUBKEY_FILE"]
    if not os.path.exists(pub_file):
        ensure_master_key()
    with open(pub_file) as f:
        return f.read().strip()


def get_master_privkey_path():
    return CONFIG["MASTER_KEY_FILE"]


# ═══════════════════════════════════════════════════════════════
#  PORT SCANNER — detects active tunnel ports
# ═══════════════════════════════════════════════════════════════

def port_active(port, timeout=1.0):
    """Return True if something is listening on localhost:port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def scan_all_ports(machines):
    """Update port_up status for all registered machines."""
    for m in machines:
        p = m.get("tunnel_port", 0)
        m["port_up"] = port_active(p) if p else False
    return machines


# ═══════════════════════════════════════════════════════════════
#  REGISTRY
# ═══════════════════════════════════════════════════════════════

def load_registry():
    """Read all .json entries from registry dir."""
    reg_dir = CONFIG["VPS_REGISTRY_DIR"]
    if not os.path.isdir(reg_dir):
        return []
    machines = []
    for fname in sorted(os.listdir(reg_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(reg_dir, fname)
        try:
            with open(fpath) as f:
                m = json.load(f)
            try:
                hb_t  = time.mktime(time.strptime(m.get("heartbeat",""),
                                                   "%Y-%m-%dT%H:%M:%SZ"))
                age   = time.time() - hb_t
                m["stale"] = age > CONFIG["STALE_THRESHOLD_S"]
                m["age_s"] = int(age)
            except Exception:
                m["stale"] = False
                m["age_s"] = 0
            machines.append(m)
        except Exception:
            pass
    return machines


def cleanup_stale_entries():
    """Remove registry JSON files for stale machines."""
    reg_dir = CONFIG["VPS_REGISTRY_DIR"]
    removed = 0
    for m in load_registry():
        if m.get("stale"):
            fpath = os.path.join(reg_dir, f"{m['name']}.json")
            try:
                os.remove(fpath)
                ok(f"Removed stale entry: {m['name']}")
                removed += 1
            except Exception:
                pass
    if removed == 0:
        info("No stale entries found.")
    return removed


# ═══════════════════════════════════════════════════════════════
#  LIVE DASHBOARD
# ═══════════════════════════════════════════════════════════════

def display_dashboard(machines, show_title=True):
    if show_title:
        title(f"  CONNECTED MACHINES   [{time.strftime('%H:%M:%S')}]")
    sep("═")

    if not machines:
        print(f"  {YEL}No machines registered yet.{R}")
        print(f"  {DIM}Run host_a.py on source machines to connect them.{R}")
        sep("═")
        return

    print(f"  {BOLD}{'#':<4} {'STATUS':<12} {'PORT':<8} {'MACHINE NAME':<22}"
          f" {'AGE':>6}  {'KEY AUTH':<9} SHARE ROOT{R}")
    sep()
    for i, m in enumerate(machines, 1):
        stale   = m.get("stale", False)
        port_up = m.get("port_up", False)
        age_s   = m.get("age_s", 0)
        key_ok  = m.get("key_auth", False)

        if not stale and port_up:
            status = f"{GRN}● CONNECTED {R}"
        elif not stale:
            status = f"{YEL}◐ REGISTERED{R}"
        else:
            status = f"{RED}○ OFFLINE   {R}"

        age_str  = f"{age_s}s" if age_s < 3600 else f"{age_s//60}m"
        key_str  = f"{GRN}✓ KEYAUTH{R}" if key_ok else f"{YEL}↑ PENDING{R}"

        name  = m.get("name", "?")
        port  = m.get("tunnel_port", "?")
        share = m.get("share_root", "?")

        print(f"  {str(i):<4} {status} {CYN}{port:<8}{R} {BOLD}{name:<22}{R}"
              f" {age_str:>6}  {key_str}  {DIM}{share}{R}")
    sep("═")
    total   = len(machines)
    online  = sum(1 for m in machines if m.get("port_up"))
    stale_n = sum(1 for m in machines if m.get("stale"))
    print(f"  {DIM}Total: {total}  |  Online: {GRN}{online}{R}{DIM}"
          f"  |  Stale: {RED}{stale_n}{R}{DIM}  |  "
          f"Master key: {CONFIG['MASTER_KEY_FILE']}{R}")


# ═══════════════════════════════════════════════════════════════
#  MACHINE CONNECTION (admin operations)
# ═══════════════════════════════════════════════════════════════

def connect_machine_with_master_key(machine):
    """
    Connect to a Host A machine using the VPS master private key.
    No password needed — the key was already installed by host_a.py.
    """
    port     = machine["tunnel_port"]
    name     = machine["name"]
    username = machine.get("username", "")

    if not username:
        import getpass
        username = input(f"  Username on '{name}': ").strip()

    info(f"Auto-connecting to '{name}' on port {port} using master key...")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname     = "127.0.0.1",
        port         = port,
        username     = username,
        key_filename = get_master_privkey_path(),
        timeout      = 10,
    )
    ok(f"Connected to '{name}' (key-based, no password).")
    return client


def run_cmd(client, cmd):
    _, stdout, stderr = client.exec_command(cmd)
    rc = stdout.channel.recv_exit_status()
    return (stdout.read().decode(errors="replace").strip(),
            stderr.read().decode(errors="replace").strip(), rc)


# ═══════════════════════════════════════════════════════════════
#  SCP PROGRESS
# ═══════════════════════════════════════════════════════════════

def scp_prog(filename, size, sent):
    if size > 0:
        pct = (sent / size) * 100
        filled = int(30 * sent // size)
        bar = f"{GRN}{'█'*filled}{'░'*(30-filled)}{R}"
        name = os.path.basename(filename.decode() if isinstance(filename, bytes) else filename)
        print(f"\r  [{bar}] {pct:5.1f}%  {name[:35]}", end="", flush=True)
        if sent == size:
            print()


# ═══════════════════════════════════════════════════════════════
#  AUTO BACKGROUND MONITOR THREAD
# ═══════════════════════════════════════════════════════════════

_monitor_data = {"machines": [], "lock": threading.Lock()}

def monitor_thread_fn(stop_event):
    """
    Background thread: every SCAN_INTERVAL_S seconds,
    reload registry and scan ports. Stores results in shared dict.
    """
    while not stop_event.is_set():
        machines = load_registry()
        machines = scan_all_ports(machines)
        with _monitor_data["lock"]:
            _monitor_data["machines"] = machines
        stop_event.wait(CONFIG["SCAN_INTERVAL_S"])


def get_live_machines():
    with _monitor_data["lock"]:
        return list(_monitor_data["machines"])


# ═══════════════════════════════════════════════════════════════
#  RELAY: Machine A -> VPS staging -> Machine B
# ═══════════════════════════════════════════════════════════════

def relay_wizard(machines):
    if len(machines) < 2:
        warn("Need at least 2 machines to relay.")
        return

    import getpass
    title("  FILE RELAY  (A -> VPS -> B)")
    display_dashboard(machines, show_title=False)

    try:
        a_idx = int(input("\n  Source machine #: ").strip()) - 1
        b_idx = int(input("  Destination machine #: ").strip()) - 1
    except (ValueError, EOFError):
        return

    if not (0 <= a_idx < len(machines) and 0 <= b_idx < len(machines)):
        warn("Invalid selection.")
        return
    if a_idx == b_idx:
        warn("Source and destination must differ.")
        return

    ma, mb = machines[a_idx], machines[b_idx]
    file_path = input(f"  Remote file path on '{ma['name']}': ").strip()
    dest_path = input(f"  Destination path on '{mb['name']}': ").strip()

    os.makedirs(CONFIG["TEMP_STAGE_DIR"], exist_ok=True)
    stage = os.path.join(CONFIG["TEMP_STAGE_DIR"], os.path.basename(file_path))

    # Download from A
    try:
        ssh_a = connect_machine_with_master_key(ma)
        with SCPClient(ssh_a.get_transport(), progress=scp_prog) as scp:
            scp.get(file_path, stage)
        print()
        ok("File staged on VPS.")
        ssh_a.close()
    except Exception as e:
        fail(f"Download from '{ma['name']}' failed: {e}")
        return

    # Upload to B
    try:
        ssh_b = connect_machine_with_master_key(mb)
        with SCPClient(ssh_b.get_transport(), progress=scp_prog) as scp:
            scp.put(stage, dest_path)
        print()
        ok(f"Delivered to '{mb['name']}' at {dest_path}")
        ssh_b.close()
    except Exception as e:
        fail(f"Upload to '{mb['name']}' failed: {e}")
        return

    if os.path.exists(stage):
        os.remove(stage)
    ok("Relay complete! Temporary file cleaned up.")


# ═══════════════════════════════════════════════════════════════
#  REMOTE COMMAND WIZARD
# ═══════════════════════════════════════════════════════════════

def remote_command_wizard(machines):
    if not machines:
        warn("No machines available.")
        return

    display_dashboard(machines, show_title=False)
    try:
        idx = int(input("\n  Machine #: ").strip()) - 1
    except (ValueError, EOFError):
        return

    if not (0 <= idx < len(machines)):
        warn("Invalid.")
        return

    m   = machines[idx]
    cmd = input(f"  Command to run on '{m['name']}': ").strip()
    if not cmd:
        return

    try:
        ssh = connect_machine_with_master_key(m)
        out, err_out, rc = run_cmd(ssh, cmd)
        sep()
        if out:
            print(f"{GRN}stdout:{R}\n{out}")
        if err_out:
            print(f"{YEL}stderr:{R}\n{err_out}")
        print(f"{DIM}Exit code: {rc}{R}")
        sep()
        ssh.close()
    except Exception as e:
        fail(f"Failed: {e}")


# ═══════════════════════════════════════════════════════════════
#  WATCH MODE (display-only, auto-refresh)
# ═══════════════════════════════════════════════════════════════

def watch_mode():
    info("Watch mode — press Ctrl+C to return to menu.")
    try:
        while True:
            os.system("clear")
            print(BANNER)
            machines = get_live_machines()
            display_dashboard(machines)
            pubkey = get_master_pubkey()
            print(f"\n  {DIM}Master pubkey: {pubkey[:60]}...{R}")
            print(f"  {DIM}Auto-refreshing every {CONFIG['SCAN_INTERVAL_S']}s{R}")
            time.sleep(CONFIG["SCAN_INTERVAL_S"])
    except KeyboardInterrupt:
        print()


# ═══════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════

def main_menu():
    while True:
        machines = get_live_machines()
        display_dashboard(machines)

        title("  ADMIN MENU")
        sep()
        print(f"  {GRN}1{R}  Refresh list")
        print(f"  {GRN}2{R}  Watch mode (auto-refresh)")
        print(f"  {GRN}3{R}  Run command on a machine (auto key-auth)")
        print(f"  {GRN}4{R}  Relay file between two machines (auto key-auth)")
        print(f"  {GRN}5{R}  Show master public key")
        print(f"  {GRN}6{R}  Remove stale registry entries")
        print(f"  {GRN}7{R}  Show raw registry JSON")
        print(f"  {RED}q{R}  Quit")
        sep()

        try:
            c = input(f"  {CYN}>{R} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if   c == "1": continue
        elif c == "2": watch_mode()
        elif c == "3": remote_command_wizard(machines)
        elif c == "4": relay_wizard(machines)
        elif c == "5":
            pubkey = get_master_pubkey()
            sep()
            print(f"  {BOLD}VPS Master Public Key:{R}")
            print(f"  {CYN}{pubkey}{R}")
            print(f"\n  {DIM}This is automatically installed on Host A machines.{R}")
            sep()
        elif c == "6": cleanup_stale_entries()
        elif c == "7":
            for m in machines:
                print(json.dumps({k: v for k, v in m.items()
                                  if k not in ("port_up","stale","age_s")}, indent=2))
        elif c in ("q", "quit", "exit"):
            break
        else:
            warn(f"Unknown option '{c}'.")


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true",
                        help="Start directly in watch mode")
    args = parser.parse_args()

    print(BANNER)

    # Step 1: Ensure directories and master key exist
    os.makedirs(CONFIG["VPS_REGISTRY_DIR"], exist_ok=True)
    os.makedirs(CONFIG["TEMP_STAGE_DIR"], exist_ok=True)
    ensure_master_key()

    # Step 2: Start background monitor thread
    stop_event = threading.Event()
    mon = threading.Thread(target=monitor_thread_fn, args=(stop_event,), daemon=True)
    mon.start()
    info(f"Auto-monitor started (scanning every {CONFIG['SCAN_INTERVAL_S']}s).")
    info(f"Registry: {CONFIG['VPS_REGISTRY_DIR']}")

    # Give monitor one cycle to load initial data
    time.sleep(1)

    try:
        if args.watch:
            watch_mode()
        else:
            main_menu()
    finally:
        stop_event.set()
        info("VPS bridge stopped.")


if __name__ == "__main__":
    main()
