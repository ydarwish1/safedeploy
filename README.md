# SafeDeploy

[![tests](https://github.com/ydarwish1/safedeploy/actions/workflows/tests.yml/badge.svg)](https://github.com/ydarwish1/safedeploy/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![FRRouting](https://img.shields.io/badge/FRRouting-OSPF%20%2B%20iBGP-orange)
![license](https://img.shields.io/badge/license-MIT-green)

A convergence gate for network change: every change enters as structured data, gets judged jointly with everything else in flight, is committed serially with health verification and automatic rollback, and is continuously proven against a declared intent. Built on a containerized OSPF + BGP lab, with adversarial auditing that exhaustively proves the gate's verdicts and a risk forecaster that grades every change by what it does to the network's ability to survive the next failure.

**Status:** Phases 0 through 11 are complete and verified on the live lab. The whole pipeline was proven end to end in a single captured run on 2026-06-14 - cold deploy, intent, the convergence gate, fault injection, self-healing, adversarial audit, blast-radius forecast, and the live agent - recorded in [docs/verification-run.txt](docs/verification-run.txt). Each phase has its own engineering log under `docs/`.

## Why

Network changes often go out without a way to predict their effect, and recovery after a bad change is manual and slow. SafeDeploy applies software deployment discipline (pre-change validation, post-change verification, automatic rollback) to routing changes, then takes on three harder questions most change tooling punts on:

1. How do you tell a change that succeeded from one that succeeded but quietly degraded the network?
2. How do you catch a combination of changes that are each safe alone but break the network together? Single-change validation has a blind spot: shutting one ring link is survivable, shutting another ring link is survivable, and shutting both strands a router. Each change passes review on its own.
3. How do you know what a change does to the network's ability to survive the *next* failure, before you commit it?

The convergence gate answers the second question by validating the combined end-state of every queued change before any of them is applied. The blast-radius forecaster answers the third with exact graph analysis. And the red team audit answers the question behind both: how do you know the gate itself has no blind spots?

## Sixty-second tour

Every workflow is one verb (`make help` lists them all; each target wraps a plain `python3` command if you prefer to run them directly):

```
make test       six offline suites - schema, partition math, gate mechanics,
                healing loop, adversarial audit, impact math (no lab needed)
make lab        deploy the 4-node FRR ring from cold
make verify     prove the live network matches its declared intent (12/12)
make block      two changes pass review alone, the gate refuses them together
make redteam    every failure combination vs the gate: expects 0 false verdicts
make chaos      actually break a survivable link, no permission asked
make heal       the watcher detects the fault and repairs it through the gate
```

## Architecture

Four FRRouting nodes in a ring (r1 through r4) running OSPF as the underlay, with a full iBGP mesh (AS 65000) over their loopbacks as the overlay, deployed via Containerlab on a single EC2 instance. OSPF provides loopback reachability; BGP rides on top and resolves its next-hops through the OSPF-learned routes, the standard IGP-underlay / BGP-overlay model. A Python control layer drives changes.

A change flows through these layers:

1. **Proposal.** Every change enters as structured data (`proposal.py`), not raw config: an action, a target, and a rationale. Malformed proposals are rejected at construction.
2. **Convergence gate.** Proposals queue at the gate (`gate.py`). The gate runs a joint pre-flight (`joint_preflight.py`): all queued changes are applied to one copy of the topology model and the combined result is checked for partition. A batch that is unsafe together is refused whole, even if every member passes alone.
3. **Serial commit with verification.** Surviving proposals commit one at a time through the existing pipeline: snapshot baseline, apply, verify control plane and data plane within a fail-safe timeout, keep only on affirmative health, otherwise restore the baseline and re-verify recovery. If any commit rolls back, the gate halts the rest of the batch, because the network no longer matches the state the joint check assumed.
4. **Continuous intent verification.** The desired state of the network is declared in `intent.yml`; `verify_intent.py` proves whether live reality conforms, with evidence per assertion.

On top of the gate sits an agent layer (`agents.py`): a proposer that turns a plain-language goal into a Proposal, a critic that reviews proposals and returns an advisory verdict, and a healer that reads failure evidence and proposes a repair. The agents are backed by Claude through the Anthropic API and answer through function calling, so their output is schema-checked structured data rather than free text. None of them can touch a device. Their only exit is `gate.submit()`. The constraint is structural, not policy: there is no code path from an agent to a router, so the final authority is always deterministic graph math plus live health verification, never a model's opinion.

The self-healing loop ties it together. `chaos.py` injects a real fault (admin-downs a survivable ring link, outside the gate, the way a real failure would arrive). `watcher.py` monitors intent continuously; on violation it collects evidence, asks the healer for a repair, passes it through critic review and the gate, and re-verifies, with a hard cap on attempts so a wrong fix can never loop forever.

Two analysis tools interrogate the safety system itself:

- **Red team** (`redteam.py`). An exhaustive adversarial audit: enumerate every combination of link failures up to a chosen depth, find every combination that partitions the model, then replay each through the gate's own joint pre-flight and check the verdict both ways. Dangerous combinations must be refused, safe changes must be allowed; the exit code is nonzero on any false verdict. On the ring it independently rediscovers a graph-theory fact: a cycle survives any single edge loss and is disconnected by any two, so it finds exactly 4 safe singles and 6 minimal deadly pairs, and verifies the gate blocks 6 of 6.
- **Blast radius** (`blastradius.py`). A quantified impact forecast per change, computed before anything is committed: the survivability margin (edge connectivity, the minimum number of simultaneous link failures that can partition the network), every link that becomes a single point of failure after the change, and every router pair whose shortest forwarding path shifts. Changes are graded LOW (auto-commit), ELEVATED (survivable but fragile, human ack), or UNSAFE (refuse). Example: shutting one ring link grades ELEVATED with the margin dropping from 2 to 1 and three new single points of failure.

## Current state

All phases verified on the live lab. Each links to its engineering log.

- **Phase 0** - 4-node FRR ring, reproducible from `topology.clab.yml` and `configs/` via `./deploy.sh`. OSPF converges across all four routers (every adjacency Full), verified end-to-end. Pinned to a stable FRR image; `deploy.sh` self-heals any FRR startup race.
- **Phase 1** - `snapshot.py` captures each router's full state (config, OSPF neighbors, interfaces, routes) to timestamped JSON. Read-only by construction; handles unreachable nodes gracefully.
- **Phase 2** - `change.py` applies a real config change (OSPF interface cost) and verifies it landed in the running config and shifted path selection.
- **Phase 3** - `rollback_deploy.py` is the core: a verify-then-commit pipeline. It captures a baseline, applies a change, runs a health check (control plane: adjacencies Full; data plane: every loopback reachable) within a fail-safe timeout, keeps the change only if health is affirmatively verified, and otherwise restores the baseline and re-verifies recovery. Every run writes a structured decision record.
- **Phase 4** - `preflight.py` validates a change offline before it touches the network. It builds a graph model of the topology from live config and simulates the change to predict whether the network would stay connected, catching partitioning changes before they are applied.
- **Phase 5** - `verify_path.py` verifies the data-plane forwarding path: it reconstructs the path traffic will take from each router's FIB (handling equal-cost multipath) and cross-checks it with a live traceroute, optionally against an expected path. This catches changes that leave the network reachable but silently reroute traffic.
- **Phase 6** - `verify_intent.py` inverts the model: the network's desired state is declared in `intent.yml` (required adjacencies, reachability within a hop budget, exact forwarding paths) and the tool proves whether live reality conforms, reporting each assertion PASS/FAIL with evidence and exiting non-zero on any violation.
- **Phase 7** - a full iBGP mesh (AS 65000) over the OSPF underlay: every router peers with the other three over loopbacks, a test prefix is originated and propagates across the mesh (next-hop resolved through OSPF), and the config is baked in so the whole two-layer network comes up from a cold deploy. Intent verification was extended with a BGP check, so `verify_intent.py` now covers both protocols.
- **Phase 8** - the convergence gate: `proposal.py` (every change is validated structured data), `joint_preflight.py` (layer all queued changes onto one copy of the model and check the combined end-state for partition), `gate.py` (queue, refuse-whole-batch on a dangerous combination, serial commit through Phase 3, halt the batch on any rollback, decision ledger), and `inject.py` (two changes safe alone, refused together, nothing applied). See [docs/PHASE8-LOG.md](docs/PHASE8-LOG.md).
- **Phase 9** - agentic layer and self-healing: `agents.py` (proposer, critic, healer via Claude function calling, structurally barred from the write path), the `enable` repair action (adds capacity only, so it is topologically safe), `chaos.py` (real fault injection outside the gate), and `watcher.py` (detect violation, gather evidence, drive healer through critic and gate, re-verify, max three attempts). This phase also fixed a convergence-timing race that could roll back a correct fix, and moved the agent output from regex-scraped text to function calling. See [docs/PHASE9-LOG.md](docs/PHASE9-LOG.md).
- **Phase 10** - adversarial audit and blast radius: `redteam.py` (every failure combination replayed through the gate, zero false verdicts, rediscovers the 2-edge-connectivity of a cycle) and `blastradius.py` (survivability margin, new single points of failure, and flow shifts per change, graded LOW / ELEVATED / UNSAFE). Both pure stdlib graph math, verified against hand-computed facts. A repeated-run check also caught and fixed a real nondeterminism bug in the red team's component ordering. See [docs/PHASE10-LOG.md](docs/PHASE10-LOG.md).
- **Phase 11** - unified CLI, tests, CI, and the live-verification run: `safedeploy.py` (one entry point fronting every phase, exit codes passed through), `collect_status.py` (writes a machine-readable status snapshot to JSON), six offline suites with the device layer and agent backend mocked at module boundaries, GitHub Actions running them on every push, and a captured end-to-end run in [docs/verification-run.txt](docs/verification-run.txt). See [docs/PHASE11-LOG.md](docs/PHASE11-LOG.md).

## Known limitations

Documented limits:

- The lab is four nodes. The red team and blast radius scale with topology size; on a ring this small their results are nearly hand-computable, and the value is the method, which a larger mesh would make non-trivial. `redteam --depth 3` hunts triples once a network is large enough to have them.
- BGP uptime parsing in `verify_intent.py` recognizes FRR's `HH:MM:SS` uptime format and would miscount a session that has been up longer than about 24 hours (FRR switches to a `1d02h` format). Harmless in a start/stop lab workflow; the clean fix is FRR's JSON output.
- `EXPECTED_ADJACENCIES` is a whole-network constant (2) that assumes the ring. A topology where a router legitimately has one neighbor would need it generalized.
- The healer reasons from fresh evidence each attempt and can re-propose an already-applied fix across retries; de-duplicating applied fixes is a known refinement.

## Direction

This is where network automation is heading: agents that propose and reason about changes, with deterministic safety systems keeping them in check. The deliberate next steps from here, stated as direction rather than a claim the project has arrived:

- **Operations dashboard.** A web console that renders the status snapshot `collect_status.py` already writes - topology, intent health, and the gate and heal ledgers at a glance. The data layer exists; the console is the next build.
- **Concurrent proposers.** The gate already serializes and joint-checks; the natural extension is multiple autonomous agents proposing changes at once while the gate keeps the combined set safe.
- **Degradation-aware verification.** Convergence timing and path-length regressions, the "succeeded but degraded" research direction, layered onto the joint check using the same one-copy-of-the-model pattern.

## Design notes

- Runs on FRR (open-source Linux routing), not a vendor NOS. Protocol behavior and automation patterns are real; vendor-specific quirks are out of scope by design.
- The tooling uses `docker exec` against the containerlab nodes today. The connection layer is isolated so a production SSH/Netmiko collector could drop in without changing the rest of the tool.
- Rollback uses full-config replay through vtysh, chosen after testing showed heavier reload mechanisms were unreliable on this image (documented in the Phase 3 log).
- Pre-flight validation is a self-built topology model. Batfish was evaluated and modeled the lab correctly, but parses FRR through its Cumulus vendor model, which expects a config layout this pure-FRR lab does not produce; that boundary is documented in the Phase 4 log.
- Path verification reads forwarding behavior two independent ways (the routers' own FIB and a live traceroute) so the model and reality are cross-checked rather than trusted blindly.
- BGP peers on loopbacks, not link addresses, so a session survives a link failure as long as OSPF still has a path to the peer's loopback.
- Intent verification is declarative: desired state lives in a small YAML file, and the verifier reuses the reachability, path, control-plane, and BGP checks as primitives.
- The gate serializes commits even for proposals submitted concurrently. Lost parallelism costs milliseconds; a corrupted control plane costs an outage.
- Agents are kept out of the write path by construction, not by policy. They emit proposals through function calling; the gate alone decides what is applied, verified, and rolled back. The critic's verdict is advisory on purpose.
- Proven files stay frozen. The gate imports from `preflight.py` and `rollback_deploy.py` rather than modifying them, so every new layer is additive and the verified foundation never churns. The one change to a frozen file, widening the health-check window for OSPF reconvergence, is documented in the Phase 9 log.
- The safety system is audited adversarially, not assumed: the red team holds the gate to zero false verdicts, exhaustively, and runs in CI on every push.
- The healer is given evidence, not answers: the failing assertions and the admin-down interfaces it must reason over. Its repair still has to survive the critic, the joint pre-flight, and post-commit health verification.

## Engineering logs

Each phase is documented honestly, including the bugs and how they were diagnosed and fixed.

- [`docs/PHASE0-LOG.md`](docs/PHASE0-LOG.md) - lab bring-up and the stable-image fix.
- [`docs/PHASE1-LOG.md`](docs/PHASE1-LOG.md) - snapshot tool design and verification.
- [`docs/PHASE2-LOG.md`](docs/PHASE2-LOG.md) - apply-and-verify a config change.
- [`docs/PHASE3-LOG.md`](docs/PHASE3-LOG.md) - verify-then-rollback, the rollback-mechanism fix, and the control-plane-vs-data-plane finding.
- [`docs/PHASE4-LOG.md`](docs/PHASE4-LOG.md) - Batfish evaluation, its FRR/Cumulus boundary, and the self-built pre-flight validator.
- [`docs/PHASE5-LOG.md`](docs/PHASE5-LOG.md) - data-plane path verification via FIB walk and live traceroute.
- [`docs/PHASE6-LOG.md`](docs/PHASE6-LOG.md) - declarative intent verification and pipeline-usable exit codes.
- [`docs/PHASE7-LOG.md`](docs/PHASE7-LOG.md) - iBGP overlay on the OSPF underlay, route propagation, cold-boot proof, and the BGP intent check.
- [`docs/PHASE8-LOG.md`](docs/PHASE8-LOG.md) - the convergence gate: structured proposals, joint pre-flight, refuse-whole-batch, halt-on-rollback.
- [`docs/PHASE9-LOG.md`](docs/PHASE9-LOG.md) - agentic layer and self-healing, the convergence-timing fix, and the move to function-calling output.
- [`docs/PHASE10-LOG.md`](docs/PHASE10-LOG.md) - exhaustive adversarial audit and blast-radius forecasting, and the nondeterminism fix.
- [`docs/PHASE11-LOG.md`](docs/PHASE11-LOG.md) - unified CLI, tests, CI, and the captured live-verification run.
- [`docs/LIVE-VERIFICATION.md`](docs/LIVE-VERIFICATION.md) - the closing runbook: every command and its expected output.
- [`docs/verification-run.txt`](docs/verification-run.txt) - the captured end-to-end live run.

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
proposal.py            # Phase 8: change schema - every change is structured data
joint_preflight.py     # Phase 8: gate core - batch check on one graph copy
gate.py                # Phase 8: the gate - queue, joint judgment, serial commits
inject.py              # Phase 8: prevention demo - refuse a safe-alone/bad-together batch
agents.py              # Phase 9: proposer / critic / healer; only exit is gate.submit()
chaos.py               # Phase 9: recovery demo - inject a real (survivable) fault
watcher.py             # Phase 9: self-healing loop - detect, diagnose, repair via the gate
redteam.py             # Phase 10: exhaustive adversarial audit - zero false verdicts or exit 1
blastradius.py         # Phase 10: impact forecast - survivability margin, SPOFs, flow shifts
safedeploy.py          # Phase 11: unified CLI fronting every phase
collect_status.py      # Phase 11: writes a status snapshot to status/status.json
termstyle.py           # terminal styling for the demo surfaces
verify_all.sh          # one-shot end-to-end verification run (captures to docs/)
test_*.py              # six offline suites (schema, partition math, gate,
                       # healing, red team, blast radius)
Makefile               # one verb per workflow (make help)
requirements.txt       # pyyaml + anthropic
configs/               # per-router frr.conf (loopback, interfaces, OSPF, BGP) + daemons
docs/                  # per-phase engineering logs + runbook + captured live run
.github/workflows/     # CI: all six suites on every push
status/ snapshots/ baselines/ deploy_records/   # runtime output (gitignored)
```

Licensed under MIT.
