#!/usr/bin/env python3
"""Offline test of the full self-healing control flow.

The live lab and the model call are replaced with deterministic stand-ins, so
the path - intent violated -> healer proposes enable -> gate approves -> commit
restores the network -> intent satisfied - is proven without a lab or an API key.
"""

from unittest.mock import patch
from proposal import Proposal
from gate import ConvergenceGate
import watcher

failures = 0

# Stand-in lab state: ring with r1-r2 already broken by a fault.
broken = {"r1": {"r4"}, "r2": {"r3"}, "r3": {"r2", "r4"}, "r4": {"r3", "r1"}}
lab = {"healed": False}

def offline_intent():
    return (lab["healed"], "FAIL: r1 -> r2 path violated" if not lab["healed"]
            else "12/12 intent checks passed")

def record_commit(p):                     # the repair: enabling restores the lab
    if p.action == "enable":
        lab["healed"] = True
    return {"decision": "kept"}

# Offline stand-in for the model: healer returns the repair, critic approves.
def offline_ask(system, user_msg):
    if "repair agent" in system:
        assert "r1 eth1" in user_msg, "evidence should name the down interface"
        return {"action": "enable", "router": "r1", "interface": "eth1",
                "value": None, "rationale": "re-enable the admin-down link"}
    return {"recommendation": "APPROVE", "concerns": []}

with patch("watcher.check_intent", side_effect=offline_intent), \
     patch.object(watcher, "admin_down_interfaces", return_value=["r1 eth1"]), \
     patch("agents._ask", side_effect=offline_ask), \
     patch("joint_preflight.build_topology", return_value=broken), \
     patch("joint_preflight.neighbor_on_interface", return_value=None):

    g = ConvergenceGate(commit_fn=record_commit)
    healed = watcher.heal_cycle(g)

print("healed:", healed)                          # expect True
failures += 0 if healed else 1
failures += 0 if lab["healed"] else 1

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURES")
raise SystemExit(failures)
