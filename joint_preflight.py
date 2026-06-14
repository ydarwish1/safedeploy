#!/usr/bin/env python3
"""
SafeDeploy - Joint pre-flight check (convergence gate core).

Evaluates a BATCH of Proposals together: all changes are applied to ONE copy
of the topology graph, then connectivity is checked on the combined result.
This catches combinations that are safe alone but partition together.
Reuses the existing preflight.py model; never touches a device beyond reads.
"""

from preflight import (build_topology, is_connected, min_adjacencies,
                       neighbor_on_interface)


def apply_batch_to_graph(graph, links_to_remove):
    """Pure logic: erase EVERY given link on the same copy, return the result."""
    g = {k: set(v) for k, v in graph.items()}        # one shared copy
    for router, neighbor in links_to_remove:
        g[router].discard(neighbor)
        g[neighbor].discard(router)
    return g


def joint_preflight(proposals):
    """Check all proposals TOGETHER. Returns (safe: bool, report: dict)."""
    base = build_topology()                          # live topology, read once
    report = {"proposals": [p.id for p in proposals],
              "links_removed": [], "verdict": None, "reasons": [],
              "predicted_connected": None, "predicted_min_adjacencies": None}

    # Resolve each shutdown proposal to the link it would kill.
    links = []
    for p in proposals:
        if p.action == "shutdown":
            nbr = neighbor_on_interface(p.router, p.interface)
            if nbr is None:
                report["reasons"].append(
                    f"{p.id}: no modeled OSPF neighbor on "
                    f"{p.router} {p.interface}, treated as no-op")
                continue
            links.append((p.router, nbr))
            report["links_removed"].append(f"{p.router}-{nbr}")
        elif p.action == "enable":
            # Re-enabling can only ADD a link; adding capacity cannot
            # partition, so it is conservatively treated as a no-op here.
            report["reasons"].append(f"{p.id}: enable can only add capacity, safe")
        # cost proposals can't remove links: topologically a no-op here.

    # Apply ALL removals to one graph copy, then judge the combined end-state.
    after = apply_batch_to_graph(base, links)
    report["predicted_connected"] = is_connected(after)
    report["predicted_min_adjacencies"] = min_adjacencies(after)

    if not report["predicted_connected"]:
        report["verdict"] = "UNSAFE"
        report["reasons"].append("COMBINED changes partition the network")
        return (False, report)
    if report["predicted_min_adjacencies"] < 1:
        report["verdict"] = "UNSAFE"
        report["reasons"].append("a router would be left with 0 adjacencies")
        return (False, report)
    report["verdict"] = "SAFE"
    report["reasons"].append("combined end-state stays connected")
    return (True, report)
