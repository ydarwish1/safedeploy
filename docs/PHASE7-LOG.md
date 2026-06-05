# Phase 7 - BGP overlay on the OSPF underlay

Goal of Phase 7: make the lab a realistic two-layer network. Real networks run an
IGP for infrastructure reachability and BGP on top for route distribution. Phase 7
adds a full iBGP mesh over the existing OSPF underlay, proves route propagation,
and extends the intent layer to verify BGP session state.

## What was built

- bgpd was already enabled in the shared daemons file, so no daemon change needed.
- iBGP, AS 65000, full mesh: every router peers with the other three over their
  loopback addresses (update-source lo), not link addresses. Loopback peering is
  the production pattern: the session survives a link failure as long as the IGP
  still has a path to the peer's loopback.
- r1 originates a test prefix (192.168.100.0/24) into BGP, backed by a Null0 route
  so the network statement has something to advertise. Test origin, not real
  reachability.
- BGP config is baked into each router's frr.conf, so the full mesh comes up on
  every cold deploy.

## Why loopback peering demonstrates the layering

When r3 learns the test prefix, its BGP next-hop is r1's loopback (1.1.1.1),
resolved through the OSPF underlay (the route shows metric 20, the OSPF cost to
reach r1). BGP carries the routes; OSPF carries the reachability BGP depends on.

## Build order (each step verified before the next)

1. Peered one pair (r1 <-> r2) first, confirmed Established before fanning out.
2. Completed the full mesh (12 sessions), confirmed all Established.
3. Originated the test prefix, confirmed propagation: r3 sees it via iBGP
   next-hop 1.1.1.1, r4 marks it valid/best.
4. Baked config into frr.conf files, proved from a cold ./deploy.sh.
5. Extended intent verification to cover BGP.

## Cold-boot proof (the Phase 7 gate)

From a single ./deploy.sh: OSPF 2 Full on every router; r1's three BGP peers all
Established with PfxSnt=1; r3 learned the prefix via iBGP, next-hop resolved
through OSPF, marked best. All three layers reproducible from cold.

## Intent verification extended to BGP

intent.yml gained bgp.min_established (each router must hold >= 3 Established
peers). verify_intent.py gained verify_bgp(), which counts Established peers from
"show ip bgp summary" (a peer is Established when its State/PfxRcd column is a
number, not a word like Active/Idle/Connect).

Healthy run: 12/12 checks pass, INTENT SATISFIED, exit 0.

Violation test: shutting r1's peering to r2 dropped both r1 and r2 to 2 Established
peers (bidirectional), failing exactly those two checks while r3 and r4 stayed at
3 and passed. Restoring the peering returned the network to 12/12. Note: do not
pipe verify_intent.py through grep when checking exit code, the pipe reports
grep's status, not the verifier's.

## Notes carried forward

- The mesh is iBGP because the lab is one AS; iBGP does not re-advertise between
  peers, hence the full mesh. At scale this is where route reflectors come in.
- A future eBGP edge (a node in a different AS advertising external prefixes) would
  let preflight/path/intent reason about inbound routes too.
