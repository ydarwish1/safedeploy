#!/usr/bin/env python3
"""
SafeDeploy Phase 1 — Network State Snapshot

Reads the current state of every router in the lab and saves it as a
timestamped JSON snapshot. This is the "known-good" baseline that later
phases compare against and roll back to.

Strictly READ-ONLY: issues only `show` commands, never enters config mode.

Connection method is pluggable. Today it uses `docker exec` into the
containerlab nodes (reliable for this lab). A production deployment would
swap in an SSH/Netmiko collector implementing the same interface — the rest
of the tool would not change.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Lab definition -------------------------------------------------------
# The routers we snapshot, and the container name prefix containerlab uses.
ROUTERS = ["r1", "r2", "r3", "r4"]
CONTAINER_PREFIX = "clab-safedeploy-"

# The read-only commands collected per router. Keys become the snapshot's
# field names; values are the vtysh commands run to populate them.
COMMANDS = {
    "running_config": "show running-config",
    "ospf_neighbors": "show ip ospf neighbor",
    "ospf_interfaces": "show ip ospf interface brief",
    "routes": "show ip route",
    "interfaces": "show interface brief",
}

# Safety: every command must be read-only. This mirrors the Layer 1
# guarantee — the snapshotter can never change a device.
READ_ONLY_PREFIXES = ("show ",)

SNAPSHOT_DIR = Path("snapshots")


# --- Collection -----------------------------------------------------------
def run_vtysh(router: str, command: str) -> str:
    """Run a single read-only vtysh command inside a router container.

    Returns the raw command output as text. Raises on a non-read-only
    command (defense in depth) or if the container call fails.
    """
    if not command.startswith(READ_ONLY_PREFIXES):
        raise ValueError(f"refused non-read-only command: {command!r}")

    container = f"{CONTAINER_PREFIX}{router}"
    result = subprocess.run(
        ["sudo", "docker", "exec", container, "vtysh", "-c", command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{container} `{command}` failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def collect_router(router: str) -> dict:
    """Collect all configured commands for one router into a dict.

    Per-command failures are captured in an `errors` list rather than
    aborting the whole snapshot — a partial snapshot with recorded errors
    is more useful than no snapshot.
    """
    record = {"router": router, "reachable": True, "state": {}, "errors": []}
    for field, command in COMMANDS.items():
        try:
            record["state"][field] = run_vtysh(router, command)
        except Exception as exc:
            record["reachable"] = False
            record["errors"].append(f"{field}: {type(exc).__name__}: {exc}")
    return record


# --- Snapshot orchestration ----------------------------------------------
def take_snapshot() -> dict:
    """Collect every router's state into one timestamped snapshot object."""
    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "captured_at": timestamp,
        "routers": [collect_router(r) for r in ROUTERS],
    }
    snapshot["summary"] = {
        "router_count": len(ROUTERS),
        "reachable": sum(1 for r in snapshot["routers"] if r["reachable"]),
        "with_errors": sum(1 for r in snapshot["routers"] if r["errors"]),
    }
    return snapshot


def save_snapshot(snapshot: dict) -> Path:
    """Write the snapshot to a timestamped JSON file and update 'latest'."""
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    stamp = snapshot["captured_at"].replace(":", "-")
    path = SNAPSHOT_DIR / f"snapshot_{stamp}.json"
    path.write_text(json.dumps(snapshot, indent=2))

    # A stable pointer to the most recent snapshot, for later phases.
    latest = SNAPSHOT_DIR / "latest.json"
    latest.write_text(json.dumps(snapshot, indent=2))
    return path


# --- Entry point ----------------------------------------------------------
def main() -> int:
    print("SafeDeploy Phase 1 — capturing network snapshot...")
    snapshot = take_snapshot()
    path = save_snapshot(snapshot)

    s = snapshot["summary"]
    print(f"Captured {s['router_count']} routers "
          f"({s['reachable']} reachable, {s['with_errors']} with errors)")
    print(f"Saved: {path}")
    print(f"Latest: {SNAPSHOT_DIR / 'latest.json'}")

    # Non-zero exit if anything was unreachable, so this can gate later steps.
    return 0 if s["reachable"] == s["router_count"] else 1


if __name__ == "__main__":
    sys.exit(main())
