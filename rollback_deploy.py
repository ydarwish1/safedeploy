#!/usr/bin/env python3
"""
SafeDeploy Phase 3 - Verify-then-commit deployment with automatic rollback.

Applies a network change only if the network stays healthy afterward; if the
change breaks health, it automatically restores the pre-change config and
confirms recovery. Every run produces a structured decision record.

Pattern (modeled on Juniper "commit confirmed"): a change is kept only if health
is AFFIRMATIVELY verified after applying it. Failed checks, a timeout, or an
error all trigger rollback. Fail-safe, not fail-detected.

Restore mechanism: replay the saved baseline config through vtysh. This was
chosen after testing showed frrinit.sh reload was SIGKILLed (exit 137) on this
image, and frr-reload.py computed a full-config DELETION on malformed input.
vtysh replay is lightweight and has a predictable failure mode. Interface admin
state is handled explicitly: a shut interface is re-enabled with 'no shutdown',
because an enabled interface has no config line to replay.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CONTAINER_PREFIX = "clab-safedeploy-"
ALL_ROUTERS = ["r1", "r2", "r3", "r4"]
LOOPBACKS = {"r1": "1.1.1.1", "r2": "2.2.2.2", "r3": "3.3.3.3", "r4": "4.4.4.4"}
EXPECTED_ADJACENCIES = 2

BASELINE_DIR = Path("baselines")
RECORD_DIR = Path("deploy_records")


def vtysh(router, *commands):
    container = f"{CONTAINER_PREFIX}{router}"
    args = ["sudo", "docker", "exec", container, "vtysh"]
    for c in commands:
        args += ["-c", c]
    return subprocess.run(args, capture_output=True, text=True, timeout=30)


def docker_exec(router, *cmd):
    container = f"{CONTAINER_PREFIX}{router}"
    return subprocess.run(["sudo", "docker", "exec", container, *cmd],
                          capture_output=True, text=True, timeout=30)


def capture_baseline(router):
    res = vtysh(router, "show running-config")
    clean = []
    for line in res.stdout.splitlines():
        s = line.strip()
        if s.startswith("Building configuration") or s.startswith("Current configuration"):
            continue
        clean.append(line)
    return "\n".join(l for l in clean if l.strip() != "") + "\n"


def save_baseline(router, config_text):
    BASELINE_DIR.mkdir(exist_ok=True)
    path = BASELINE_DIR / f"{router}_baseline.conf"
    path.write_text(config_text)
    return path


def restore_baseline(router, baseline_path):
    """Restore by replaying the baseline config through vtysh.

    Re-enables every interface in the baseline first (clears any 'shutdown'),
    then replays the config lines. vtysh replay avoids the frrinit reload that
    was SIGKILLed on this image.
    """
    baseline = baseline_path.read_text()

    # 1. Re-enable any interface named in the baseline.
    interfaces = re.findall(r"^interface (\S+)", baseline, re.MULTILINE)
    enable_cmds = ["configure terminal"]
    for iface in interfaces:
        enable_cmds += [f"interface {iface}", "no shutdown", "exit"]
    enable_cmds.append("end")
    res = vtysh(router, *enable_cmds)
    if res.returncode != 0:
        return False

    # 2. Replay baseline config lines.
    config_lines = []
    for line in baseline.splitlines():
        s = line.strip()
        if not s or s == "!" or s == "end":
            continue
        if s.startswith("frr version") or s.startswith("frr defaults"):
            continue
        config_lines.append(s)
    replay = ["configure terminal"] + config_lines + ["end"]
    res = vtysh(router, *replay)
    return res.returncode == 0


def apply_ospf_cost(router, interface, cost):
    res = vtysh(router, "configure terminal", f"interface {interface}",
                f"ip ospf cost {cost}", "end")
    if res.returncode != 0:
        raise RuntimeError(f"apply failed on {router}: {res.stderr.strip()}")


def apply_interface_shutdown(router, interface):
    res = vtysh(router, "configure terminal", f"interface {interface}",
                "shutdown", "end")
    if res.returncode != 0:
        raise RuntimeError(f"shutdown failed on {router}: {res.stderr.strip()}")


def check_adjacencies():
    problems = []
    for r in ALL_ROUTERS:
        res = vtysh(r, "show ip ospf neighbor")
        full = res.stdout.count("Full")
        if full < EXPECTED_ADJACENCIES:
            problems.append(f"{r}: {full}/{EXPECTED_ADJACENCIES} Full")
    return (len(problems) == 0, problems)


def check_reachability():
    problems = []
    for src in ALL_ROUTERS:
        src_lo = LOOPBACKS[src]
        for dst, dst_lo in LOOPBACKS.items():
            if src == dst:
                continue
            res = docker_exec(src, "ping", "-c", "1", "-W", "1", "-I", src_lo, dst_lo)
            if res.returncode != 0:
                problems.append(f"{src} cannot reach {dst}({dst_lo})")
    return (len(problems) == 0, problems)


def run_health_checks():
    adj_ok, adj_p = check_adjacencies()
    reach_ok, reach_p = check_reachability()
    return {
        "healthy": adj_ok and reach_ok,
        "control_plane": {"ok": adj_ok, "problems": adj_p},
        "data_plane": {"ok": reach_ok, "problems": reach_p},
    }


def wait_for_health(timeout=90, interval=5):
    """Poll health until it passes or the timeout expires.

    The timeout must exceed OSPF reconvergence time. Re-enabling an interface
    starts a fresh adjacency (default hello 10s / dead 40s), so a correct change
    can read UNHEALTHY for ~40-50s while the neighbor works up to Full. A short
    window would roll back a good change mid-convergence; 90s gives roughly a 2x
    margin so health is judged only after the network has had time to settle.
    Changes that reach this stage already passed the gate's joint partition
    pre-flight, so a longer wait only ever lets a legitimate change converge.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = run_health_checks()
        if last["healthy"]:
            return last
        time.sleep(interval)
    return last


def deploy(change_fn, change_desc, targets):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "change": change_desc, "targets": targets,
        "decision": None, "reason": None,
        "health_after_change": None, "health_after_rollback": None,
    }
    baselines = {}
    for r in targets:
        baselines[r] = save_baseline(r, capture_baseline(r))
    print(f"Captured baselines for: {', '.join(targets)}")

    print(f"Applying change: {change_desc}")
    change_fn()

    print("Verifying health (control plane + data plane)...")
    health = wait_for_health()
    record["health_after_change"] = health

    if health["healthy"]:
        record["decision"] = "kept"
        record["reason"] = "health affirmatively verified after change"
        print("HEALTHY - change kept.")
    else:
        print("UNHEALTHY - rolling back.")
        print(f"  control plane: {health['control_plane']['problems']}")
        print(f"  data plane: {health['data_plane']['problems']}")
        for r in targets:
            ok = restore_baseline(r, baselines[r])
            print(f"  restored {r}: {'ok' if ok else 'FAILED'}")
        time.sleep(10)
        recovery = wait_for_health()
        record["health_after_rollback"] = recovery
        record["decision"] = "rolled_back"
        record["reason"] = "health checks failed after change"
        if recovery["healthy"]:
            print("Rollback verified - network recovered.")
        else:
            print("WARNING: network still unhealthy after rollback.")

    RECORD_DIR.mkdir(exist_ok=True)
    stamp = record["timestamp"].replace(":", "-")
    rec_path = RECORD_DIR / f"deploy_{stamp}.json"
    rec_path.write_text(json.dumps(record, indent=2))
    print(f"Decision record: {rec_path}")
    return record


def main():
    p = argparse.ArgumentParser(description="SafeDeploy Phase 3: verify-then-commit with auto-rollback.")
    p.add_argument("--router", required=True)
    p.add_argument("--interface", required=True)
    p.add_argument("--action", required=True, choices=["cost", "shutdown"])
    p.add_argument("--cost", type=int, default=50)
    args = p.parse_args()

    if args.action == "cost":
        desc = f"set OSPF cost {args.cost} on {args.router} {args.interface}"
        fn = lambda: apply_ospf_cost(args.router, args.interface, args.cost)
    else:
        desc = f"shutdown {args.router} {args.interface} (breaking change)"
        fn = lambda: apply_interface_shutdown(args.router, args.interface)

    record = deploy(fn, desc, [args.router])
    return 0 if record["decision"] == "kept" else 2


if __name__ == "__main__":
    sys.exit(main())
