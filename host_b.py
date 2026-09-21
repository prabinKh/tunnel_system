#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              HOST B  —  MAIN CONTROLLER                      ║
║   Run on YOUR machine to browse, execute commands & download ║
║   from any Host A machine (Windows, macOS, Linux) via VPS.   ║
╠══════════════════════════════════════════════════════════════╣
║  Just run:  python3 host_b.py                                ║
║  Or:        ./host_b.py  (if executable)                     ║
║                                                              ║
║  Features:                                                   ║
║    • Auto-discovers all online machines in VPS registry      ║
║    • Passwordless instant connection via embedded master key ║
║    • Universal SFTP file browser (Windows / Mac / Linux)     ║
║    • Remote Command Execution on any target machine (exec)   ║
║    • Single-file and bulk folder downloads                   ║
╠══════════════════════════════════════════════════════════════╣
║  COMMANDS IN BROWSER:                                        ║
║    <number>       → Open folder (or download if file)        ║
║    0 / ..         → Go up one folder level                   ║
║    d <num>        → Download specific file or folder         ║
║    da             → Download ALL items in current directory  ║
║    cd <path>      → Jump to absolute path                    ║
║    exec <command> → Execute a shell command on that machine  ║
║    info           → Show machine specifications              ║
║    machines / b   → Return to machine selection list         ║
║    q              → Quit                                     ║
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
        except subprocess.CalledProcessError:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--quiet",
                     "--break-system-packages"] + missing
                )
            except Exception as e:
                print(f"[SETUP] Warning: pip install failed ({e}). Proceeding...")
        print("[SETUP] Installation complete.\n")

_ensure_packages()

# ─────────────────────────────────────────────────────────────
#  Safe standard imports
# ─────────────────────────────────────────────────────────────
import time, json, stat, tempfile, posixpath, ntpath
import paramiko
from scp import SCPClient

# Disable ANSI colors on legacy Windows cmd if needed
if platform.system() == "Windows":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# ═════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═════════════════════════════════════════════════════════════
CONFIG = {
    # ── VPS (Public Bridge) ──────────────────────────────────
    "VPS_IP":       "144.91.72.44",
    "VPS_USER":     "prabin",
    "VPS_PORT":     22,
    "VPS_PASSWORD": "Prabin@1234#",
    "VPS_KEY_PATH": "",

    # ── VPS paths ────────────────────────────────────────────
    "VPS_REGISTRY_DIR":    "/home/prabin/tunnel_system/registry",
    "VPS_MASTER_KEY_FILE": "/home/prabin/tunnel_system/registry/master_key",

    # ── Where downloaded files are saved on THIS machine ─────
    "LOCAL_DOWNLOAD_DIR": os.path.expanduser("~/Downloads/from_tunnel"),

    # ── Locally cached copy of master private key ────────────
    "LOCAL_KEY_CACHE": os.path.expanduser("~/.ssh/tunnel_master_key"),

    "CONNECT_TIMEOUT": 15,
}

# ═════════════════════════════════════════════════════════════
#  EMBEDDED MASTER PRIVATE KEY
# ═════════════════════════════════════════════════════════════
MASTER_PRIVATE_KEY = """\
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACAciuPj/t96AQHVilrGIlAAFXGsQ2NTSKX0eGMr744fgQAAAJgFEj2nBRI9
pwAAAAtzc2gtZWQyNTUxOQAAACAciuPj/t96AQHVilrGIlAAFXGsQ2NTSKX0eGMr744fgQ
AAAEDdxYkNehpMCzn3animpTCtL3svAS4VIBhfVbkjLRlF6hyK4+P+33oBAdWKWsYiUAAV
caxDY1NIpfR4Yyvvjh+BAAAAEXZwcy10dW5uZWwtbWFzdGVyAQIDBA==
-----END OPENSSH PRIVATE KEY-----
"""

# ─── Colours ─────────────────────────────────────────────────
R="\033[0m"; BOLD="\033[1m"; BLU="\033[94m"; GRN="\033[92m"
YEL="\033[93m"; RED="\033[91m"; CYN="\033[96m"; DIM="\033[2m"; MAG="\033[95m"

def info(m):  print(f"{BLU}[INFO]{R}  {m}")
def ok(m):    print(f"{GRN}[ OK ]{R}  {m}")
def warn(m):  print(f"{YEL}[WARN]{R}  {m}")
def err(m):   print(f"{RED}[ERR ]{R}  {m}")
def sep(ch="─", w=70): print(ch * w)
def title(m): print(f"\n{BOLD}{CYN}{m}{R}")

BANNER = f"""
{BOLD}{CYN}
  ██╗  ██╗ ██████╗ ███████╗████████╗    ██████╗
  ██║  ██║██╔═══██╗██╔════╝╚══██╔══╝    ██╔══██╗
  ███████║██║   ██║███████╗   ██║       ██████╔╝
  ██╔══██║██║   ██║╚════██║   ██║       ██╔══██╗
  ██║  ██║╚██████╔╝███████║   ██║       ██████╔╝
  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝       ╚═════╝
  Universal Controller  |  Win • Mac • Linux  |  Auto-Connect
{R}"""


# ═════════════════════════════════════════════════════════════
#  VPS CONNECTION
# ═════════════════════════════════════════════════════════════

def connect_vps():
    info(f"Connecting to VPS {CONFIG['VPS_IP']}:{CONFIG['VPS_PORT']} ...")
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
    ok("Connected to VPS.")
    return client

def vps_run(vps, cmd):
    _, stdout, _ = vps.exec_command(cmd)
    stdout.channel.recv_exit_status()
    return stdout.read().decode(errors="replace").strip()


# ═════════════════════════════════════════════════════════════
#  MASTER KEY RETRIEVAL
# ═════════════════════════════════════════════════════════════

_KEY_PLACEHOLDER_MARKER = "PLACEHOLDER_NOT_A_REAL_KEY_IGNORE_ME"

def get_master_key_path(vps):
    cache_path = CONFIG["LOCAL_KEY_CACHE"]
    embedded = MASTER_PRIVATE_KEY.strip()
    is_placeholder = (
        not embedded
        or "-----BEGIN OPENSSH PRIVATE KEY-----" not in embedded
        or _KEY_PLACEHOLDER_MARKER in embedded
        or len(embedded) < 200
    )

    if not is_placeholder:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_tunnel_key", mode="w")
        tmp.write(embedded + "\n")
        tmp.close()
        try:
            os.chmod(tmp.name, 0o600)
        except Exception:
            pass
        ok("Using embedded master key.")
        return tmp.name

    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
        ok(f"Using cached master key: {cache_path}")
        return cache_path

    info("Downloading master private key from VPS...")
    vps_key = CONFIG["VPS_MASTER_KEY_FILE"]
    check = vps_run(vps, f"test -f '{vps_key}' && echo OK || echo MISSING")
    if check != "OK":
        err(f"Master key not found on VPS at {vps_key}")
        return None
    try:
        os.makedirs(os.path.dirname(cache_path), mode=0o700, exist_ok=True)
    except Exception:
        pass
    with SCPClient(vps.get_transport()) as scp:
        scp.get(vps_key, cache_path)
    try:
        os.chmod(cache_path, 0o600)
    except Exception:
        pass
    ok(f"Master key cached: {cache_path}")
    return cache_path


# ═════════════════════════════════════════════════════════════
#  REGISTRY: DISCOVER MACHINES
# ═════════════════════════════════════════════════════════════

def fetch_registry(vps):
    reg_dir = CONFIG["VPS_REGISTRY_DIR"]
    raw = vps_run(vps, f"ls {reg_dir}/*.json 2>/dev/null || true")
    if not raw:
        return []
    
    # Check currently listening tunnel ports directly on VPS
    open_ports_raw = vps_run(vps, "ss -tlnH 2>/dev/null || netstat -tlpn 2>/dev/null || true")
    
    machines = []
    for fpath in raw.splitlines():
        if not fpath.strip().endswith(".json"):
            continue
        content = vps_run(vps, f"cat '{fpath.strip()}' 2>/dev/null || true")
        if not content:
            continue
        try:
            m = json.loads(content)
            port_str = f":{m.get('tunnel_port', -1)}"
            port_is_open = (port_str in open_ports_raw)

            try:
                hb_t = time.mktime(time.strptime(
                    m.get("heartbeat",""), "%Y-%m-%dT%H:%M:%SZ"))
                age = time.time() - hb_t
                m["online"] = port_is_open or (age < 120)
                m["age_s"]  = int(age) if age >= 0 else 0
            except Exception:
                m["online"] = port_is_open
                m["age_s"]  = 0
            machines.append(m)
        except json.JSONDecodeError:
            pass
    return sorted(machines, key=lambda x: x.get("name",""))



def display_machine_list(machines):
    title("  CONNECTED MACHINES (WINDOWS / MAC / LINUX)")
    sep("═")
    if not machines:
        print(f"  {YEL}No machines registered yet.{R}")
        print(f"  {DIM}Run host_a.py on your target machines first.{R}")
        sep("═")
        return
    print(f"  {BOLD}{'#':<4}  {'STATUS':<12}  {'OS':<10}  {'NAME':<24}  {'PORT':<6}  AGE{R}")
    sep()
    for i, m in enumerate(machines, 1):
        online   = m.get("online", False)
        os_type  = m.get("os", "Linux")[:9]
        age_s    = m.get("age_s", 0)
        status   = f"{GRN}● ONLINE   {R}" if online else f"{RED}○ OFFLINE  {R}"
        age_str  = f"{age_s}s" if age_s < 3600 else f"{age_s//60}m"
        name     = m.get("name", "?")
        port     = m.get("tunnel_port", "?")
        print(f"  {str(i):<4}  {status}  {CYN}{os_type:<10}{R}  "
              f"{BOLD}{name:<24}{R}  {BLU}{port:<6}{R}  {DIM}{age_str}{R}")
    sep("═")


# ═════════════════════════════════════════════════════════════
#  AUTO-CONNECT TO HOST A
# ═════════════════════════════════════════════════════════════

def connect_to_machine(vps, machine, key_path):
    tunnel_port = machine["tunnel_port"]
    name        = machine["name"]
    username    = machine.get("username", "")
    key_auth    = machine.get("key_auth", False)
    os_name     = machine.get("os", "")

    info(f"Connecting to '{name}' ({os_name}) via reverse tunnel port {tunnel_port} ...")

    try:
        channel = vps.get_transport().open_channel(
            "direct-tcpip",
            ("127.0.0.1", tunnel_port),
            ("127.0.0.1", 0),
        )
    except Exception as e:
        err(f"Cannot open tunnel channel to port {tunnel_port}: {e}")
        err("Is host_a.py running on that machine?")
        return None

    if not username:
        import getpass
        username = input(f"  Username on '{name}': ").strip()

    host_a = paramiko.SSHClient()
    host_a.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = {
        "hostname": "127.0.0.1",
        "port":     tunnel_port,
        "username": username,
        "sock":     channel,
        "timeout":  CONFIG["CONNECT_TIMEOUT"],
    }

    # Try key authentication first (master key)
    if key_auth and key_path and os.path.exists(key_path):
        kw["key_filename"] = key_path
        try:
            host_a.connect(**kw)
            ok(f"Connected to '{name}'  {GRN}(passwordless — master key ✓){R}")
            return host_a
        except paramiko.AuthenticationException:
            warn("Key auth was rejected by host. Falling back to password...")
            del kw["key_filename"]
        except Exception as e:
            warn(f"Key attempt failed ({e}). Falling back to password...")
            if "key_filename" in kw:
                del kw["key_filename"]

    # Password fallback
    import getpass
    kw["password"] = getpass.getpass(f"  Password for '{username}@{name}': ")
    try:
        host_a.connect(**kw)
        ok(f"Connected to '{name}'  {YEL}(password){R}")
        return host_a
    except Exception as e:
        err(f"Connection failed: {e}")
        return None


# ═════════════════════════════════════════════════════════════
#  UNIVERSAL SFTP FILE BROWSER & COMMAND RUNNER
# ═════════════════════════════════════════════════════════════

def fmt_size(n):
    try:
        n = int(n)
        if n > 1_073_741_824: return f"{GRN}{n/1_073_741_824:6.1f}G{R}"
        if n > 1_048_576:     return f"{CYN}{n/1_048_576:6.1f}M{R}"
        if n > 1024:          return f"{BLU}{n/1024:6.1f}K{R}"
        return f"{DIM}{n:7d}{R}"
    except Exception:
        return f"{str(n):>7}"

def normalize_remote_path(p, is_windows=False):
    if not p:
        return "/"
    p = p.strip()
    if is_windows:
        return p.replace("/", "\\")
    return p.replace("\\", "/")

def get_parent_dir(p, is_windows=False):
    if is_windows:
        parent = ntpath.dirname(p.rstrip("\\"))
        return parent if parent else p
    else:
        parent = posixpath.dirname(p.rstrip("/"))
        return parent if parent else "/"

def join_remote_path(base, item, is_windows=False):
    if is_windows:
        return ntpath.join(base, item)
    return posixpath.join(base, item)

def list_sftp_dir(sftp, remote_path):
    try:
        raw_attrs = sftp.listdir_attr(remote_path)
    except Exception as e:
        return None, str(e)

    entries = []
    for a in raw_attrs:
        name = a.filename
        if name in (".", ".."):
            continue
        is_dir = stat.S_ISDIR(a.st_mode) if a.st_mode else False
        is_lnk = stat.S_ISLNK(a.st_mode) if a.st_mode else False
        kind = "DIR" if is_dir else "LNK" if is_lnk else "FILE"
        entries.append({
            "name":  name,
            "type":  kind,
            "size":  a.st_size if a.st_size is not None else 0,
            "mtime": a.st_mtime or 0,
        })
    # Sort: folders first, then files alphabetically
    entries.sort(key=lambda x: (0 if x["type"] == "DIR" else 1, x["name"].lower()))
    return entries, None

def display_listing(entries, current_path, machine_name, os_type):
    title(f"  [{machine_name} | {os_type}]  📁 {current_path}")
    sep()
    print(f"  {BOLD}{'#':<5} {'TYPE':<7} {'SIZE':>9}   NAME{R}")
    sep()
    print(f"  {'0':<5} {YEL}[..]   {R}{'':>9}   {YEL}.. (go up){R}")
    for i, e in enumerate(entries, 1):
        if e["type"] == "DIR":
            col, tag = BLU, "[DIR]  "
        elif e["type"] == "LNK":
            col, tag = MAG, "[LNK]  "
        else:
            col, tag = R, "[FILE] "
        print(f"  {str(i):<5} {col}{tag}{R} {fmt_size(e['size'])}   {col}{e['name']}{R}")
    sep()
    print(f"  {DIM}{len(entries)} items in folder{R}")


# ─── Remote command execution ─────────────────────────────────
def execute_remote_command(client, command, os_type):
    info(f"Running on remote [{os_type}]: {command}")
    print()
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=30)
        out = stdout.read().decode(errors="replace")
        err_out = stderr.read().decode(errors="replace")
        if out:
            print(out.rstrip())
        if err_out:
            print(f"{RED}{err_out.rstrip()}{R}")
        rc = stdout.channel.recv_exit_status()
        print(f"\n{DIM}[Exit code: {rc}]{R}")
    except Exception as e:
        err(f"Execution failed: {e}")


# ─── File & Folder Downloads ──────────────────────────────────
def scp_progress(filename, size, sent):
    if size > 0:
        pct    = (sent / size) * 100
        filled = int(30 * sent // size)
        bar    = f"{GRN}{'█'*filled}{'░'*(30-filled)}{R}"
        fname  = os.path.basename(filename.decode() if isinstance(filename, bytes) else filename)
        print(f"\r  [{bar}] {pct:5.1f}%  {fname[:38]:<38}", end="", flush=True)
        if sent == size:
            print()

def download_sftp_recursive(sftp, remote_dir, local_dir, is_windows=False):
    os.makedirs(local_dir, exist_ok=True)
    try:
        attrs = sftp.listdir_attr(remote_dir)
    except Exception as e:
        err(f"Cannot list {remote_dir}: {e}")
        return
    for a in attrs:
        if a.filename in (".", ".."):
            continue
        r_path = join_remote_path(remote_dir, a.filename, is_windows)
        l_path = os.path.join(local_dir, a.filename)
        if stat.S_ISDIR(a.st_mode):
            download_sftp_recursive(sftp, r_path, l_path, is_windows)
        else:
            try:
                print(f"  {DIM}Downloading {a.filename} ({fmt_size(a.st_size)})...{R}")
                sftp.get(r_path, l_path)
            except Exception as e:
                warn(f"Failed to download {a.filename}: {e}")

def download_item(host_a, sftp, remote_path, local_dir, is_dir=False, is_windows=False):
    os.makedirs(local_dir, exist_ok=True)
    item_name = os.path.basename(remote_path.replace("\\", "/").rstrip("/"))
    local_path = os.path.join(local_dir, item_name)
    label = "folder" if is_dir else "file"
    
    info(f"Downloading {label}: {remote_path}")
    info(f"Saving to:          {local_path}")
    print()

    if is_dir:
        download_sftp_recursive(sftp, remote_path, local_path, is_windows)
        ok(f"Folder downloaded → {local_path}")
    else:
        try:
            with SCPClient(host_a.get_transport(), progress=scp_progress) as scp:
                scp.get(remote_path, local_path)
            ok(f"Saved: {local_path}")
        except Exception:
            # Fallback to SFTP get
            try:
                sftp.get(remote_path, local_path)
                ok(f"Saved (via SFTP): {local_path}")
            except Exception as e:
                err(f"Download error: {e}")


# ═════════════════════════════════════════════════════════════
#  INTERACTIVE SESSION
# ═════════════════════════════════════════════════════════════

def browser_session(vps, machine, key_path):
    host_a = connect_to_machine(vps, machine, key_path)
    if not host_a:
        return

    name       = machine["name"]
    os_type    = machine.get("os", "Linux")
    is_windows = (os_type.lower() == "windows")
    local_dl   = CONFIG["LOCAL_DOWNLOAD_DIR"]
    os.makedirs(local_dl, exist_ok=True)

    try:
        sftp = host_a.open_sftp()
    except Exception as e:
        err(f"Failed to start SFTP session: {e}")
        host_a.close()
        return

    # Start path: share_root or root
    current_path = machine.get("share_root", "")
    if not current_path:
        current_path = "C:\\" if is_windows else "/"
    current_path = normalize_remote_path(current_path, is_windows)

    # Test path access
    entries, err_msg = list_sftp_dir(sftp, current_path)
    if entries is None:
        current_path = "C:\\" if is_windows else "/"
        entries, _ = list_sftp_dir(sftp, current_path)
        if entries is None:
            entries = []

    history = []

    print(f"\n  {BOLD}{GRN}COMMAND CHEATSHEET:{R}")
    print(f"  {CYN}<number>{R}       → Open folder or download file")
    print(f"  {CYN}0 / ..{R}         → Go up one level")
    print(f"  {CYN}d <num>{R}        → Download item by number")
    print(f"  {CYN}da{R}             → Download entire current directory")
    print(f"  {CYN}cd <path>{R}      → Navigate to exact path")
    print(f"  {CYN}exec <cmd>{R}     → Execute terminal command on remote machine")
    print(f"  {CYN}info{R}           → Show machine info")
    print(f"  {CYN}b / machines{R}   → Back to machines list")
    print(f"  {CYN}q{R}              → Disconnect\n")

    while True:
        entries, error = list_sftp_dir(sftp, current_path)
        if entries is None:
            err(f"Cannot access directory: {error}")
            if history:
                current_path = history.pop()
                continue
            else:
                current_path = "C:\\" if is_windows else "/"
                entries, _ = list_sftp_dir(sftp, current_path)
                if entries is None:
                    break

        display_listing(entries, current_path, name, os_type)
        print()

        try:
            raw = input(f"  {CYN}[{name}:{os_type}]{R}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        low = raw.lower()

        if low in ("q", "quit", "exit"):
            break
        if low in ("b", "back", "machines"):
            break
        if low == "pwd":
            print(f"  {current_path}")
            continue
        if low == "info":
            print()
            for k, v in machine.items():
                print(f"    {CYN}{k:<15}{R} {v}")
            print()
            continue
        if low.startswith("exec ") or low.startswith("sh "):
            cmd_to_run = raw.split(" ", 1)[1].strip()
            execute_remote_command(host_a, cmd_to_run, os_type)
            input(f"\n  Press {BOLD}Enter{R} to return to file browser... ")
            continue
        if low.startswith("cd "):
            target = raw[3:].strip()
            history.append(current_path)
            current_path = normalize_remote_path(target, is_windows)
            continue
        if raw in ("0", ".."):
            history.append(current_path)
            current_path = get_parent_dir(current_path, is_windows)
            continue
        if low == "da":
            ans = input(f"  Download ALL {len(entries)} items to {local_dl}? (y/n): ").lower()
            if ans == "y":
                for e in entries:
                    rp = join_remote_path(current_path, e["name"], is_windows)
                    download_item(host_a, sftp, rp, local_dl, is_dir=(e["type"]=="DIR"), is_windows=is_windows)
            continue
        if low.startswith("d "):
            parts = raw.split()
            if len(parts) == 2 and parts[1].isdigit():
                idx = int(parts[1]) - 1
                if 0 <= idx < len(entries):
                    e  = entries[idx]
                    rp = join_remote_path(current_path, e["name"], is_windows)
                    download_item(host_a, sftp, rp, local_dl, is_dir=(e["type"]=="DIR"), is_windows=is_windows)
                else:
                    warn(f"Invalid item number (1–{len(entries)}).")
            else:
                warn("Usage: d <number>  (e.g., d 2)")
            continue
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(entries):
                e = entries[idx]
                if e["type"] == "DIR":
                    history.append(current_path)
                    current_path = join_remote_path(current_path, e["name"], is_windows)
                else:
                    rp  = join_remote_path(current_path, e["name"], is_windows)
                    ans = input(f"  '{e['name']}' is a file ({fmt_size(e['size'])}). Download? (y/n): ").lower()
                    if ans == "y":
                        download_item(host_a, sftp, rp, local_dl, is_windows=is_windows)
            else:
                warn(f"Invalid item number (1–{len(entries)}).")
            continue

        warn(f"Unknown command '{raw}'. Type 'b' to go back, 'q' to quit, or 'exec <cmd>' to run commands.")

    try:
        sftp.close()
    except Exception:
        pass
    host_a.close()
    info(f"Disconnected from '{name}'.")


# ─── Machine Selection Loop ───────────────────────────────────
def machine_list_loop(vps, key_path):
    while True:
        info("Reading VPS registry for connected machines...")
        machines = fetch_registry(vps)
        display_machine_list(machines)

        if not machines:
            print(f"\n  {DIM}Press Enter to refresh, or 'q' to quit.{R}")
            try:
                raw = input(f"  {CYN}>{R} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if raw in ("q", "quit"):
                break
            continue

        print(f"\n  {BOLD}Select:{R} Enter {GRN}number{R} to connect  "
              f"  {GRN}r{R}=refresh  {GRN}q{R}=quit\n")
        try:
            raw = input(f"  {CYN}>{R} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw in ("q", "quit", "exit"):
            break
        if raw in ("r", "refresh", "ls", "list", "status", ""):
            continue

        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(machines):
                machine = machines[idx]
                if not machine.get("online"):
                    ans = input(f"  '{machine['name']}' appears offline. Try anyway? (y/n): ").lower()
                    if ans != "y":
                        continue
                browser_session(vps, machine, key_path)
            else:
                warn(f"Invalid machine number (1–{len(machines)}).")
        else:
            warn(f"Unknown command '{raw}'. Type the number (e.g. 1) to connect, 'r' to refresh, or 'q' to quit.")



# ═════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════

def main():
    print(BANNER)
    sep("═")
    info(f"Downloads folder: {CONFIG['LOCAL_DOWNLOAD_DIR']}")
    info(f"VPS Gateway:      {CONFIG['VPS_USER']}@{CONFIG['VPS_IP']}")
    sep("═")
    print()

    os.makedirs(CONFIG["LOCAL_DOWNLOAD_DIR"], exist_ok=True)

    vps = None
    try:
        vps = connect_vps()
        vps_run(vps, f"mkdir -p {CONFIG['VPS_REGISTRY_DIR']}")
        key_path = get_master_key_path(vps)
        if not key_path:
            warn("No master key found. Password will be prompted for connections.")
        machine_list_loop(vps, key_path)

    except paramiko.AuthenticationException:
        err("VPS authentication failed. Check credentials in CONFIG.")
    except Exception as e:
        err(f"Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        if vps:
            vps.close()
        info("Session finished. Goodbye.")


if __name__ == "__main__":
    main()
