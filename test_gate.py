#!/usr/bin/env python3
"""Offline test: gate queue mechanics with a recording commit (no lab needed).

The commit step is replaced with a recorder, so the queue, joint-check, and
commit logic runs and is asserted without touching a device.
"""

from unittest.mock import patch
from proposal import Proposal
from gate import ConvergenceGate

failures = 0
committed = []
record_commit = lambda p: committed.append(p.id)    # record instead of deploying

ring = {"r1": {"r2", "r4"}, "r2": {"r1", "r3"},
        "r3": {"r2", "r4"}, "r4": {"r3", "r1"}}

# Stand in for the live lab: topology is the hand-built ring, neighbors from a map.
nbr_map = {("r1", "eth1"): "r2", ("r4", "eth2"): "r1", ("r2", "eth2"): "r3"}
with patch("joint_preflight.build_topology", return_value=ring), \
     patch("joint_preflight.neighbor_on_interface",
           side_effect=lambda r, i: nbr_map.get((r, i))):

    # Batch 1: one safe shutdown -> should commit
    g = ConvergenceGate(commit_fn=record_commit)
    g.submit(Proposal(id="p1", action="shutdown", router="r1", interface="eth1"))
    r1 = g.evaluate_and_commit()
    print("batch1 verdict:", r1["verdict"], "committed:", r1["committed"])
    failures += 0 if (r1["verdict"] == "SAFE" and r1["committed"] == ["p1"]) else 1

    # Batch 2: the killer combo -> safe alone, UNSAFE together, commit NOTHING
    g.submit(Proposal(id="p2", action="shutdown", router="r1", interface="eth1"))
    g.submit(Proposal(id="p3", action="shutdown", router="r4", interface="eth2"))
    r2 = g.evaluate_and_commit()
    print("batch2 verdict:", r2["verdict"], "committed:", r2["committed"])
    failures += 0 if (r2["verdict"] == "UNSAFE" and r2["committed"] == []) else 1

    # Batch 3: a commit that rolls back halts the rest of the batch
    def rollback_commit(p):
        committed.append(p.id)
        return {"decision": "rolled_back"}
    g2 = ConvergenceGate(commit_fn=rollback_commit)
    g2.submit(Proposal(id="p4", action="cost", router="r2", interface="eth2", value=50))
    g2.submit(Proposal(id="p5", action="cost", router="r2", interface="eth2", value=60))
    r3 = g2.evaluate_and_commit()
    print("batch3 verdict:", r3["verdict"], "committed:", r3["committed"],
          "halted_after_rollback:", r3["halted_after_rollback"])
    failures += 0 if (r3["committed"] == [] and
                      r3["halted_after_rollback"] == "p4") else 1

print("total committed:", committed)                 # expect ['p1', 'p4']
failures += 0 if committed == ["p1", "p4"] else 1

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURES")
raise SystemExit(failures)
