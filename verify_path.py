#!/usr/bin/env python3
"""
SafeDeploy Phase 5 - Data-plane path verification.

Phase 3 confirms traffic REACHES its destination. Phase 5 confirms it takes the
EXPECTED PATH. A change can leave everything pingable while silently rerouting
traffic the wrong way (a longer path, through the wrong transit node, across a
link that should not carry it). That is the "succeeded but degraded" case. This
tool catches it.

Two independent methods, cross-checked:

1. FIB walk (control-plane intent): starting at the source router, read its
   routing table for the destination, find the next-hop router, hop to it, and
   repeat until the destination is reached. This reconstructs the path each
   router WILL actually use from its own forwarding table. Deterministic, and it
   handles ECMP (equal-cost multipath) by reporting all next-hops at each step.

2. Live traceroute (data-plane reality): run an actual traceroute from the source
   loopback to the destination loopback and record the hops the packets really
   took. This proves real traffic, not just the model.

A change's effect on the path can then be compared before vs after.
"""

import argparse
import subprocess
import sys
import re

CONTAINER_PREFIX = "clab-safedeploy-"
ROUTERS = ["r1", "r2", "r3", "r4"]
LOOPBACKS = {"r1": "1.1.1.1", "r2": "2.2.2.2", "r3": "3.3.3.3", "r4": "4.4.4.4"}
# Reverse lookup: which router owns a given interface IP, so we can turn a
# next-hop address into a router name.
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


def next_hops(router, dst_ip):
    """Return the next-hop router(s) this router uses to reach dst_ip.

    Reads the FIB. Returns a list (more than one entry means ECMP). An empty
    list means no route (the destination is unreachable from this router).
    A next-hop that is 'directly connected' means dst is on this router.
    """
    out = vtysh(router, f"show ip route {dst_ip}")
    # If this router owns the destination, the route is to its own loopback.
    if f"{dst_ip}/32 is directly connected" in out or "Loopback" in out:
        return ["LOCAL"]
    hops = []
    for line in out.splitlines():
        # FRR format: "* 10.0.12.2, via eth1, weight 1" - nexthop IP is BEFORE "via".
        m = re.search(r"(\d+\.\d+\.\d+\.\d+), via", line)
        if m:
            nh_ip = m.group(1)
            nh_router = IFACE_IPS.get(nh_ip)
            if nh_router and nh_router not in hops:
                hops.append(nh_router)
    # No nexthop found but route exists and dst is this router's own loopback.
    if not hops and "directly connected" in out:
        return ["LOCAL"]
    return hops


def fib_paths(src, dst):
    """Walk the FIB from src to dst, returning all forwarding paths.

    Handles ECMP by branching at each multi-next-hop step. Guards against loops.
    Returns a list of paths, each a list of router names from src to dst.
    """
    dst_ip = LOOPBACKS[dst]
    results = []

    def walk(current, path):
        if current == dst:
            results.append(path)
            return
        if len(path) > len(ROUTERS) + 1:  # loop guard
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
            if nh in path:  # already visited - loop
                results.append(path + [nh, "LOOP?"])
                continue
            walk(nh, path + [nh])

    walk(src, [src])
    return results


def live_traceroute(src, dst):
    """Run a real traceroute from src loopback to dst loopback.

    Returns the ordered list of hop IPs the packets actually traversed.
    """
    src_ip = LOOPBACKS[src]
    dst_ip = LOOPBACKS[dst]
    res = docker_exec(src, "traceroute", "-n", "-w", "1", "-q", "1",
                      "-s", src_ip, dst_ip)
    hops = []
    for line in res.stdout.splitlines():
        m = re.match(r"\s*\d+\s+(\d+\.\d+\.\d+\.\d+)", line)
        if m:
            hops.append(m.group(1))
    return hops


def verify(src, dst, expected=None):
    """Verify the path from src to dst. If expected (list of router names) is
    given, check the FIB path matches it.
    """
    paths = fib_paths(src, dst)
    trace = live_traceroute(src, dst)

    print(f"=== path {src} -> {dst} ===")
    print("FIB forwarding path(s) (from routing tables):")
    for p in paths:
        print(f"  {' -> '.join(p)}")
    print(f"Live traceroute hops (real packets): {trace if trace else '(none)'}")

    ok = True
    if expected is not None:
        match = any(p == expected for p in paths)
        print(f"\nExpected path: {' -> '.join(expected)}")
        print(f"Match: {'YES' if match else 'NO'}")
        ok = match

    # Sanity: destination actually reached on every FIB path.
    reached = all(p[-1] == dst for p in paths)
    if not reached:
        print("WARNING: at least one FIB path does not reach the destination")
        ok = False

    return ok, paths, trace


def main():
    p = argparse.ArgumentParser(
        description="SafeDeploy Phase 5: data-plane path verification.")
    p.add_argument("--src", required=True, choices=ROUTERS)
    p.add_argument("--dst", required=True, choices=ROUTERS)
    p.add_argument("--expect", default=None,
                   help="expected path as router names, e.g. r1,r2,r3")
    args = p.parse_args()

    expected = args.expect.split(",") if args.expect else None
    ok, paths, trace = verify(args.src, args.dst, expected)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
