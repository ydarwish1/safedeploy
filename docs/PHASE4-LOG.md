# Phase 4 - Offline pre-flight change validation

Goal of Phase 4: add offline modeling so a proposed change can be analyzed before
it touches the live network. A change that would partition the network should be
caught and refused at pre-flight, before the Phase 3 apply/verify/rollback
pipeline ever runs.

Outcome: achieved with a self-built topology model (`preflight.py`). The intended
tool, Batfish, was integrated and models the lab topology correctly, but its FRR
support hits a boundary on pure-FRR configs (documented below). Rather than
fabricate a config representation to satisfy Batfish, the pre-flight check was
built directly against the real configs, which keeps fidelity and integrates
cleanly with the rest of the tooling.

## The Batfish attempt and its boundary

Batfish was deployed (batfish/allinone container) and pybatfish connected
successfully. It ingested the configs and correctly modeled the topology: all 12
interfaces and their IP addresses across the four routers.

It did not model the OSPF control plane, for a specific, diagnosed reason:

- Batfish auto-detected the configs as CISCO_IOS, because FRR's CLI is IOS-like.
  Under the IOS grammar, interfaces and IPs parsed, but FRR-native OSPF syntax
  (`ip ospf area 0`, `router ospf`, `ospf router-id`) was unrecognized, so no
  OSPF sessions were produced.
- Batfish delivers FRR support through its Cumulus Linux vendor parser, not a
  standalone FRR vendor. Forcing that parser (RANCID content type plus a hostname
  declaration) did change the detected format to CUMULUS_CONCATENATED, confirming
  the FRR/Cumulus path engaged.
- But the Cumulus parser expects the Cumulus two-file model (interface addressing
  in `/etc/network/interfaces`, routing in `/etc/frr/frr.conf`, joined with
  specific collector markers). This lab runs pure containerized FRR, where all
  config lives in one `frr.conf`. Parse warnings confirmed the section markers
  and the frr.conf body were not recognized, so OSPF still did not model.

Closing the gap would mean synthesizing a fabricated `/etc/network/interfaces`
section and exact Cumulus markers, i.e. feeding Batfish a Cumulus representation
of a device that does not run Cumulus. That trades fidelity (the actual configs)
for tool compatibility, which is the wrong trade for a project whose value is
fidelity to the real network.

## The self-built pre-flight validator

`preflight.py` builds a graph model directly from the live configs:

- It reads each router's running config and extracts OSPF-enabled, addressed
  interfaces.
- Two routers are linked in the graph if they share an OSPF subnet (the same /30
  on OSPF-enabled interfaces). An interface that is shut, or not in OSPF, does
  not contribute a link.
- It then simulates a proposed change on the graph and predicts the result:
  - `shutdown`: remove the affected link, then check whether the graph is still
    one connected component and whether any router is left with zero
    adjacencies. If the change would partition the network, the verdict is
    UNSAFE and the change should not be applied.
  - `cost`: a cost change cannot remove a link or partition the topology; it only
    shifts path preference, so it is always topologically SAFE.

This is the pre-flight gate: cheap, offline, and run before touching the network.

## Scope (honest)

Pre-flight models L3 topology and connectivity. It predicts partition/isolation
effects of link and cost changes. It does NOT model full OSPF behavior (timers,
LSA flooding, exact convergence). That is intentional: pre-flight catches
obviously-unsafe changes cheaply, and the live-lab verification in Phase 3
remains the authoritative check of real behavior. The two layers complement each
other - predict cheaply, then verify for real.

## Verification (Phase 4 gate)

- Shutting one ring link (`r1 eth2`, the link to r4): predicted SAFE, network
  stays connected via the redundant ring path, minimum adjacencies drops from 2
  to 1. Matches reality (the ring tolerates a single link loss).
- Cost change: predicted SAFE (topology unchanged), consistent with Phase 2/3
  results where a cost change only shifted path preference.

## Notes carried forward

- A change that genuinely partitions the topology (e.g. isolating a router by
  removing both of its links) would be predicted UNSAFE; the model supports this
  directly via the connectivity check.
- Future option: run the lab on Cumulus VX, which Batfish models natively, to get
  full control-plane simulation. Larger change than this phase warranted;
  recorded for later.
