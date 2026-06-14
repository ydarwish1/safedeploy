#!/usr/bin/env python3
"""Offline test: blast radius math verified against hand-computed graph facts.

On the 4-ring: margin is 2 (a cycle is 2-edge-connected), no SPOFs. After
shutting r1-r2 the ring becomes the path r2-r3-r4-r1: margin 1, every
remaining link is a SPOF, and r1<->r2 stretches from 1 hop to 3. Re-enabling
restores everything. No lab, no API key.
"""

from blastradius import (survivability_margin, single_points_of_failure,
                         shortest_hops, flow_changes, forecast)

failures = 0
ring = {"r1": {"r2", "r4"}, "r2": {"r1", "r3"},
        "r3": {"r2", "r4"}, "r4": {"r3", "r1"}}
path = {"r1": {"r4"}, "r2": {"r3"}, "r3": {"r2", "r4"}, "r4": {"r3", "r1"}}

# 1. Baseline ring: margin 2, zero SPOFs (2-edge-connected cycle).
failures += 0 if survivability_margin(ring) == 2 else 1
failures += 0 if single_points_of_failure(ring) == [] else 1
print(f"ring: margin={survivability_margin(ring)} (expect 2), "
      f"spofs={len(single_points_of_failure(ring))} (expect 0)")

# 2. Path graph after losing r1-r2: margin 1, all 3 remaining links are SPOFs.
failures += 0 if survivability_margin(path) == 1 else 1
failures += 0 if len(single_points_of_failure(path)) == 3 else 1
print(f"path: margin={survivability_margin(path)} (expect 1), "
      f"spofs={len(single_points_of_failure(path))} (expect 3)")

# 3. BFS sanity: r1->r2 is 1 hop on the ring, 3 on the path; r1->r3 always 2.
failures += 0 if shortest_hops(ring, "r1", "r2") == 1 else 1
failures += 0 if shortest_hops(path, "r1", "r2") == 3 else 1
failures += 0 if shortest_hops(path, "r1", "r3") == 2 else 1

# 4. Full forecast: shutdown r1 eth1 (kills r1-r2) -> ELEVATED, human ack.
rep = forecast(ring, "shutdown", "r1", "eth1", nbr="r2")
print(f"shutdown r1-r2: grade={rep['grade']} (expect ELEVATED), "
      f"margin {rep['margin_before']}->{rep['margin_after']} (expect 2->1), "
      f"new spofs={len(rep['new_spofs'])} (expect 3), "
      f"flows changed={len(rep['flow_changes'])}")
failures += 0 if rep["grade"] == "ELEVATED" else 1
failures += 0 if (rep["margin_before"], rep["margin_after"]) == (2, 1) else 1
failures += 0 if len(rep["new_spofs"]) == 3 else 1
r12 = next((f for f in rep["flow_changes"] if f["flow"] == "r1<->r2"), None)
failures += 0 if r12 and (r12["before_hops"], r12["after_hops"]) == (1, 3) else 1

# 5. Enable on the broken path restores the ring -> LOW, margin back to 2.
rep2 = forecast(path, "enable", "r1", "eth1", nbr="r2")
print(f"enable r1-r2 on path: grade={rep2['grade']} (expect LOW), "
      f"margin {rep2['margin_before']}->{rep2['margin_after']} (expect 1->2)")
failures += 0 if rep2["grade"] == "LOW" else 1
failures += 0 if (rep2["margin_before"], rep2["margin_after"]) == (1, 2) else 1

# 6. Cost change: topology no-op -> LOW, nothing shifts in the model.
rep3 = forecast(ring, "cost", "r2", "eth2", nbr="r3")
failures += 0 if (rep3["grade"] == "LOW" and not rep3["flow_changes"]) else 1
print(f"cost change: grade={rep3['grade']} (expect LOW), "
      f"flows changed={len(rep3['flow_changes'])} (expect 0)")

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURES")
raise SystemExit(failures)
