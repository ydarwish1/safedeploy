# SafeDeploy

Automated, verified network change deployment with rollback, built on a containerized BGP/OSPF lab.

**Status:** In development. Phase 0 complete - a 4-node FRR ring running OSPF, converged with verified end-to-end reachability, reproducible from config. The deployment/verification engine is the next phase.

## Why

Network changes often go out without a way to predict their effect, and recovery after a bad change is manual and slow. SafeDeploy is an exploration of applying software deployment discipline - pre-change validation, post-change verification, automatic rollback - to routing changes, and of a harder question most rollback systems punt on: how to tell a change that *succeeded* from one that succeeded but quietly degraded the network.

## Architecture

The design: four FRRouting nodes in a ring (r1–r4) running OSPF (BGP to follow), deployed via Containerlab on a single EC2 instance. A Python control layer (Netmiko/NAPALM) drives changes; Batfish models proposed changes offline before they touch the network.

A change flows: snapshot current state → model the change with Batfish → apply → verify control plane (adjacencies, route table) and data plane (actual path) → roll back to snapshot if verification fails.

## Current state

Working today:

- 4-node FRR ring, reproducible from `topology.clab.yml` + `configs/`
- OSPF converged across all four routers (every adjacency Full)
- End-to-end reachability verified (r1 loopback 1.1.1.1 reaches r3 loopback 3.3.3.3 across the ring, TTL confirms a transit hop)

Daemons are enabled and routing config loaded automatically via bind-mounted files, so the lab comes up configured rather than requiring manual setup after deploy. (See the known issue on cold-start daemon health in the Phase 0 log.)

Planned: config snapshot/restore, automated deploy, verify-then-rollback, Batfish pre-change validation, data-plane verification, dashboard, fault injection, constrained intent layer.

## Design notes

- Runs on FRR (open-source Linux routing), not vendor NOS. Protocol behavior and automation patterns are real; vendor-specific quirks are out of scope by design.
- "Rollback on failure" requires defining *failure*. A working naive version (revert on reachability loss) is the near-term goal; the research direction is a defensible, intent-aware definition that also catches degradation (suboptimal paths, slow convergence), and an honest account of where that definition breaks.

## Engineering log

Phase 0 was not a clean first pass. The debugging — daemons, kernel-level link state, config persistence, and a single-node failure - is written up honestly in [`docs/PHASE0-LOG.md`](docs/PHASE0-LOG.md), since how the network was brought up is more informative than the fact that it runs.

## Repo layout

```
topology.clab.yml      # containerlab topology; binds configs into each node
configs/
  daemons              # FRR daemon enablement (shared by all nodes)
  r1/frr.conf          # per-router config (loopback, interfaces, OSPF)
  r2/frr.conf
  r3/frr.conf
  r4/frr.conf
docs/
  PHASE0-LOG.md        # build + debugging log for Phase 0
```
