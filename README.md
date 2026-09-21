# tunnel_system

A lightweight, automated, cross-platform Reverse SSH Tunneling and Remote Management System connecting Windows, macOS, and Linux machines through a central VPS bridge.

## 🚀 Features

- **Cross-Platform Support**: Works seamlessly on Windows, macOS, and Linux.
- **Auto-Discovery & Registry**: Machines running `host_a.py` automatically register with the central VPS registry.
- **Passwordless Connection**: Key-based authentication using master keys for secure, passwordless access.
- **Universal SFTP File Browser**: Interactive CLI to browse, search, and download files/folders.
- **Remote Command Execution**: Execute shell commands on connected machines from the controller.
- **Auto-Reconnection**: Resilient background tunnels with automatic heartbeat and reconnection.

## 📦 Files

- `host_a.py`: Agent script to run on any machine you want to access/share files from.
- `host_b.py`: Controller CLI to run on your local machine to discover, browse, and control Host A machines.
- `vps_bridge.py`: VPS bridge daemon and status dashboard.
- `setup_vps.py`: Setup script for configuring the VPS bridge.

## 🛠️ Getting Started

### 1. Source Machine (Host A)
```bash
python3 host_a.py
```

### 2. Controller Machine (Host B)
```bash
python3 host_b.py
```
