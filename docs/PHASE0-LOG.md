# Phase 0 — Build & Debugging Log

Goal of Phase 0: stand up a 4-node FRRouting ring (r1–r4) on Containerlab/EC2,
running OSPF in area 0, with every adjacency Full and verified end-to-end
reachability between loopbacks across the ring.

Outcome: achieved. The path there involved four distinct failures, each at a
different layer. They're documented below because the diagnosis is the point —
the final config is short; understanding why earlier attempts failed is what the
work actually was.

## Topology

Ring: r1 — r2 — r3 — r4 — back to r1.
Loopbacks: r1 1.1.1.1, r2 2.2.2.2, r3 3.3.3.3, r4 4.4.4.4 (/32 each).
Point-to-point links, /30 each, named for the routers they join:
r1–r2 10.0.12.0/30, r2–r3 10.0.23.0/30, r3–r4 10.0.34.0/30, r4–r1 10.0.41.0/30.
OSPF single area 0.

## Issue 1 — Routing daemons not running

Symptom: in vtysh, `router ospf` returned `ospfd is not running`; OSPF config
appeared to be accepted but had no effect.

Root cause: FRR ships with routing daemons disabled by default
(`/etc/frr/daemons` has `ospfd=no`, `bgpd=no`). Until those are enabled and FRR
reloads, OSPF/BGP commands are silently ignored.

Fix (final form): enable the daemons in a `daemons` file that is bind-mounted
into each node at deploy time, so daemons come up enabled from boot and no
post-deploy restart is needed.

Lesson: in FRR, configuring a protocol and *running* the protocol's daemon are
two separate steps. A command being accepted at the prompt does not mean a
daemon exists to act on it.

## Issue 2 — `docker restart` dropped the data links

Symptom: after restarting a node to pick up the daemon change, OSPF still saw no
neighbors. `vtysh` showed eth1/eth2 as down with no addresses;
`ip link show` inside the container showed only `lo` and `eth0` — eth1 and eth2
did not exist at the kernel level.

Root cause: Containerlab wires inter-node links as veth pairs at deploy time. A
plain `docker restart` on a node brings the container back without those veth
links, because Docker does not re-run Containerlab's link wiring. I had been
configuring interfaces that no longer existed.

Diagnosis step that mattered: when FRR's view (eth1/eth2 present but down)
stopped matching reality, I dropped to the layer below — `ip link show` — and
compared the kernel's view to FRR's. The disagreement located the problem.

Fix: rebuild wiring with `containerlab deploy --reconfigure` rather than
`docker restart`. Confirmed eth1/eth2 present and UP at the kernel level before
touching FRR config again.

Lesson: when the layer you're working in stops making sense, verify the layer
beneath it. Containerlab manages links; Docker does not — restarting at the
wrong layer silently destroys state.

## Issue 3 — Config wouldn't persist on save

Symptom: `write memory` reported `Can't open configuration file
/etc/frr/ospfd.conf.XXXXXX` for the per-daemon files; config didn't survive.

Root cause: permissions/ownership on the per-daemon config files prevented FRR
from writing them.

Fix: switch to FRR integrated configuration (`service integrated-vtysh-config`),
which persists everything to a single `/etc/frr/frr.conf`, and ensure that file
is writable. In the final design this is moot — config is supplied by a
bind-mounted `frr.conf`, so it loads at boot and isn't written back at all.

Lesson: there are two FRR config models (per-daemon files vs. integrated
frr.conf). Mixing them, or fighting file permissions, wastes time. Pick
integrated config and bind-mount it.

## Issue 4 — One node (r4) had a dead zebra

Symptom: after a clean bind-mounted deploy, r1–r3 worked and formed adjacencies,
but r4 had zero OSPF neighbors and `vtysh` reported `zebra is not running` on r4
specifically.

Diagnosis: r4's `daemons` and `frr.conf` were verified correct and identical in
intent to the others — so this was not a config problem. `ps` inside r4 showed
watchfrr and ospfd alive but zebra absent: zebra had failed/crashed on this node
while the rest of FRR stayed up.

Fix: watchfrr (FRR's watchdog) brought zebra back; once zebra was running, r4
loaded its interface addresses and OSPF activated, and both of r4's adjacencies
went Full.

Lesson: isolate the failing node before touching the working ones. Three of four
nodes healthy means the method is sound and the fault is local. Also: FRR is
several cooperating daemons, not one process — one (zebra) can die while others
survive, producing partial, confusing behavior.

## Verification (Phase 0 gate)

- `show ip ospf neighbor` on every node: two neighbors each, all Full
  (each router peers only with its two ring-adjacent neighbors — two is correct
  for a ring, not a missing-neighbor sign).
- `ping -c 4 -I 1.1.1.1 3.3.3.3`: 0% loss; replies at TTL 63 (one decrement from
  64), confirming the packet transited an intermediate router rather than a
  direct link — i.e. OSPF actually routed it.
- `show ip route 3.3.3.3`: learned via OSPF (administrative distance 110).

## Observations carried forward (not yet acted on)

- ECMP to r3: r1 has two equal-cost paths to 3.3.3.3 (via r2 and via r4) and
  load-balances across both. Fine for Phase 0. For the later reroute/transient
  experiments, one arc's cost will need to be raised to force a single
  preferred path so a path change is cleanly observable.
- OSPF/SPF baseline timers (FRR defaults on this image), recorded for later
  transient-convergence measurement: initial SPF delay 0 ms, min hold 50 ms,
  max hold 5000 ms, LSA min interval 5000 ms, LSA min arrival 1000 ms.

## Known open item

A cold `containerlab deploy --reconfigure` has not yet been confirmed to bring
all four nodes up healthy without manual intervention, since r4's zebra required
a watchdog recovery in this session. Before claiming fully hands-off
reproducibility, this needs to be verified: destroy, deploy fresh, and confirm
all four converge with no manual step. Until then, reproducibility is "comes up
from config, with a possible per-node daemon recovery on r4."
