#!/usr/bin/env python3
"""Offline test: the red team finds every kill on a ring and the gate blocks all.

Graph theory says a 4-cycle survives any single edge removal but is
disconnected by removing ANY two edges. So on the lab ring the red team must
find exactly 4 safe singles and exactly 6 minimal deadly pairs, and the gate
must block 6/6 while allowing 4/4. No lab, no API key.
"""

from unittest.mock import patch
from redteam import hunt, audit_gate, edges_of, components

failures = 0

ring = {"r1": {"r2", "r4"}, "r2": {"r1", "r3"},
        "r3": {"r2", "r4"}, "r4": {"r3", "r1"}}
# Same wiring as the lab: (router, iface) -> neighbor, both directions.
nbr_map = {("r1","eth1"):"r2", ("r2","eth1"):"r1",
           ("r2","eth2"):"r3", ("r3","eth1"):"r2",
           ("r3","eth2"):"r4", ("r4","eth1"):"r3",
           ("r4","eth2"):"r1", ("r1","eth2"):"r4"}
imap = {(r, n): i for (r, i), n in nbr_map.items()}

# 1. The hunt: 4 links -> 4 safe singles, 6 minimal deadly pairs.
safe, deadly = hunt(ring, depth=2)
print(f"links: {edges_of(ring)}")
print(f"safe singles: {len(safe)} (expect 4)")
print(f"minimal deadly combos: {len(deadly)} (expect 6 - any 2 edges cut a cycle)")
failures += 0 if len(safe) == 4 else 1
failures += 0 if len(deadly) == 6 else 1
failures += 0 if all(len(d["links"]) == 2 for d in deadly) else 1

# Spot-check the famous pair strands exactly r1.
killer = next(d for d in deadly
              if set(d["links"]) == {("r1","r2"), ("r1","r4")})
print(f"r1-r2 + r1-r4 strands: {killer['stranded']} (expect [['r1']])")
failures += 0 if killer["stranded"] == [["r1"]] else 1

# 2. The audit: gate blocks 6/6 deadly, allows 4/4 safe - zero false verdicts.
with patch("joint_preflight.build_topology", return_value=ring), \
     patch("joint_preflight.neighbor_on_interface",
           side_effect=lambda r, i: nbr_map.get((r, i))):
    false_allows, false_blocks = audit_gate(safe, deadly, imap)
blocked = sum(1 for d in deadly if d["gate_blocked"])
print(f"gate blocked {blocked}/6 deadly, false allows: {len(false_allows)}, "
      f"false blocks: {len(false_blocks)}")
failures += 0 if (blocked == 6 and not false_allows and not false_blocks) else 1

# 3. Sanity: components() reports the split correctly.
split = components({"r1": set(), "r2": {"r3"}, "r3": {"r2"}, "r4": set()})
failures += 0 if split == [["r1"], ["r4"], ["r2", "r3"]] else 1

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURES")
raise SystemExit(failures)
