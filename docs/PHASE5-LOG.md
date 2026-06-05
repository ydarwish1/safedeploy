# Phase 5 - Data-plane path verification

Goal of Phase 5: confirm that traffic takes the EXPECTED path, not just that it
arrives. Phase 3 verifies reachability (every loopback pings every other). But a
change can leave the network fully reachable while silently rerouting traffic the
wrong way - a longer path, through the wrong transit node, or across a link that
should not carry it. That is the "succeeded but degraded" case. Phase 5 catches
it.

Tool: `verify_path.py`.

## Two methods, cross-checked

1. FIB walk (control-plane intent). Starting at the source router, read its
   routing table for the destination, resolve the next-hop IP to a router, hop to
   that router, and repeat until the destination is reached. This reconstructs
   the path each router will actually use, from its own forwarding table. It is
   deterministic and handles ECMP by branching at each step where more than one
   equal-cost next-hop exists, returning every path.

2. Live traceroute (data-plane reality). Run a real traceroute from the source
   loopback to the destination loopback and record the hops the packets actually
   traversed. This proves real traffic behavior, not just the model.

The two are complementary: the FIB walk shows all forwarding options the routers
will use; the traceroute shows which one a real packet took. An optional
`--expect` argument checks the FIB path against an expected path (router names).

## Implementation notes

- Next-hop resolution maps each point-to-point interface IP back to the router
  that owns it (IFACE_IPS), so a next-hop address from the routing table becomes
  a router name in the reconstructed path.
- The FIB walk has a loop guard (path length bounded by node count) and detects
  revisited routers, so a misrouted or looping topology is reported rather than
  hanging.
- A destination reached on its own router is detected and ends the walk cleanly.

## Bug found and fixed during build

The first FIB walk reported UNREACHABLE for routes that clearly existed. Cause: a
regex that expected the next-hop IP to appear AFTER the word "via". FRR's route
output is "* 10.0.12.2, via eth1, weight 1", where the next-hop IP comes BEFORE
"via" and "via" is followed by the interface name. The regex was corrected to
match the IP before "via". The live traceroute confirmed throughout that the
network itself was healthy, which isolated the fault to the parser rather than the
lab.

## Verification (Phase 5 gate)

Baseline (r1 to r3, equal-cost paths exist):
- FIB walk returned both paths: r1 -> r2 -> r3 and r1 -> r4 -> r3.
- Live traceroute confirmed real packets reached 3.3.3.3.

Directly-reachable case (r1 to r2):
- FIB walk returned the single path r1 -> r2; `--expect r1,r2` reported Match YES;
  traceroute confirmed 2.2.2.2.

Path-shift detection (the point of the phase):
- Raised r1 eth1 OSPF cost to 500, making the r1->r2->r3 path expensive.
- Re-running verify showed the path collapse from two ECMP paths to the single
  path r1 -> r4 -> r3, and traceroute confirmed real packets followed it.
- Resetting the cost (`no ip ospf cost`) restored both ECMP paths.

This proves the tool detects when a change reroutes traffic, which is exactly the
degradation signal Phase 3 reachability checks alone would miss.

## Integration

verify_path.py stands alone now. It is designed to plug into the Phase 3 pipeline
as an additional post-change health layer: after a change, confirm not only that
destinations are reachable but that key flows still take their expected paths, and
roll back if a path has shifted unexpectedly. That wiring is left for the CLI
unification step.
