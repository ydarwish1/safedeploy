# Phase 2 - Apply & Verify a Config Change

Goal of Phase 2: give the tool the ability to change a router and confirm the
change took effect. Phase 1 was read-only; this is the write half. There is
deliberately no rollback in this phase (that is Phase 3). Phase 2's job is
narrow: apply one change, read it back, confirm it is present, and shift real
traffic.

Outcome: achieved. change.py sets the OSPF cost on one interface, verifies the
exact cost line is present in the running config, and the change measurably
changed path selection on the live network.

## Change model

The Phase 2 change is OSPF interface cost. It was chosen because it is real (it
influences which path OSPF prefers), easily verified (it appears in both the
running config and show ip ospf interface), and reversible. It also does useful
setup work: raising the cost on one ring link breaks the equal-cost tie and
forces a single preferred path, which later phases need for clean reroute
experiments.

## How it works

- Command-line tool: change.py --router rX --interface ethN --cost C. A change
  tool needs to be told what to change, so unlike the hardcoded Phase 1
  snapshotter, this takes arguments.
- apply_ospf_cost() is the only state-changing function in the tool. It enters
  vtysh config mode and sets the cost. Containing the one dangerous capability
  in a single named function is deliberate: Phase 3 will wrap this exact
  function in snapshot-and-rollback safety logic.
- verify_ospf_cost() does not trust that the command succeeded. It reads the
  running config back and confirms the exact "ip ospf cost C" line is present
  under the target interface. Apply-and-verify, not apply-and-assume.
- The tool prints the interface state before and after so the effect is visible.

## Verification (Phase 2 gate)

- Ran: change.py --router r1 --interface eth1 --cost 50. Before showed Cost 10,
  after showed Cost 50, and verification confirmed the cost line in the running
  config. Gate passed.
- Routing effect confirmed: before the change, r1 reached r3's loopback via two
  equal-cost paths (ECMP). After raising r1 eth1's cost, r1's route to 3.3.3.3
  used a single path (via eth2 toward r4). The change demonstrably altered path
  selection, not just config text.
- Failure path: running against a nonexistent router (r9) raised a clear error
  and exited non-zero rather than silently reporting success.
- Reset: removed the cost (no ip ospf cost) to return r1 eth1 to its default
  (Cost 10), since Phase 2 has no automatic rollback yet.

## Notes carried forward

- No rollback yet. The OSPF cost change is safe on this ring (worst case it
  shifts a path; it does not break reachability), which is why it is the right
  change to practice on before rollback exists.
- Phase 3 will combine snapshot (Phase 1) + apply (Phase 2) + post-change
  verification, and will call rollback if the change breaks a defined health
  condition. apply_ospf_cost is the function it will wrap.
