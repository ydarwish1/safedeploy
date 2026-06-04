#!/usr/bin/env python3
"""
SafeDeploy Phase 4 - Offline pre-flight change validation.

Predicts whether a proposed change is safe BEFORE it touches the live network,
by building a graph model of the topology from captured config and simulating
the change against it. This is the pre-flight gate that runs ahead of the
Phase 3 apply/verify/rollback pipeline: if pre-flight says a change would
partition the network, you never apply it at all.

This is a self-built model rather than Batfish: Batfish parses FRR via its
Cumulus vendor model, which expects a two-file layout this pure-FRR lab does not
produce (see docs/PHASE4-LOG.md). Building the check directly keeps fidelity to
the actual configs and integrates cleanly with the existing tooling.

Scope (honest): this models L3 topology and OSPF reachability as a graph. It
predicts connectivity/partition effects of link or cost changes. It does NOT
model full OSPF timer/LSA behavior - that is what the live-lab verification in
Phase 3 is for. Pre-flight catches obviously-unsafe changes cheaply; Phase 3
verifies real behavior authoritatively.
"""

import argparse
import subprocess
import sys
import re
from itertools import combinations

CONTAINER_PREFIX = "clab-safedeploy-"
ROUTERS = ["r1", "r2", "r3", "r4"]
LOOPBACKS = {"r1": "1.1.1.1", "r2": "2.2.2.2", "r3": "3.3.3.3", "r4": "4.4.4.4"}


# --- build topology model from live config -------------------------------
def get_config(router):
    res = subprocess.run(
        ["sudo", "docker", "exec", f"{CONTAINER_PREFIX}{router}", "vtysh",
         "-c", "show running-config"],
        capture_output=True, text=True, timeout=30,
    )
    return res.stdout


def get_interface_subnets(router):
    """Return {interface: (ip, prefix)} for OSPF-enabled interfaces.

    We only count interfaces that are both addressed and in OSPF, because an
    interface without OSPF does not form an adjacency / carry the IGP.
    """
    cfg = get_config(router)
    subnets = {}
    current_if = None
    has_ip = {}
    has_ospf = {}
    ip_of = {}
    for line in cfg.splitlines():
        s = line.strip()
        m = re.match(r"interface (\S+)", s)
        if m:
            current_if = m.group(1)
            continue
        if current_if:
            mip = re.match(r"ip address (\d+\.\d+\.\d+\.\d+)/(\d+)", s)
            if mip:
                ip_of[current_if] = (mip.group(1), int(mip.group(2)))
                has_ip[current_if] = True
            if s == "ip ospf area 0":
                has_ospf[current_if] = True
            if s == "shutdown":
                has_ospf[current_if] = False  # shut iface carries nothing
    for iface, ok in has_ospf.items():
        if ok and iface in ip_of:
            subnets[iface] = ip_of[iface]
    return subnets


def network_addr(ip, prefix):
    """Return the network address for an ip/prefix (for matching link ends)."""
    octets = [int(x) for x in ip.split(".")]
    bits = (octets[0] << 24) + (octets[1] << 16) + (octets[2] << 8) + octets[3]
    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    net = bits & mask
    return f"{(net>>24)&255}.{(net>>16)&255}.{(net>>8)&255}.{net&255}/{prefix}"


def build_topology():
    """Build an adjacency graph: two routers are linked if they share an OSPF
    subnet (i.e. an OSPF-enabled interface on the same /30)."""
    router_subnets = {}
    for r in ROUTERS:
        subs = get_interface_subnets(r)
        router_subnets[r] = {network_addr(ip, p) for (ip, p) in subs.values()}

    graph = {r: set() for r in ROUTERS}
    for a, b in combinations(ROUTERS, 2):
        if router_subnets[a] & router_subnets[b]:  # shared OSPF subnet
            graph[a].add(b)
            graph[b].add(a)
    return graph


# --- connectivity analysis on the model ----------------------------------
def is_connected(graph):
    """Is every router reachable from r1 (is the graph one component)?"""
    if not graph:
        return False
    start = next(iter(graph))
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nbr in graph[node]:
            if nbr not in seen:
                seen.add(nbr)
                stack.append(nbr)
    return len(seen) == len(graph)


def min_adjacencies(graph):
    """Fewest neighbors any router has (a node with 0 is isolated)."""
    return min((len(v) for v in graph.values()), default=0)


# --- simulate a proposed change on the model ------------------------------
def simulate_link_down(graph, router, neighbor):
    """Return a copy of the graph with the router<->neighbor link removed."""
    g = {k: set(v) for k, v in graph.items()}
    g[router].discard(neighbor)
    g[neighbor].discard(router)
    return g


def neighbor_on_interface(router, interface):
    """Find which router sits on the other end of router's interface."""
    subs = get_interface_subnets(router)
    if interface not in subs:
        return None
    ip, prefix = subs[interface]
    my_net = network_addr(ip, prefix)
    for other in ROUTERS:
        if other == router:
            continue
        for (oip, op) in get_interface_subnets(other).values():
            if network_addr(oip, op) == my_net:
                return other
    return None


# --- pre-flight check -----------------------------------------------------
def preflight(action, router, interface):
    """Predict whether a change is safe. Returns (safe: bool, report: dict)."""
    base = build_topology()
    report = {
        "action": action, "router": router, "interface": interface,
        "baseline_connected": is_connected(base),
        "baseline_min_adjacencies": min_adjacencies(base),
        "predicted_connected": None,
        "predicted_min_adjacencies": None,
        "verdict": None, "reasons": [],
    }

    if action == "shutdown":
        nbr = neighbor_on_interface(router, interface)
        if nbr is None:
            report["verdict"] = "WARN"
            report["reasons"].append(
                f"{router} {interface} has no modeled OSPF neighbor; "
                "change may be a no-op or interface is non-OSPF")
            return (True, report)
        after = simulate_link_down(base, router, nbr)
        report["predicted_connected"] = is_connected(after)
        report["predicted_min_adjacencies"] = min_adjacencies(after)
        if not report["predicted_connected"]:
            report["verdict"] = "UNSAFE"
            report["reasons"].append(
                f"shutting {router} {interface} (link to {nbr}) PARTITIONS "
                "the network - some routers become unreachable")
            return (False, report)
        if report["predicted_min_adjacencies"] < 1:
            report["verdict"] = "UNSAFE"
            report["reasons"].append("a router would be left with 0 adjacencies")
            return (False, report)
        report["verdict"] = "SAFE"
        report["reasons"].append(
            f"link {router}-{nbr} can be removed; network stays connected "
            f"via redundant ring paths (min adjacencies "
            f"{report['predicted_min_adjacencies']})")
        return (True, report)

    elif action == "cost":
        # A cost change never removes a link or partitions the topology; it
        # only shifts path preference. Always topologically safe.
        report["predicted_connected"] = report["baseline_connected"]
        report["predicted_min_adjacencies"] = report["baseline_min_adjacencies"]
        report["verdict"] = "SAFE"
        report["reasons"].append(
            "cost change shifts path preference only; cannot partition the "
            "topology")
        return (True, report)

    report["verdict"] = "UNKNOWN"
    report["reasons"].append(f"no pre-flight model for action '{action}'")
    return (False, report)


def main():
    p = argparse.ArgumentParser(
        description="SafeDeploy Phase 4: offline pre-flight change validation.")
    p.add_argument("--router", required=True)
    p.add_argument("--interface", required=True)
    p.add_argument("--action", required=True, choices=["cost", "shutdown"])
    args = p.parse_args()

    print(f"Pre-flight: {args.action} on {args.router} {args.interface}")
    safe, report = preflight(args.action, args.router, args.interface)

    print(f"\n  baseline connected:        {report['baseline_connected']}")
    print(f"  baseline min adjacencies:  {report['baseline_min_adjacencies']}")
    if report["predicted_connected"] is not None:
        print(f"  predicted connected:       {report['predicted_connected']}")
        print(f"  predicted min adjacencies: {report['predicted_min_adjacencies']}")
    print(f"\n  VERDICT: {report['verdict']}")
    for r in report["reasons"]:
        print(f"    - {r}")

    return 0 if safe else 1


if __name__ == "__main__":
    sys.exit(main())
