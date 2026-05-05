Title: Scripted Syncthing: Managing Bidirectional Sync Between Mac and Linux with a YAML Config
Date: 2026-05-12
Category: How-to
Tags: syncthing, python, yaml, mac, linux, homelab, file-sync, docker, automation
Slug: syncthing-yaml-config-mac-linux-bidirectional-sync
Summary: Syncthing's GUI works for a couple of folders. When you have a dozen folder pairs with different sync directions — some Mac to server, some server to Mac, some bidirectional — the GUI becomes a liability. I built a Python script that reads a YAML config and configures both Syncthing instances via their REST APIs.

---

[Syncthing](https://syncthing.net) is the right tool for keeping files synchronized between machines. It's open source, encrypted, peer-to-peer, and doesn't route your data through anyone's cloud. I've been running it in Docker on my home server (Apollo) and natively on my Mac.

The problem isn't Syncthing. The problem is managing it.

I have a dozen folder pairs with different sync directions:

- **Drone footage** syncs from Mac → Server (I shoot, I want it backed up immediately)
- **Downloads** sync from Server → Mac (media I want local access to)
- **Photos backup** is bidirectional (phone → both, Mac → both)
- **Project repos** are Mac → Server (the server is an additional copy, not the primary)

Configuring this in Syncthing's web UI — on two devices — is a 45-minute exercise in clicking through the same modal twelve times. If I change my mind about a folder, I do it again.

I automated it.

---

## The Architecture

The core insight is that Syncthing has a REST API. Everything you can do in the GUI, you can do via `curl` (or Python `requests`). The sync configuration lives in a YAML file that I commit to my homelab-docs repository. A Python script reads the YAML and configures both Syncthing instances via their APIs.

```
sync_config.yaml         (source of truth)
       ↓
syncthing_setup.py       (reads config, calls both APIs)
       ↓
┌──────────────┐    ┌──────────────────┐
│  Mac          │    │  Apollo (Server)  │
│  Syncthing    │◄──►│  Syncthing        │
│  :8385        │    │  :8384            │
└──────────────┘    └──────────────────┘
```

---

## The Config File

`config/sync_config.yaml`:

```yaml
# Syncthing Sync Configuration
# direction options:
#   mac_to_server  → Mac sends, Server receives (sendonly/receiveonly)
#   server_to_mac  → Server sends, Mac receives (sendonly/receiveonly)
#   both           → Full bidirectional (sendreceive on both sides)

devices:
  mac:
    syncthing_url: "http://localhost:8385"
    api_key: "${MAC_SYNCTHING_API_KEY}"
    device_id: "${MAC_SYNCTHING_DEVICE_ID}"
  server:
    syncthing_url: "http://apollo.local:8384"
    api_key: "${SERVER_SYNCTHING_API_KEY}"
    device_id: "${SERVER_SYNCTHING_DEVICE_ID}"

folders:
  - id: drone-ecosystem
    label: "DroneEcosystem"
    direction: mac_to_server
    mac_path: "/Volumes/seagate_8tb/DroneEcosystem"
    server_path: "/data/DroneEcosystem"

  - id: unsorted2
    label: "Unsorted Downloads"
    direction: server_to_mac
    mac_path: "/Volumes/seagate_8tb/unsorted2"
    server_path: "/data/unsorted2"

  - id: phone-backup
    label: "Phone Backup"
    direction: both
    mac_path: "/Volumes/seagate_8tb/phone_backup"
    server_path: "/data/phone_backup"

  - id: projects-sync
    label: "Active Projects"
    direction: mac_to_server
    mac_path: "~/Projects/active"
    server_path: "/data/sync/projects"
```

API keys and device IDs are environment variables — never hardcoded. The `.env.example` in the repo shows what to populate.

---

## The Script

`scripts/syncthing_setup.py`:

```python
"""
Configure Syncthing bidirectional sync from YAML spec.

For each folder in the config, creates the folder on both devices
and adds the counterpart device as a sharing partner, with the
correct send/receive mode for each side.
"""
import os
import sys
import yaml
import requests
from pathlib import Path
from typing import Literal

# Folder type mappings per direction per side
FOLDER_TYPES = {
    "mac_to_server": {"mac": "sendonly", "server": "receiveonly"},
    "server_to_mac": {"mac": "receiveonly", "server": "sendonly"},
    "both":          {"mac": "sendreceive", "server": "sendreceive"},
}

def expand_env(config: dict) -> dict:
    """Recursively expand ${VAR} references in config values."""
    if isinstance(config, dict):
        return {k: expand_env(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [expand_env(v) for v in config]
    elif isinstance(config, str) and config.startswith("${") and config.endswith("}"):
        var_name = config[2:-1]
        value = os.environ.get(var_name)
        if value is None:
            raise ValueError(f"Required environment variable {var_name} not set")
        return value
    return config


class SyncthingClient:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip("/")
        self.headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    
    def get_config(self) -> dict:
        r = requests.get(f"{self.url}/rest/config", headers=self.headers)
        r.raise_for_status()
        return r.json()
    
    def put_config(self, config: dict) -> None:
        r = requests.put(
            f"{self.url}/rest/config",
            headers=self.headers,
            json=config,
        )
        r.raise_for_status()
    
    def ensure_device(self, config: dict, device_id: str, device_name: str) -> dict:
        """Add device to config if not already present."""
        existing_ids = {d["deviceID"] for d in config.get("devices", [])}
        if device_id not in existing_ids:
            config.setdefault("devices", []).append({
                "deviceID": device_id,
                "name": device_name,
                "autoAcceptFolders": False,
            })
        return config
    
    def ensure_folder(
        self,
        config: dict,
        folder_id: str,
        folder_label: str,
        folder_path: str,
        folder_type: str,
        peer_device_id: str,
    ) -> dict:
        """Add or update folder in config."""
        folder_path_expanded = str(Path(folder_path).expanduser())
        
        # Find existing folder or create new
        existing = next(
            (f for f in config.get("folders", []) if f["id"] == folder_id),
            None,
        )
        
        if existing is None:
            config.setdefault("folders", []).append({
                "id": folder_id,
                "label": folder_label,
                "path": folder_path_expanded,
                "type": folder_type,
                "devices": [{"deviceID": peer_device_id}],
            })
        else:
            existing["type"] = folder_type
            existing["path"] = folder_path_expanded
            # Ensure peer device is in sharing list
            peer_ids = {d["deviceID"] for d in existing.get("devices", [])}
            if peer_device_id not in peer_ids:
                existing.setdefault("devices", []).append(
                    {"deviceID": peer_device_id}
                )
        
        return config


def configure_from_yaml(config_path: str) -> None:
    with open(config_path) as f:
        raw_config = yaml.safe_load(f)
    
    config = expand_env(raw_config)
    
    mac_cfg = config["devices"]["mac"]
    srv_cfg = config["devices"]["server"]
    
    mac = SyncthingClient(mac_cfg["syncthing_url"], mac_cfg["api_key"])
    server = SyncthingClient(srv_cfg["syncthing_url"], srv_cfg["api_key"])
    
    mac_config = mac.get_config()
    srv_config = server.get_config()
    
    # Ensure each knows about the other
    mac_config = mac.ensure_device(mac_config, srv_cfg["device_id"], "Apollo Server")
    srv_config = server.ensure_device(srv_config, mac_cfg["device_id"], "Mac")
    
    for folder in config["folders"]:
        types = FOLDER_TYPES[folder["direction"]]
        
        # Configure on Mac
        mac_config = mac.ensure_folder(
            config=mac_config,
            folder_id=folder["id"],
            folder_label=folder["label"],
            folder_path=folder["mac_path"],
            folder_type=types["mac"],
            peer_device_id=srv_cfg["device_id"],
        )
        
        # Configure on Server
        srv_config = server.ensure_folder(
            config=srv_config,
            folder_id=folder["id"],
            folder_label=folder["label"],
            folder_path=folder["server_path"],
            folder_type=types["server"],
            peer_device_id=mac_cfg["device_id"],
        )
        
        print(f"✓ {folder['id']} ({folder['direction']}): "
              f"mac={types['mac']}, server={types['server']}")
    
    mac.put_config(mac_config)
    server.put_config(srv_config)
    print("\nConfigs applied. Syncthing will reload automatically.")


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/sync_config.yaml"
    configure_from_yaml(config_path)
```

---

## Usage

```bash
# Set environment variables
export MAC_SYNCTHING_API_KEY="your-mac-api-key"
export SERVER_SYNCTHING_API_KEY="your-server-api-key"
export MAC_SYNCTHING_DEVICE_ID="XXXX-XXXX-XXXX-XXXX-..."
export SERVER_SYNCTHING_DEVICE_ID="YYYY-YYYY-YYYY-YYYY-..."

# Or use a .env file with python-dotenv
source .env

# Run configuration
python3 scripts/syncthing_setup.py config/sync_config.yaml
```

Output:
```
✓ drone-ecosystem (mac_to_server): mac=sendonly, server=receiveonly
✓ unsorted2 (server_to_mac): mac=receiveonly, server=sendonly
✓ phone-backup (both): mac=sendreceive, server=sendreceive
✓ projects-sync (mac_to_server): mac=sendonly, server=receiveonly

Configs applied. Syncthing will reload automatically.
```

---

## The Gotcha: Docker Path Mapping

If Syncthing on the server is running in Docker, folder paths inside the container are different from paths on the host.

My Docker Compose config:

```yaml
syncthing:
  image: lscr.io/linuxserver/syncthing:v2.0.14-ls208
  volumes:
    - /home/kivan/appdata/syncthing:/config
    - /mnt/unified:/data          # ← host path /mnt/unified = container path /data
```

So `server_path` in my YAML config uses the container path (`/data/DroneEcosystem`), not the host path (`/mnt/unified/DroneEcosystem`). If you use host paths, Syncthing's folder won't find the directory.

This caught me. The error was:
```
Failed to create folder root directory (folder.id=drone-ecosystem 
error="folder path missing")
```

Fix: update all `server_path` values to use the container-internal path. In my case, prefix `/data/` instead of `/mnt/unified/`.

---

## Adding a New Folder

With the GUI approach, adding a folder requires:
1. Open Syncthing UI on Mac
2. Add folder, configure path, set type, add peer device
3. Open Syncthing UI on server
4. Accept incoming folder share (or add manually)
5. Configure server-side path and type

With the script:

```yaml
# Add to sync_config.yaml
- id: new-project
  label: "New Project"
  direction: mac_to_server
  mac_path: "~/Projects/new-project"
  server_path: "/data/sync/new-project"
```

```bash
python3 scripts/syncthing_setup.py config/sync_config.yaml
```

Done.

---

## Why This Matters Beyond Convenience

The config file is the source of truth. It's version-controlled. When I rebuild either machine, I clone the repo and run the script — both Syncthing instances are configured identically to before. No manual clicking, no forgotten folder pairs, no sync direction inconsistencies.

This is the same principle behind Infrastructure as Code, applied to a personal file sync setup. The configuration is declarative, auditable, and reproducible.

It's also a useful exercise in Syncthing's REST API, which is well-documented but underutilized. If you can configure Syncthing via script, you can automate folder creation based on project status, build sync health monitoring into your homelab dashboard, or trigger sync validation as part of a backup verification workflow.

---

*Full code in the `homelab-docs` repository. The script currently requires manual API key setup; adding support for reading from Syncthing's config database directly is on the roadmap.*
