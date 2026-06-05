# SafeDeploy

Automated, verified network change deployment with rollback, built on a containerized OSPF lab.

**Status:** In active development. Phases 0 through 6 complete: a reproducible 4-node FRR ring running OSPF, a read-only state-snapshot tool, a config-change engine, an automatic verify-then-rollback deployment pipeline, an offline pre-flight change validator, data-plane path verification, and a declarative intent-verification layer.

## Why

Network changes often go out without a way to predict their effect, and recovery after a bad change is manual and slow. SafeDeploy applies software deployment discipline (pre-change validation, post-change verification, automatic rollback) to routing changes. It also takes on a harder question most rollback systems punt on: how to tell a change that succeeded from one that succeeded but quietly degraded the network.

## Architecture

Four FRRouting nodes in a ring (r1 through r4) running OSPF, deployed via Containerlab on a single EC2 instance. A Python control layer drives changes.

A change flows through these steps: pre-flight validate the change offline against a topology model, snapshot current state, apply the change, verify control plane (adjacencies), data plane (reachability), forwarding path (traffic takes the expected route), and overall intent (the declared desired state still holds), and roll back to the snapshot if verification fails.

## Current state

Working today:

- **Phase 0** - 4-node FRR ring, reproducible from `topology.clab.yml` and `configs/` via `./deploy.sh`. OSPF converges across all four routers (every adjacency Full), verified end-to-end (r1 loopback reaches r3 loopback across the ring; TTL confirms a transit hop). Pinned to a stable FRR image; `deploy.sh` self-heals any FRR startup race.
- **Phase 1** - `snapshot.py` captures each router's full state (config, OSPF neighbors, interfaces, routes) to timestamped JSON as a known-good baseline. Read-only by construction; handles unreachable nodes gracefully.
- **Phase 2** - `change.py` applies a real config change (OSPF interface cost) and verifies it landed in the running config and shifted path selection.
- **Phase 3** - `rollback_deploy.py` is the core: a verify-then-commit pipeline. It captures a baseline, applies a change, runs a two-layer health check (control plane: adjacencies Full; data plane: every loopback reachable) within a fail-safe timeout, keeps the change only if health is affirmatively verified, and otherwise restores the baseline and re-verifies recovery. Every run writes a structured decision record.
- **Phase 4** - `preflight.py` validates a change offline before it touches the network. It builds a graph model of the topology from live config and simulates the change (link removal, cost change) to predict whether the network would stay connected, catching partitioning changes before they are ever applied.
- **Phase 5** - `verify_path.py` verifies the data-plane forwarding path: it reconstructs the path traffic will take from each router's FIB (handling equal-cost multipath) and cross-checks it with a live traceroute, optionally against an expected path. This catches changes that leave the network reachable but silently reroute traffic.
- **Phase 6** - `verify_intent.py` inverts the model: the network's desired state is declared in `intent.yml` (required adjacencies, reachability within a hop budget, exact forwarding paths) and the tool proves whether live reality conforms, reporting each assertion PASS/FAIL with evidence and exiting non-zero on any violation. This is the single "is the network in its intended state?" gate the pipeline can act on.

Planned: deploy dashboard, fault injection / self-healing, and a single CLI that unifies the phases with CI-driven validation.

## Design notes

- Runs on FRR (open-source Linux routing), not a vendor NOS. Protocol behavior and automation patterns are real; vendor-specific quirks are out of scope by design.
- The tooling uses `docker exec` against the containerlab nodes today. The connection layer is isolated so a production SSH/Netmiko collector could drop in without changing the rest of the tool.
- Rollback uses full-config replay through vtysh, chosen after testing showed heavier reload mechanisms were unreliable on this image (documented in the Phase 3 log). The mechanism was selected for its predictable failure mode.
- Pre-flight validation is a self-built topology model rather than Batfish. Batfish was integrated and models the lab topology correctly, but parses FRR through its Cumulus vendor model, which expects a config layout this pure-FRR lab does not produce. The boundary is documented honestly in the Phase 4 log; the self-built model keeps fidelity to the actual configs.
- Path verification reads forwarding behavior two independent ways (the routers' own FIB and a live traceroute) so the model and reality are cross-checked rather than trusted blindly.
- Intent verification is declarative: desired state lives in a small, readable YAML file, and the verifier reuses the reachability, path, and control-plane checks as the primitives it asserts against. New intent types (forbidden paths, utilization, convergence budgets) are added as new check functions without changing the structure.
- "Rollback on failure" requires defining failure. The checks now cover control plane, data-plane reachability, forwarding path, and declared intent. Convergence-timing detection is the planned research direction.

## Engineering logs

Each phase is documented honestly, including the bugs and how they were diagnosed and fixed, since how the system was built is more informative than the fact that it runs.

- [`docs/PHASE0-LOG.md`](docs/PHASE0-LOG.md) - lab bring-up: daemons, kernel-level link state, config persistence, OSPF interface-binding race, a single-node zebra failure, and the stable-image fix.
- [`docs/PHASE1-LOG.md`](docs/PHASE1-LOG.md) - snapshot tool design and verification.
- [`docs/PHASE2-LOG.md`](docs/PHASE2-LOG.md) - apply-and-verify a config change.
- [`docs/PHASE3-LOG.md`](docs/PHASE3-LOG.md) - verify-then-rollback, including a rollback-mechanism bug and the fix, and the control-plane-vs-data-plane finding.
- [`docs/PHASE4-LOG.md`](docs/PHASE4-LOG.md) - Batfish integration, its FRR/Cumulus boundary, and the self-built pre-flight validator.
- [`docs/PHASE5-LOG.md`](docs/PHASE5-LOG.md) - data-plane path verification via FIB walk and live traceroute, including a route-parsing bug and the path-shift detection test.
- [`docs/PHASE6-LOG.md`](docs/PHASE6-LOG.md) - declarative intent verification, the violation-detection test, and pipeline-usable exit codes.

## Repo layout

```
deploy.sh              # deploy the lab + self-heal FRR startup race
topology.clab.yml      # containerlab topology; binds configs into each node
snapshot.py            # Phase 1: read-only network state snapshot -> JSON
change.py              # Phase 2: apply + verify a config change
rollback_deploy.py     # Phase 3: verify-then-commit deploy with auto-rollback
preflight.py           # Phase 4: offline pre-flight change validation
verify_path.py         # Phase 5: data-plane path verification
verify_intent.py       # Phase 6: declarative intent verification
intent.yml             # Phase 6: declared desired state of the network
configs/
  daemons              # FRR daemon enablement (shared by all nodes)
  r1/frr.conf          # per-router config (loopback, interfaces, OSPF)
  r2/frr.conf
  r3/frr.conf
  r4/frr.conf
docs/
  PHASE0-LOG.md
  PHASE1-LOG.md
  PHASE2-LOG.md
  PHASE3-LOG.md
  PHASE4-LOG.md
  PHASE5-LOG.md
  PHASE6-LOG.md
snapshots/             # runtime output (gitignored)
baselines/             # runtime output (gitignored)
deploy_records/        # runtime output (gitignored)
bf_snapshot/           # Batfish working dir (gitignored)
```
