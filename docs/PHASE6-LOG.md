# Phase 6 - Intent verification

Goal of Phase 6: invert the model. Phases 1-5 are imperative (apply a change,
check specific results). Phase 6 is declarative: the network's DESIRED STATE is
written down in `intent.yml`, and `verify_intent.py` proves whether live reality
conforms to it. This is intent-based networking in miniature - the same model
behind tools like Cisco NSO and Juniper Apstra - and it becomes the single
"is the network in its intended state?" gate the deploy pipeline can call.

## The intent file (intent.yml)

Three kinds of assertion, declared as desired state:

- control_plane.min_neighbors: each router must hold at least N Full OSPF
  adjacencies (2 in the ring = fully converged).
- reachability: each src loopback must reach each dst loopback, and the
  forwarding path must be within max_hops routers.
- path: specific flows whose forwarding path must match an exact router sequence
  (ECMP-aware: any equal-cost path matching the expectation counts).

## The verifier (verify_intent.py)

Reads intent.yml and checks each assertion against the live lab, reusing the
Phase 5 FIB-walk and the same next-hop resolution:

- control_plane: counts Full neighbors per router (show ip ospf neighbor).
- reachability: pings dst loopback from src loopback, and walks the FIB to
  measure the shortest forwarding path length against max_hops.
- path: walks the FIB and confirms a path matches the expected sequence exactly.

Output is PASS/FAIL per assertion with evidence, a tally, and a non-zero exit
code if ANY intent is violated. The exit code is the important part: a deploy can
run verify_intent.py, check the status, and roll back automatically on violation.

## Verification (Phase 6 gate)

Healthy lab:
- 8/8 checks passed, INTENT SATISFIED, exit code 0.

Deliberate violation (raised r1 eth1 OSPF cost to 1000, forcing r1->r2 off the
direct link onto the long way around the ring):
- control_plane: still PASS (neighbors unaffected) - correct discrimination, it
  failed only what actually broke.
- reachability r1->r2 within 2 hops: FAIL (shortest path became 4 routers).
- path r1->r2 expected [r1, r2]: FAIL (actual path r1 -> r4 -> r3 -> r2).
- 6/8 passed, INTENT VIOLATED, exit code 1.

Reset (no ip ospf cost):
- back to 8/8, INTENT SATISFIED, exit code 0.

This proves the verifier detects drift from declared intent, reports it with
actionable evidence (expected vs actual path), and signals it in a way a pipeline
can act on.

## Why this is the capstone

Every earlier phase produces a capability; Phase 6 unifies them under a single
declarative question. verify_intent.py already calls reachability, path, and
control-plane checks, so it is the natural high-level entrypoint for the planned
CLI: "deploy a change, then verify intent, roll back if intent is violated."

## Notes carried forward

- The intent schema is intentionally small and readable. It can grow (forbidden
  paths, per-link utilization, convergence-time budgets) without changing the
  verifier's structure - each new key is another check function.
- Ping uses the source loopback as the source address so reachability is tested
  loopback-to-loopback (the routed overlay), not just link-local.
