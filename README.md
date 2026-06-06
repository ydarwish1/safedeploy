# SafeDeploy

Automated, verified network change deployment with rollback, built on a containerized OSPF + BGP lab.

**Status:** In active development. Phases 0 through 7 complete: a reproducible 4-node FRR network running OSPF with an iBGP overlay, a read-only state-snapshot tool, a config-change engine, an automatic verify-then-rollback deployment pipeline, an offline pre-flight change validator, data-plane path verification, and a declarative intent-verification layer covering both protocols.

> **Note (in progress):** I'm building the next major phase, a multi-change
> "convergence gate" that checks several proposed changes together, not just one at
> a time, so changes that each look safe alone but break the network in combination
> get caught before they're applied. The longer-term goal is to let multiple
> autonomous agents propose changes concurrently while this gate keeps them safe.
> This is a larger build, so the repo may sit at Phase 7 while that work is underway.

## Why

Network changes often go out without a way to predict their effect, and recovery after a bad change is manual and slow. SafeDeploy applies software deployment discipline (pre-change validation, post-change verification, automatic rollback) to routing changes. It also takes on a harder question most rollback systems punt on: how to tell a change that succeeded from one that succeeded but quietly degraded the network.

## Architecture

Four FRRouting nodes in a ring (r1 through r4) running OSPF as the underlay, with a full iBGP mesh (AS 65000) over their loopbacks as the overlay, deployed via Containerlab on a single EC2 instance. OSPF provides loopback reachability; BGP rides on top and resolves its next-hops through the OSPF-learned routes, the standard IGP-underlay / BGP-overlay model. A Python control layer drives changes.

A change flows through these steps: pre-flight validate the change offline against a topology model, snapshot current state, apply the change, verify control plane (adjacencies and BGP sessions), data plane (reachability), forwarding path (traffic takes the expected route), and overall intent (the declared desired state still holds), and roll back to the snapshot if verification fails.

## Current state

Working today:

- **Phase 0** - 4-node FRR ring, reproducible from \`topology.clab.yml\` and \`configs/\` via \`./deploy.sh\`. OSPF converges across all four routers (every adjacency Full), verified end-to-end. Pinned to a stable FRR image; \`deploy.sh\` self-heals any FRR startup race.
- **Phase 1** - \`snapshot.py\` captures each router's full state (config, OSPF neighbors, interfaces, routes) to timestamped JSON. Read-only by construction; handles unreachable nodes gracefully.
- **Phase 2** - \`change.py\` applies a real config change (OSPF interface cost) and verifies it landed in the running config and shifted path selection.
- **Phase 3** - \`rollback_deploy.py\` is the core: a verify-then-commit pipeline. It captures a baseline, applies a change, runs a health check (control plane: adjacencies Full; data plane: every loopback reachable) within a fail-safe timeout, keeps the change only if health is affirmatively verified, and otherwise restores the baseline and re-verifies recovery. Every run writes a structured decision record.
- **Phase 4** - \`preflight.py\` validates a change offline before it touches the network. It builds a graph model of the topology from live config and simulates the change to predict whether the network would stay connected, catching partitioning changes before they are applied.
- **Phase 5** - \`verify_path.py\` verifies the data-plane forwarding path: it reconstructs the path traffic will take from each router's FIB (handling equal-cost multipath) and cross-checks it with a live traceroute, optionally against an expected path. This catches changes that leave the network reachable but silently reroute traffic.
- **Phase 6** - \`verify_intent.py\` inverts the model: the network's desired state is declared in \`intent.yml\` (required adjacencies, reachability within a hop budget, exact forwarding paths) and the tool proves whether live reality conforms, reporting each assertion PASS/FAIL with evidence and exiting non-zero on any violation.
- **Phase 7** - a full iBGP mesh (AS 65000) over the OSPF underlay: every router peers with the other three over loopbacks, a test prefix is originated and propagates across the mesh (next-hop resolved through OSPF), and the config is baked in so the whole two-layer network comes up from a cold deploy. Intent verification was extended with a BGP check, so \`verify_intent.py\` now covers both protocols.

Planned: deploy dashboard, fault injection / self-healing, and a single CLI that unifies the phases with CI-driven validation.

## Design notes

- Runs on FRR (open-source Linux routing), not a vendor NOS. Protocol behavior and automation patterns are real; vendor-specific quirks are out of scope by design.
- The tooling uses \`docker exec\` against the containerlab nodes today. The connection layer is isolated so a production SSH/Netmiko collector could drop in without changing the rest of the tool.
- Rollback uses full-config replay through vtysh, chosen after testing showed heavier reload mechanisms were unreliable on this image (documented in the Phase 3 log).
- Pre-flight validation is a self-built topology model. Batfish was evaluated for this and modeled the lab topology correctly, but parses FRR through its Cumulus vendor model, which expects a config layout this pure-FRR lab does not produce; that boundary is documented in the Phase 4 log, and the self-built model keeps fidelity to the actual configs.
- Path verification reads forwarding behavior two independent ways (the routers' own FIB and a live traceroute) so the model and reality are cross-checked rather than trusted blindly.
- BGP peers on loopbacks, not link addresses, so a session survives a link failure as long as OSPF still has a path to the peer's loopback.
- Intent verification is declarative: desired state lives in a small YAML file, and the verifier reuses the reachability, path, control-plane, and BGP checks as primitives. New intent types are added as new check functions without changing the structure.
- "Rollback on failure" requires defining failure. The checks now cover OSPF adjacencies, BGP sessions, data-plane reachability, forwarding path, and declared intent. Convergence-timing detection is the planned research direction.

## Engineering logs

Each phase is documented honestly, including the bugs and how they were diagnosed and fixed.

- [\`docs/PHASE0-LOG.md\`](docs/PHASE0-LOG.md) - lab bring-up and the stable-image fix.
- [\`docs/PHASE1-LOG.md\`](docs/PHASE1-LOG.md) - snapshot tool design and verification.
- [\`docs/PHASE2-LOG.md\`](docs/PHASE2-LOG.md) - apply-and-verify a config change.
- [\`docs/PHASE3-LOG.md\`](docs/PHASE3-LOG.md) - verify-then-rollback, the rollback-mechanism fix, and the control-plane-vs-data-plane finding.
- [\`docs/PHASE4-LOG.md\`](docs/PHASE4-LOG.md) - Batfish evaluation, its FRR/Cumulus boundary, and the self-built pre-flight validator.
- [\`docs/PHASE5-LOG.md\`](docs/PHASE5-LOG.md) - data-plane path verification via FIB walk and live traceroute.
- [\`docs/PHASE6-LOG.md\`](docs/PHASE6-LOG.md) - declarative intent verification and pipeline-usable exit codes.
- [\`docs/PHASE7-LOG.md\`](docs/PHASE7-LOG.md) - iBGP overlay on the OSPF underlay, route propagation, cold-boot proof, and the BGP intent check.

## Repo layout

```
deploy.sh              # deploy the lab + self-heal FRR startup race
topology.clab.yml      # containerlab topology; binds configs into each node
snapshot.py            # Phase 1: read-only network state snapshot -> JSON
change.py              # Phase 2: apply + verify a config change
rollback_deploy.py     # Phase 3: verify-then-commit deploy with auto-rollback
preflight.py           # Phase 4: offline pre-flight change validation
verify_path.py         # Phase 5: data-plane path verification
verify_intent.py       # Phase 6/7: declarative intent verification (OSPF + BGP)
intent.yml             # declared desired state of the network
configs/               # per-router frr.conf (loopback, interfaces, OSPF, BGP) + daemons
docs/                  # per-phase engineering logs (PHASE0-7)
snapshots/             # runtime output (gitignored)
baselines/             # runtime output (gitignored)
deploy_records/        # runtime output (gitignored)
```
