#!/usr/bin/env python3
"""Offline test: joint logic on a hand-built ring graph (no lab needed)."""

from joint_preflight import apply_batch_to_graph
from preflight import is_connected

failures = 0

# Hand-built ring: r1-r2-r3-r4-r1 (same shape as the lab)
ring = {"r1": {"r2", "r4"}, "r2": {"r1", "r3"},
        "r3": {"r2", "r4"}, "r4": {"r3", "r1"}}

# One link removed alone: ring survives (long way around)
one = apply_batch_to_graph(ring, [("r1", "r2")])
print("remove r1-r2 alone -> connected:", is_connected(one))      # expect True
failures += 0 if is_connected(one) else 1

two = apply_batch_to_graph(ring, [("r4", "r1")])
print("remove r4-r1 alone -> connected:", is_connected(two))      # expect True
failures += 0 if is_connected(two) else 1

# BOTH removed together: r1 stranded -> partition (the convergence-gate case)
both = apply_batch_to_graph(ring, [("r1", "r2"), ("r4", "r1")])
print("remove BOTH -> connected:", is_connected(both))            # expect False
failures += 0 if not is_connected(both) else 1

# The original graph must be untouched (copy semantics)
intact = ring == {"r1": {"r2", "r4"}, "r2": {"r1", "r3"},
                  "r3": {"r2", "r4"}, "r4": {"r3", "r1"}}
print("base graph untouched:", intact)                            # expect True
failures += 0 if intact else 1

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURES")
raise SystemExit(failures)
