#!/usr/bin/env python3
"""
SafeDeploy - Red team: exhaustive adversarial audit of the convergence gate.

inject.py shows the gate blocking ONE dangerous combination. This tool proves
completeness: it enumerates EVERY combination of link failures up to a chosen
depth on the topology model, finds every combination that partitions the
network, then feeds each one through the gate's own joint pre-flight and
verifies the verdict. The exit code is the audit:

  0  the gate blocked every partitioning combination and allowed every safe
     single change - zero false verdicts
  1  a false verdict was found (a dangerous combo the gate would allow, or a
     safe change it would refuse) - the gate has a bug, fix before trusting it

This is deterministic graph math, no LLM involved: the adversary is brute
force, which never gets tired and never misses a case. On the 4-node ring at
depth 2 it tests all 4 singles and all 6 pairs.

Usage (lab up):  python3 redteam.py            # depth 2 (pairs)
                 python3 redteam.py --depth 3  # triples too, on bigger labs
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from preflight import (build_topology, is_connected, get_interface_subnets,
                       neighbor_on_interface)
from joint_preflight import apply_batch_to_graph, joint_preflight
from proposal import Proposal
from termstyle import banner, step, good, bad, c


def edges_of(graph):
    """Unique links as sorted (a, b) tuples."""
    seen = set()
    for a, nbrs in graph.items():
        for b in nbrs:
            seen.add(tuple(sorted((a, b))))
    return sorted(seen)


def components(graph):
    """Connected components, each a sorted list of routers."""
    todo, comps = set(graph), []
    while todo:
        start = todo.pop()
        comp, stack = {start}, [start]
        while stack:
            for nbr in graph[stack.pop()]:
                if nbr in todo:
                    todo.discard(nbr)
                    comp.add(nbr)
                    stack.append(nbr)
        comps.append(sorted(comp))
    return sorted(comps, key=lambda comp: (len(comp), comp))


def interface_map(graph):
    """(router, neighbor) -> the interface on router facing that neighbor."""
    m = {}
    for r in graph:
        for iface in get_interface_subnets(r):
            nbr = neighbor_on_interface(r, iface)
            if nbr:
                m[(r, nbr)] = iface
    return m


def hunt(graph, depth):
    """Exhaustively classify link-failure combinations up to `depth`.

    Returns (safe_singles, deadly) where deadly holds only MINIMAL dangerous
    combinations: a combo is skipped if a smaller already-deadly combo is
    contained in it (those are doomed by inclusion, not interesting).
    """
    edges = edges_of(graph)
    safe_singles, deadly = [], []
    for k in range(1, depth + 1):
        for combo in combinations(edges, k):
            if any(set(d["links"]) <= set(combo) for d in deadly):
                continue                       # superset of a known kill: not minimal
            after = apply_batch_to_graph(graph, list(combo))
            if not is_connected(after):
                comps = components(after)
                deadly.append({"links": combo,
                               "stranded": comps[:-1],   # all but the largest island
                               "split": comps})
            elif k == 1:
                safe_singles.append(combo[0])
    return safe_singles, deadly


def proposals_for(combo, imap, tag):
    """One shutdown Proposal per link in the combo (shut one end of each)."""
    props = []
    for i, (a, b) in enumerate(combo):
        props.append(Proposal(id=f"{tag}-{i+1:02d}", action="shutdown",
                              router=a, interface=imap[(a, b)],
                              rationale=f"red team: kill {a}-{b}"))
    return props


def audit_gate(safe_singles, deadly, imap):
    """Feed every finding through the gate's own joint check; count mistakes."""
    false_allows, false_blocks = [], []
    for n, d in enumerate(deadly, 1):
        ok, _ = joint_preflight(proposals_for(d["links"], imap, f"rt-kill{n}"))
        d["gate_blocked"] = not ok
        if ok:
            false_allows.append(d["links"])
    for n, link in enumerate(safe_singles, 1):
        ok, _ = joint_preflight(proposals_for((link,), imap, f"rt-safe{n}"))
        if not ok:
            false_blocks.append(link)
    return false_allows, false_blocks


def main():
    ap = argparse.ArgumentParser(description="exhaustive adversarial gate audit")
    ap.add_argument("--depth", type=int, default=2,
                    help="max links failed together (default 2)")
    ap.add_argument("--out", default="status/redteam.json")
    args = ap.parse_args()

    banner("SAFEDEPLOY · RED TEAM",
           "every failure combination, exhaustively, vs the gate")

    print()
    step("model", "reading live topology...")
    graph = build_topology()
    edges = edges_of(graph)
    imap = interface_map(graph)
    step("model", f"{len(graph)} routers, {len(edges)} links: "
         + c(", ".join(f"{a}-{b}" for a, b in edges), "grey"))

    print()
    step("hunt", f"testing every combination up to {args.depth} simultaneous failures...")
    safe_singles, deadly = hunt(graph, args.depth)
    for link in safe_singles:
        good(f"{link[0]}-{link[1]} alone: survivable, ring reroutes")
    for d in deadly:
        names = " + ".join(f"{a}-{b}" for a, b in d["links"])
        bad(f"{names}: PARTITIONS - strands {d['stranded']}")

    print()
    step("audit", "replaying every finding through the gate's joint pre-flight...")
    false_allows, false_blocks = audit_gate(safe_singles, deadly, imap)

    blocked = sum(1 for d in deadly if d["gate_blocked"])
    print()
    report = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "depth": args.depth,
              "links": [f"{a}-{b}" for a, b in edges],
              "safe_singles": [f"{a}-{b}" for a, b in safe_singles],
              "deadly_combos": [{"links": [f"{a}-{b}" for a, b in d["links"]],
                                 "strands": d["stranded"],
                                 "gate_blocked": d["gate_blocked"]} for d in deadly],
              "false_allows": len(false_allows),
              "false_blocks": len(false_blocks)}
    Path(args.out).parent.mkdir(exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))

    if not false_allows and not false_blocks:
        good(f"AUDIT CLEAN: {blocked}/{len(deadly)} dangerous combinations blocked, "
             f"{len(safe_singles)}/{len(safe_singles)} safe changes allowed, "
             f"0 false verdicts")
        print(c(f"evidence written to {args.out}", "grey"))
        return 0
    bad(f"AUDIT FAILED: {len(false_allows)} dangerous combos the gate would ALLOW, "
        f"{len(false_blocks)} safe changes it would refuse - do not trust the gate")
    return 1


if __name__ == "__main__":
    sys.exit(main())
