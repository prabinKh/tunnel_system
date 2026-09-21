#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              HOST A  —  SOURCE MACHINE AGENT                 ║
║   Universal cross-platform agent: Windows, macOS & Linux     ║
╠══════════════════════════════════════════════════════════════╣
║  Just run:  python3 host_a.py                                ║
║  Or:        ./host_a.py  (if executable)                     ║
║                                                              ║
║  This script AUTOMATICALLY detects OS & performs:            ║
║    1. Auto-installs requirements (paramiko, scp)             ║
║    2. Detects & enables local SSH server (Win / Mac / Linux) ║
║    3. Configures permissions on shared directory             ║
║    4. Installs VPS master public key into authorized_keys    ║
║       (including Windows administrators_authorized_keys)     ║
║    5. Registers machine identity on the VPS                  ║
║    6. Opens & maintains reverse SSH tunnel with auto-reconnect║
║    7. Sends background heartbeats to VPS                     ║
╚══════════════════════════════════════════════════════════════╝
"""

# ─────────────────────────────────────────────────────────────
#  STEP 0: Auto-install dependencies before any other imports
# ─────────────────────────────────────────────────────────────
import sys, subprocess, os, platform

def _ensure_packages():
    required = {"paramiko": "paramiko", "scp": "scp"}
    missing  = []
    for mod, pkg in required.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[SETUP] Installing required packages: {', '.join(missing)}")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet"] + missing,
                stderr=subprocess.DEVNULL
            )
            print("[SETUP] Installation complete. Continuing...\n")
        except subprocess.CalledProcessError:
            try:
                # Try with --break-system-packages (Debian 12+ / Ubuntu 23+)
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--quiet",
                     "--break-system-packages"] + missing
                )
                print("[SETUP] Installation complete. Continuing...\n")
            except Exception as e:
                print(f"[SETUP] Warning: pip install failed ({e}). Attempting to proceed...")

_ensure_packages()

# ─────────────────────────────────────────────────────────────
#  Safe standard imports
# ─────────────────────────────────────────────────────────────
import time, stat, json, socket, hashlib, argparse
import threading, signal, getpass
import paramiko

# ═════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═════════════════════════════════════════════════════════════
CONFIG = {
    # ── VPS (Public Bridge) ──────────────────────────────────
    "VPS_IP":       "144.91.72.44",
    "VPS_USER":     "prabin",
    "VPS_PORT":     22,
    "VPS_PASSWORD": "Prabin@1234#",
    "VPS_KEY_PATH": "",               # leave "" to use password

    # ── Machine Identity ─────────────────────────────────────
    "MACHINE_NAME": "",               # "" = auto-detect hostname

    # ── Tunnel Port Range ────────────────────────────────────
    "PORT_RANGE_START": 22100,
    "PORT_RANGE_SIZE":  500,

    # ── Shared Directory ─────────────────────────────────────
    "SHARE_ROOT":  os.path.expanduser("~/shared_files"),

    # ── VPS Registry ─────────────────────────────────────────
    "VPS_REGISTRY_DIR":  "/home/prabin/tunnel_system/registry",
    "VPS_MASTER_PUBKEY": "/home/prabin/tunnel_system/registry/master_key.pub",

    # ── Local authorized_keys ────────────────────────────────
    "AUTHORIZED_KEYS": os.path.expanduser("~/.ssh/authorized_keys"),

    # ── Options ──────────────────────────────────────────────
    "AUTO_GRANT_PERMISSIONS": True,
    "HEARTBEAT_INTERVAL":     30,
}

# ═════════════════════════════════════════════════════════════
#  EMBEDDED MASTER PUBLIC KEY
#  This key is installed so Host B can connect automatically
#  without any password.
# ═════════════════════════════════════════════════════════════
MASTER_PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByK4+P+33oBAdWKWsYiUAAV"
    "caxDY1NIpfR4Yyvvjh+B vps-tunnel-master"
)

# ─── Colours ─────────────────────────────────────────────────
R="\033[0m"; BOLD="\033[1m"; BLU="\033[94m"; GRN="\033[92m"
YEL="\033[93m"; RED="\033[91m"; CYN="\033[96m"; DIM="\033[2m"

# Disable ANSI colors on legacy Windows cmd if needed
if platform.system() == "Windows":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

def info(m):  print(f"{BLU}[INFO]{R}  {m}")
def ok(m):    print(f"{GRN}[ OK ]{R}  {m}")
def warn(m):  print(f"{YEL}[WARN]{R}  {m}")
def err(m):   print(f"{RED}[ERR ]{R}  {m}")
def sep():    print("─" * 60)

BANNER = f"""
{BOLD}{CYN}
  ██╗  ██╗ ██████╗ ███████╗████████╗     █████╗
  ██║  ██║██╔═══██╗██╔════╝╚══██╔══╝    ██╔══██╗
  ███████║██║   ██║███████╗   ██║       ███████║
  ██╔══██║██║   ██║╚════██║   ██║       ██╔══██║
  ██║  ██║╚██████╔╝███████║   ██║       ██║  ██║
  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝       ╚═╝  ╚═╝
  Source Machine Agent  |  Auto-Connect & Share
{R}"""


# ═════════════════════════════════════════════════════════════
#  HELPERS & OS DETECTION
# ═════════════════════════════════════════════════════════════

def get_machine_name(override=""):
    if override:
        return override.strip().replace(" ", "_")
    return socket.gethostname().replace(" ", "_")

def compute_tunnel_port(name):
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return CONFIG["PORT_RANGE_START"] + (h % CONFIG["PORT_RANGE_SIZE"])

def get_current_username():
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("USERNAME") or "user"

# ─── STEP 1: Grant permissions ────────────────────────────────
def grant_permissions(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        ok(f"Created share directory: {path}")
    info(f"Setting permissions on share folder: {path}")
    
    sys_name = platform.system()
    if sys_name in ("Darwin", "Linux"):
        try:
            for root, dirs, files in os.walk(path):
                for d in dirs:
                    os.chmod(os.path.join(root, d),
                        stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP |
                        stat.S_IROTH | stat.S_IXOTH)
                for f in files:
                    os.chmod(os.path.join(root, f),
                        stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |
                        stat.S_IRGRP | stat.S_IROTH)
            os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP |
                            stat.S_IROTH | stat.S_IXOTH)
            ok(f"Permissions set on: {path}")
        except Exception as e:
            warn(f"Permission warning: {e}")
    else:
        # Windows
        ok(f"Directory ready on Windows: {path}")

# ─── STEP 2: Check & auto-enable local SSH daemon ─────────────
def is_ssh_port_open():
    try:
        s = socket.create_connection(("127.0.0.1", 22), timeout=2)
        s.close()
        return True
    except Exception:
        return False

def enable_ssh_macos():
    """Try to enable Remote Login (SSH) on macOS automatically."""
    info("Attempting to auto-enable SSH on macOS...")
    methods = [
        ["sudo", "-n", "launchctl", "load", "-w", "/System/Library/LaunchDaemons/ssh.plist"],
        ["sudo", "-n", "launchctl", "enable", "system/com.openssh.sshd"],
        ["sudo", "-n", "systemsetup", "-setremotelogin", "on"],
    ]
    for cmd in methods:
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=5)
            if res.returncode == 0:
                time.sleep(1)
                if is_ssh_port_open():
                    ok("SSH enabled automatically via macOS service manager.")
                    return True
        except Exception:
            pass
    return False

def enable_ssh_linux():
    """Try to start SSH service on Linux automatically."""
    info("Attempting to auto-start SSH service on Linux...")
    # Try systemctl / service without password
    service_cmds = [
        ["sudo", "-n", "systemctl", "enable", "--now", "ssh"],
        ["sudo", "-n", "systemctl", "enable", "--now", "sshd"],
        ["sudo", "-n", "systemctl", "start", "ssh"],
        ["sudo", "-n", "systemctl", "start", "sshd"],
        ["sudo", "-n", "service", "ssh", "start"],
        ["sudo", "-n", "service", "sshd", "start"],
    ]
    for cmd in service_cmds:
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
            time.sleep(1)
            if is_ssh_port_open():
                ok("SSH service started on Linux.")
                return True
        except Exception:
            pass

    # Check if sshd binary even exists
    sshd_exists = False
    for path in ["/usr/sbin/sshd", "/usr/bin/sshd", "/sbin/sshd"]:
        if os.path.exists(path):
            sshd_exists = True
            break

    if not sshd_exists:
        warn("OpenSSH server is not installed on this Linux machine.")
        # Attempt installation if sudo without password works
        pkg_managers = [
            ["sudo", "-n", "apt-get", "update", "-y", "&&", "sudo", "-n", "apt-get", "install", "-y", "openssh-server"],
            ["sudo", "-n", "yum", "install", "-y", "openssh-server"],
            ["sudo", "-n", "dnf", "install", "-y", "openssh-server"],
            ["sudo", "-n", "pacman", "-Sy", "--noconfirm", "openssh"],
            ["sudo", "-n", "apk", "add", "openssh"],
        ]
        for cmd in pkg_managers:
            try:
                subprocess.run(" ".join(cmd), shell=True, capture_output=True, timeout=60)
                if any(os.path.exists(p) for p in ["/usr/sbin/sshd", "/usr/bin/sshd", "/sbin/sshd"]):
                    ok("Installed OpenSSH server.")
                    subprocess.run(["sudo", "-n", "systemctl", "enable", "--now", "ssh"], capture_output=True)
                    subprocess.run(["sudo", "-n", "systemctl", "enable", "--now", "sshd"], capture_output=True)
                    time.sleep(1)
                    if is_ssh_port_open():
                        return True
            except Exception:
                pass

    return False

def enable_ssh_windows():
    """Try to start and install OpenSSH server on Windows."""
    info("Checking OpenSSH server on Windows...")
    try:
        # Check and start sshd service
        ps_start = (
            "Start-Service sshd -ErrorAction SilentlyContinue; "
            "Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_start], capture_output=True, timeout=10)
        time.sleep(1)
        if is_ssh_port_open():
            ok("OpenSSH Server is running on Windows.")
            return True

        # If not running, attempt installation of OpenSSH capability
        info("Installing OpenSSH.Server capability on Windows...")
        ps_install = (
            "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction SilentlyContinue; "
            "Start-Service sshd; "
            "Set-Service -Name sshd -StartupType Automatic; "
            "if (!(Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) { "
            "  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 "
            "}"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_install], capture_output=True, timeout=90)
        time.sleep(2)
        if is_ssh_port_open():
            ok("OpenSSH Server installed and started on Windows.")
            return True
    except Exception as e:
        warn(f"Windows SSH auto-enable error: {e}")
    return False


def check_local_ssh():
    info("Checking local SSH daemon on port 22...")
    if is_ssh_port_open():
        ok("Local SSH is running on port 22.")
        return True

    sys_name = platform.system()
    warn(f"Local SSH is not running on {sys_name}. Attempting to enable it...")

    if sys_name == "Darwin":
        if enable_ssh_macos():
            return True
        print()
        print(f"  {YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
        print(f"  {BOLD}Enable Remote Login (SSH) on macOS{R}")
        print(f"  {YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
        print(f"  Go to:")
        print(f"  {CYN}  System Settings → General → Sharing → Remote Login → Turn ON{R}")
        print()
        print(f"  Or in a terminal:")
        print(f"  {GRN}  sudo launchctl load -w /System/Library/LaunchDaemons/ssh.plist{R}")
        print()
        input(f"  Press {BOLD}Enter{R} after enabling Remote Login to continue... ")
        if is_ssh_port_open():
            ok("SSH is now running!")
            return True
        err("SSH still not detected on port 22.")
        return False

    elif sys_name == "Linux":
        if enable_ssh_linux():
            return True
        print()
        print(f"  {YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
        print(f"  {BOLD}Enable SSH Server on Linux{R}")
        print(f"  {YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
        print(f"  Run:")
        print(f"  {GRN}  sudo apt-get install -y openssh-server && sudo systemctl enable --now ssh{R}")
        print(f"  {CYN}  (or sudo systemctl enable --now sshd on RHEL/CentOS/Arch){R}")
        print()
        input(f"  Press {BOLD}Enter{R} after starting SSH service... ")
        if is_ssh_port_open():
            ok("SSH is now running!")
            return True
        err("SSH still not detected on port 22.")
        return False

    elif sys_name == "Windows":
        if enable_ssh_windows():
            return True
        print()
        print(f"  {YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
        print(f"  {BOLD}Enable OpenSSH Server on Windows{R}")
        print(f"  {YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
        print(f"  Run PowerShell as Administrator:")
        print(f"  {GRN}  Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0{R}")
        print(f"  {GRN}  Start-Service sshd; Set-Service -Name sshd -StartupType Automatic{R}")
        print()
        print(f"  Or via Settings: Settings → System → Optional features → OpenSSH Server")
        print()
        input(f"  Press {BOLD}Enter{R} after starting OpenSSH Server... ")
        if is_ssh_port_open():
            ok("SSH is now running!")
            return True
        err("SSH still not detected on port 22.")
        return False

    return False

# ─── STEP 3: Install embedded master public key ───────────────
def install_master_pubkey():
    """
    Install the embedded VPS master public key into authorized_keys across
    Windows, macOS, and Linux.
    """
    info("Installing VPS master public key into authorized_keys...")
    sys_name = platform.system()
    
    # Standard user authorized_keys
    user_auth_keys = os.path.expanduser("~/.ssh/authorized_keys")
    target_files = [user_auth_keys]

    # Windows Administrator path
    if sys_name == "Windows":
        admin_auth_keys = os.path.expandvars(r"%ProgramData%\ssh\administrators_authorized_keys")
        target_files.append(admin_auth_keys)

    for auth_keys in target_files:
        try:
            ssh_dir = os.path.dirname(auth_keys)
            if not os.path.exists(ssh_dir):
                try:
                    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
                except Exception:
                    continue

            already_present = False
            if os.path.exists(auth_keys):
                try:
                    with open(auth_keys, "r", encoding="utf-8", errors="ignore") as f:
                        if MASTER_PUBLIC_KEY in f.read():
                            already_present = True
                except Exception:
                    pass

            if not already_present:
                with open(auth_keys, "a", encoding="utf-8") as f:
                    f.write(f"\n{MASTER_PUBLIC_KEY}\n")

            # Set POSIX permissions if on Mac/Linux
            if sys_name in ("Darwin", "Linux"):
                try:
                    os.chmod(ssh_dir, 0o700)
                    os.chmod(auth_keys, 0o600)
                except Exception:
                    pass
            elif sys_name == "Windows":
                # Fix Windows NTFS ACL permissions on administrators_authorized_keys if present
                if "administrators_authorized_keys" in auth_keys and os.path.exists(auth_keys):
                    try:
                        subprocess.run(
                            f'icacls "{auth_keys}" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"',
                            shell=True, capture_output=True, timeout=5
                        )
                    except Exception:
                        pass

            ok(f"Master public key registered in: {auth_keys}")
        except Exception as e:
            warn(f"Note on {auth_keys}: {e}")

    ok(f"{GRN}{BOLD}Host B can now connect WITHOUT a password!{R}")
    return True

# ─── STEP 4: VPS helpers ──────────────────────────────────────
def make_vps_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = {
        "hostname": CONFIG["VPS_IP"],
        "port":     CONFIG["VPS_PORT"],
        "username": CONFIG["VPS_USER"],
        "timeout":  15,
    }
    kp = os.path.expanduser(CONFIG["VPS_KEY_PATH"]) if CONFIG["VPS_KEY_PATH"] else None
    if kp and os.path.exists(kp):
        kw["key_filename"] = kp
    elif CONFIG["VPS_PASSWORD"]:
        kw["password"] = CONFIG["VPS_PASSWORD"]
    client.connect(**kw)
    return client

def vps_run(client, cmd):
    _, stdout, _ = client.exec_command(cmd)
    stdout.channel.recv_exit_status()
    return stdout.read().decode(errors="replace").strip()

# ─── STEP 5: Register on VPS ──────────────────────────────────
def register_on_vps(name, tunnel_port, share_root, username):
    try:
        client = make_vps_client()
        reg_dir = CONFIG["VPS_REGISTRY_DIR"]
        vps_run(client, f"mkdir -p {reg_dir} && chmod 777 {reg_dir}")
        entry = {
            "name":        name,
            "tunnel_port": tunnel_port,
            "share_root":  share_root,
            "hostname":    socket.gethostname(),
            "username":    username,
            "os":          platform.system(),
            "platform":    platform.platform(),
            "key_auth":    True,
            "registered":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "heartbeat":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        reg_file = f"{reg_dir}/{name}.json"
        vps_run(client, f"echo '{json.dumps(entry)}' > {reg_file}")
        client.close()
        ok(f"Registered as '{BOLD}{name}{R}' on VPS registry.")
        return True
    except Exception as e:
        warn(f"Registry write failed: {e}")
        return False

def refresh_heartbeat(name):
    try:
        client = make_vps_client()
        reg_file = f"{CONFIG['VPS_REGISTRY_DIR']}/{name}.json"
        raw = vps_run(client, f"cat '{reg_file}' 2>/dev/null || true")
        if raw:
            entry = json.loads(raw)
            entry["heartbeat"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            vps_run(client, f"echo '{json.dumps(entry)}' > {reg_file}")
        client.close()
    except Exception:
        pass

def deregister(name):
    try:
        client = make_vps_client()
        vps_run(client, f"rm -f '{CONFIG['VPS_REGISTRY_DIR']}/{name}.json'")
        client.close()
        ok("Removed from VPS registry.")
    except Exception:
        pass

# ─── Heartbeat thread ─────────────────────────────────────────
def heartbeat_loop(name, stop_event):
    while not stop_event.is_set():
        stop_event.wait(CONFIG["HEARTBEAT_INTERVAL"])
        if not stop_event.is_set():
            refresh_heartbeat(name)

# ─── STEP 6: Run reverse SSH tunnel ───────────────────────────
def run_tunnel(name, tunnel_port, stop_event):
    """Open persistent reverse tunnel using paramiko."""
    import socket as _socket
    
    while not stop_event.is_set():
        try:
            info("Connecting to VPS tunnel gateway...")
            transport = paramiko.Transport((CONFIG["VPS_IP"], CONFIG["VPS_PORT"]))
            kp = os.path.expanduser(CONFIG["VPS_KEY_PATH"]) if CONFIG["VPS_KEY_PATH"] else None
            if kp and os.path.exists(kp):
                transport.connect(username=CONFIG["VPS_USER"],
                                  pkey=paramiko.Ed25519Key.from_private_key_file(kp))
            else:
                transport.connect(username=CONFIG["VPS_USER"],
                                  password=CONFIG["VPS_PASSWORD"])

            # Request reverse port forward on VPS
            transport.request_port_forward("127.0.0.1", tunnel_port)

            print()
            print(f"  {GRN}{BOLD}TUNNEL IS OPEN  ✓{R}")
            print(f"  {CYN}Machine Name   :{R} {BOLD}{name}{R}")
            print(f"  {CYN}OS Type        :{R} {platform.system()} ({platform.platform()})")
            print(f"  {CYN}VPS Tunnel Port:{R} {BOLD}{tunnel_port}{R}  (auto-derived)")
            print(f"  {CYN}Share Folder   :{R} {CONFIG['SHARE_ROOT']}")
            print(f"  {CYN}VPS            :{R} {CONFIG['VPS_USER']}@{CONFIG['VPS_IP']}")
            print(f"\n  {YEL}Host B can now browse and download from this machine.{R}")
            print(f"  {YEL}Key-based access: NO PASSWORD required on Host B.{R}")
            print(f"  {DIM}Press Ctrl+C to disconnect.{R}\n")

            # Forward incoming connections from VPS tunnel port to local SSH port 22
            while not stop_event.is_set():
                chan = transport.accept(timeout=1)
                if chan is None:
                    continue

                def forward(ch):
                    try:
                        local = _socket.create_connection(("127.0.0.1", 22))
                        def pipe(src, dst):
                            try:
                                while True:
                                    data = src.recv(2048)
                                    if not data: break
                                    dst.sendall(data)
                            except Exception: pass
                            finally:
                                try: src.close()
                                except: pass
                                try: dst.close()
                                except: pass
                        threading.Thread(target=pipe, args=(ch, local), daemon=True).start()
                        threading.Thread(target=pipe, args=(local, ch), daemon=True).start()
                    except Exception as ex:
                        warn(f"Forward error: {ex}")

                threading.Thread(target=forward, args=(chan,), daemon=True).start()

            transport.close()
        except Exception as e:
            if stop_event.is_set():
                break
            warn(f"Tunnel dropped: {e}. Reconnecting in 5s...")
            time.sleep(5)


# ═════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Host A — Source Machine Agent")
    parser.add_argument("--name",  default="", help="Custom machine name (default: hostname)")
    parser.add_argument("--share", default="", help="Custom share directory path")
    args = parser.parse_args()

    print(BANNER)
    sep()

    if CONFIG["VPS_IP"] == "your_vps_ip":
        err("Set VPS_IP in CONFIG before running!")
        sys.exit(1)

    # Resolve identity
    machine_name = get_machine_name(args.name or CONFIG["MACHINE_NAME"])
    tunnel_port  = compute_tunnel_port(machine_name)
    share_root   = os.path.abspath(os.path.expanduser(args.share or CONFIG["SHARE_ROOT"]))
    CONFIG["SHARE_ROOT"] = share_root
    username     = get_current_username()

    print(f"  {CYN}Machine Name   :{R} {BOLD}{machine_name}{R}")
    print(f"  {CYN}Detected OS    :{R} {platform.system()} ({platform.machine()})")
    print(f"  {CYN}Tunnel Port    :{R} {BOLD}{tunnel_port}{R}  (auto-derived from name)")
    print(f"  {CYN}Share Directory:{R} {share_root}")
    print(f"  {CYN}Username       :{R} {username}")
    print(f"  {CYN}VPS            :{R} {CONFIG['VPS_USER']}@{CONFIG['VPS_IP']}")
    sep()
    print()

    # ── 1. Grant permissions ───────────────────────────────────
    if CONFIG["AUTO_GRANT_PERMISSIONS"]:
        grant_permissions(share_root)
        print()

    # ── 2. Check local SSH daemon ──────────────────────────────
    if not check_local_ssh():
        err("Please enable SSH on this machine and re-run host_a.py.")
        sys.exit(1)
    print()

    # ── 3. Install embedded master public key ──────────────────
    install_master_pubkey()
    print()

    # ── 4. Register on VPS ────────────────────────────────────
    info(f"Connecting to VPS {CONFIG['VPS_IP']} and registering...")
    if register_on_vps(machine_name, tunnel_port, share_root, username):
        ok(f"Machine '{machine_name}' is now visible to Host B!")
    print()

    # ── 5. Set up signals & heartbeat thread ──────────────────
    stop_event = threading.Event()

    def shutdown(sig, frame):
        stop_event.set()
        print(f"\n{YEL}Shutting down...{R}")
        deregister(machine_name)
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT,  shutdown)
        signal.signal(signal.SIGTERM, shutdown)
    except Exception:
        pass

    hb = threading.Thread(target=heartbeat_loop,
                          args=(machine_name, stop_event), daemon=True)
    hb.start()

    # ── 6. Open tunnel (blocking) ──────────────────────────────
    try:
        run_tunnel(machine_name, tunnel_port, stop_event)
    finally:
        stop_event.set()
        deregister(machine_name)


if __name__ == "__main__":
    main()
