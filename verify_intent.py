#!/usr/bin/env python3
"""
SafeDeploy Phase 8 - Intent verification.

The inversion that ties the project together: instead of "apply a change and
check some things," this declares the network's DESIRED STATE in intent.yml and
proves whether live reality conforms to it. This is intent-based networking in
miniature - the same model behind tools like Cisco NSO and Juniper Apstra.

verify_intent.py reads intent.yml and checks every assertion against the live
lab:
  - control_plane: each router holds at least min_neighbors Full OSPF adjacencies
  - reachability:  each src loopback reaches each dst loopback, within max_hops
  - path:          specific flows take exactly the expected forwarding path

It prints PASS/FAIL per assertion with evidence, and exits non-zero if ANY intent
is violated - so it can serve as the single "is the network in its intended
state?" gate for the Phase 3 deploy pipeline.
"""

import subprocess
import sys
import re
import yaml

CONTAINER_PREFIX = "clab-safedeploy-"
ROUTERS = ["r1", "r2", "r3", "r4"]
LOOPBACKS = {"r1": "1.1.1.1", "r2": "2.2.2.2", "r3": "3.3.3.3", "r4": "4.4.4.4"}
IFACE_IPS = {
    "10.0.12.1": "r1", "10.0.41.2": "r1",
    "10.0.12.2": "r2", "10.0.23.1": "r2",
    "10.0.23.2": "r3", "10.0.34.1": "r3",
    "10.0.34.2": "r4", "10.0.41.1": "r4",
}


def vtysh(router, command):
    res = subprocess.run(
        ["sudo", "docker", "exec", f"{CONTAINER_PREFIX}{router}", "vtysh",
         "-c", command],
        capture_output=True, text=True, timeout=30,
    )
    return res.stdout


def docker_exec(router, *cmd):
    return subprocess.run(
        ["sudo", "docker", "exec", f"{CONTAINER_PREFIX}{router}", *cmd],
        capture_output=True, text=True, timeout=60,
    )


# --- live state readers (reused from Phase 5 logic) ----------------------
def full_neighbor_count(router):
    out = vtysh(router, "show ip ospf neighbor")
    return sum(1 for line in out.splitlines() if "Full" in line)


def next_hops(router, dst_ip):
    out = vtysh(router, f"show ip route {dst_ip}")
    if f"{dst_ip}/32 is directly connected" in out or "Loopback" in out:
        return ["LOCAL"]
    hops = []
    for line in out.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+), via", line)
        if m:
            nh = IFACE_IPS.get(m.group(1))
            if nh and nh not in hops:
                hops.append(nh)
    if not hops and "directly connected" in out:
        return ["LOCAL"]
    return hops


def fib_paths(src, dst):
    dst_ip = LOOPBACKS[dst]
    results = []

    def walk(current, path):
        if current == dst:
            results.append(path)
            return
        if len(path) > len(ROUTERS) + 1:
            results.append(path + ["LOOP?"])
            return
        hops = next_hops(current, dst_ip)
        if hops == ["LOCAL"]:
            results.append(path)
            return
        if not hops:
            results.append(path + ["UNREACHABLE"])
            return
        for nh in hops:
            if nh in path:
                results.append(path + [nh, "LOOP?"])
                continue
            walk(nh, path + [nh])

    walk(src, [src])
    return results


def pings(src, dst):
    """True if src loopback can ping dst loopback."""
    src_ip = LOOPBACKS[src]
    dst_ip = LOOPBACKS[dst]
    res = docker_exec(src, "ping", "-c", "2", "-W", "1", "-I", src_ip, dst_ip)
    return res.returncode == 0


# --- intent checks -------------------------------------------------------
class Result:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, ok, label, evidence=""):
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {label}")
        if evidence:
            print(f"         {evidence}")
        if ok:
            self.passed += 1
        else:
            self.failed += 1


def verify_control_plane(intent, r):
    section = intent.get("control_plane", {})
    minn = section.get("min_neighbors", {})
    if not minn:
        return
    print("control_plane:")
    for router, required in minn.items():
        actual = full_neighbor_count(router)
        r.check(actual >= required,
                f"{router} has >= {required} Full neighbors",
                f"actual Full neighbors: {actual}")


def verify_reachability(intent, r):
    items = intent.get("reachability", [])
    if not items:
        return
    print("reachability:")
    for item in items:
        src, dst = item["src"], item["dst"]
        max_hops = item.get("max_hops")
        reachable = pings(src, dst)
        paths = fib_paths(src, dst)
        # hop count = routers traversed beyond the source on the shortest path
        good_paths = [p for p in paths if p and p[-1] == dst]
        if not reachable or not good_paths:
            r.check(False, f"{src} -> {dst} reachable",
                    f"ping ok={reachable}, fib paths={paths}")
            continue
        shortest = min(len(p) for p in good_paths)
        within = (max_hops is None) or (shortest <= max_hops)
        r.check(within,
                f"{src} -> {dst} reachable within {max_hops} hops",
                f"ping ok, shortest path = {shortest} routers")


def verify_path(intent, r):
    items = intent.get("path", [])
    if not items:
        return
    print("path:")
    for item in items:
        src, dst = item["src"], item["dst"]
        expect = item["expect"]
        paths = fib_paths(src, dst)
        match = any(p == expect for p in paths)
        r.check(match,
                f"{src} -> {dst} path is {' -> '.join(expect)}",
                f"actual fib paths: {paths}")


def main():
    try:
        with open("intent.yml") as f:
            intent = yaml.safe_load(f)
    except FileNotFoundError:
        print("intent.yml not found")
        return 2

    print("=== Verifying network against declared intent (intent.yml) ===\n")
    r = Result()
    verify_control_plane(intent, r)
    verify_reachability(intent, r)
    verify_path(intent, r)

    total = r.passed + r.failed
    print(f"\n=== {r.passed}/{total} intent checks passed ===")
    if r.failed:
        print("INTENT VIOLATED")
        return 1
    print("INTENT SATISFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
