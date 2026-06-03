# SafeDeploy

Automated, verified network change deployment with rollback, built on a containerized BGP/OSPF lab.

**Status:** In development. Phases 0–1 complete — a reproducible 4-node FRR ring running OSPF with verified end-to-end reachability, plus a tested read-only state-snapshot tool. The change/verify/rollback engine is next.

## Why

Network changes often go out without a way to predict their effect, and recovery after a bad change is manual and slow. SafeDeploy is an exploration of applying software deployment discipline — pre-change validation, post-change verification, automatic rollback — to routing changes, and of a harder question most rollback systems punt on: how to tell a change that *succeeded* from one that succeeded but quietly degraded the network.

## Architecture

The design: four FRRouting nodes in a ring (r1–r4) running OSPF (BGP to follow), deployed via Containerlab on a single EC2 instance. A Python control layer drives changes; Batfish models proposed changes offline before they touch the network.

A change flows: snapshot current state → model the change with Batfish → apply → verify control plane (adjacencies, route table) and data plane (actual path) → roll back to snapshot if verification fails.

## Current state

Working today:

- 4-node FRR ring, reproducible from `topology.clab.yml` + `configs/` via `./deploy.sh`
- OSPF converged across all four routers (every adjacency Full), verified end-to-end (r1 loopback reaches r3 loopback across the ring; TTL confirms a transit hop)
- `deploy.sh` self-heals the FRR startup race so cold deploys come up clean
- **Phase 1:** `snapshot.py` captures each router's full state (config, OSPF neighbors, interfaces, routes) to timestamped JSON as a known-good baseline. Read-only by construction; handles unreachable nodes gracefully.

Planned: push config change, verify-then-rollback, Batfish pre-change validation, data-plane verification, dashboard, fault injection, constrained intent layer.

## Design notes

- Runs on FRR (open-source Linux routing), not vendor NOS. Protocol behavior and automation patterns are real; vendor-specific quirks are out of scope by design.
- The snapshot/deploy tooling uses `docker exec` against the containerlab nodes today; the connection layer is isolated so a production SSH/Netmiko collector could drop in without changing the rest of the tool.
- "Rollback on failure" requires defining *failure*. A working naive version (revert on reachability loss) is the near-term goal; the research direction is a defensible, intent-aware definition that also catches degradation (suboptimal paths, slow convergence), and an honest account of where that definition breaks.

## Engineering log

Phase 0 was not a clean first pass. The debugging — daemons, kernel-level link state, config persistence, an OSPF interface-binding race, and a single-node zebra failure — is written up honestly in [`docs/PHASE0-LOG.md`](docs/PHASE0-LOG.md), since how the network was brought up is more informative than the fact that it runs.

## Repo layout
deploy.sh              # deploy the lab + self-heal FRR startup race
topology.clab.yml      # containerlab topology; binds configs into each node
snapshot.py            # Phase 1: read-only network state snapshot -> JSON
configs/
daemons              # FRR daemon enablement (shared by all nodes)
r1/frr.conf          # per-router config (loopback, interfaces, OSPF)
r2/frr.conf
r3/frr.conf
r4/frr.conf
docs/
PHASE0-LOG.md        # build + debugging log for Phase 0
snapshots/             # runtime output (gitignored)
