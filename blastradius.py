#!/usr/bin/env python3
"""
SafeDeploy - Blast radius: quantified impact forecast for a change.

Pre-flight answers "does this change break the network?" - binary. This tool
answers the question senior operators actually ask: "what does this change do
to the network's ability to survive the NEXT failure?" For a proposed change
it computes, on the topology model, before vs after:

  margin   survivability margin = edge connectivity: the minimum number of
           simultaneous link failures that can partition the network
  spofs    every link that becomes a single point of failure after the change
  flows    every router-pair whose shortest forwarding path changes, with the
           old and new hop counts

and grades the result:

  LOW       margin preserved - routine change            (policy: auto-commit)
  ELEVATED  margin reduced / SPOFs created - survivable
            but fragile                                  (policy: human ack)
  UNSAFE    partitions the network                       (policy: refuse)

Pure graph math on the same model the gate trusts; nothing here touches a
device. Usage (lab up):

  python3 blastradius.py -a shutdown -r r1 -i eth1
  python3 blastradius.py -a enable   -r r1 -i eth1
"""

import argparse
import sys
from itertools import combinations

from preflight import build_topology, is_connected, neighbor_on_interface
from joint_preflight import apply_batch_to_graph
from termstyle import banner, step, good, bad, c

GRADE_POLICY = {"LOW": "auto-commit OK",
                "ELEVATED": "requires human ack",
                "UNSAFE": "refuse - do not commit"}


def edges_of(graph):
    return sorted({tuple(sorted((a, b))) for a, n in graph.items() for b in n})


def survivability_margin(graph):
    """Edge connectivity: smallest number of links whose loss partitions.

    Brute force over link subsets, smallest first - exact and instant at lab
    scale, and honest about being exhaustive rather than clever.
    """
    edges = edges_of(graph)
    if not is_connected(graph):
        return 0
    for k in range(1, len(edges) + 1):
        for combo in combinations(edges, k):
            if not is_connected(apply_batch_to_graph(graph, list(combo))):
                return k
    return len(edges)


def single_points_of_failure(graph):
    """Every link whose loss ALONE partitions the graph."""
    return [e for e in edges_of(graph)
            if not is_connected(apply_batch_to_graph(graph, [e]))]


def shortest_hops(graph, src, dst):
    """BFS hop count src->dst on the model; None if unreachable."""
    if src == dst:
        return 0
    seen, frontier, hops = {src}, [src], 0
    while frontier:
        hops += 1
        nxt = []
        for node in frontier:
            for nbr in graph[node]:
                if nbr == dst:
                    return hops
                if nbr not in seen:
                    seen.add(nbr)
                    nxt.append(nbr)
        frontier = nxt
    return None


def flow_changes(before, after):
    """Router pairs whose shortest path length changes (or breaks)."""
    changed = []
    routers = sorted(before)
    for a, b in combinations(routers, 2):
        old, new = shortest_hops(before, a, b), shortest_hops(after, a, b)
        if old != new:
            changed.append({"flow": f"{a}<->{b}", "before_hops": old,
                            "after_hops": new})
    return changed


def forecast(graph, action, router, interface, nbr=None):
    """Full impact report for one change. Returns a dict; pure logic."""
    if nbr is None:
        nbr = neighbor_on_interface(router, interface)
    report = {"action": action, "router": router, "interface": interface,
              "link": None, "margin_before": survivability_margin(graph),
              "margin_after": None, "new_spofs": [], "flow_changes": [],
              "grade": None}

    if action == "shutdown" and nbr:
        after = apply_batch_to_graph(graph, [(router, nbr)])
        report["link"] = f"{router}-{nbr}"
    elif action == "enable" and nbr:
        after = {k: set(v) for k, v in graph.items()}
        after[router].add(nbr)
        after[nbr].add(router)
        report["link"] = f"{router}-{nbr}"
    else:
        after = graph                       # cost / unresolvable: topology no-op

    report["margin_after"] = survivability_margin(after)
    spofs_before = set(single_points_of_failure(graph))
    report["new_spofs"] = [f"{a}-{b}" for a, b in
                           single_points_of_failure(after)
                           if (a, b) not in spofs_before]
    report["flow_changes"] = flow_changes(graph, after)

    if report["margin_after"] == 0:
        report["grade"] = "UNSAFE"
    elif report["margin_after"] < report["margin_before"]:
        report["grade"] = "ELEVATED"
    else:
        report["grade"] = "LOW"
    report["policy"] = GRADE_POLICY[report["grade"]]
    return report


def main():
    ap = argparse.ArgumentParser(description="quantified change impact forecast")
    ap.add_argument("-a", "--action", required=True,
                    choices=["shutdown", "enable", "cost"])
    ap.add_argument("-r", "--router", required=True)
    ap.add_argument("-i", "--interface", required=True)
    args = ap.parse_args()

    banner("SAFEDEPLOY · BLAST RADIUS",
           "what does this change do to the NEXT failure?")
    print()
    step("model", "reading live topology...")
    graph = build_topology()
    rep = forecast(graph, args.action, args.router, args.interface)

    print()
    step("change", f"{rep['action']} {rep['router']} {rep['interface']}"
         + (c(f"  (link {rep['link']})", "grey") if rep["link"] else
            c("  (no topology effect modeled)", "grey")))
    arrow = "->" if rep["margin_after"] != rep["margin_before"] else "=="
    step("margin", f"survivability: {rep['margin_before']} {arrow} "
         f"{rep['margin_after']} simultaneous failure(s) to partition")
    if rep["new_spofs"]:
        bad(f"new single points of failure: {', '.join(rep['new_spofs'])}")
    else:
        good("no new single points of failure")
    if rep["flow_changes"]:
        step("flows", f"{len(rep['flow_changes'])} flow(s) reroute:")
        for f in rep["flow_changes"]:
            print(c(f"        {f['flow']}: {f['before_hops']} -> "
                    f"{f['after_hops']} hops", "grey"))
    else:
        step("flows", "no shortest-path changes")

    print()
    shade = {"LOW": good, "ELEVATED": bad, "UNSAFE": bad}[rep["grade"]]
    shade(f"GRADE: {rep['grade']}  -  policy: {rep['policy']}")
    return 0 if rep["grade"] != "UNSAFE" else 1


if __name__ == "__main__":
    sys.exit(main())
