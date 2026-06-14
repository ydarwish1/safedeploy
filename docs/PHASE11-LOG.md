# Phase 11 - Unified CLI, tests, CI, and live verification

Goal of Phase 11: make every phase usable from one entry point, lock the logic
behind continuous integration, and prove the whole pipeline end to end on the
live lab in a single captured run.

Outcome: achieved. One CLI fronts every phase, six suites run in CI on every
push, and a full end-to-end run on the lab is recorded in docs/verification-run.txt.

## What was built

- safedeploy.py - one CLI fronting every phase: snapshot, preflight, deploy,
  path, intent, inject, redteam, blast, status. Each subcommand routes to the
  existing tool and passes its exit code through unchanged, so every phase stays
  usable in scripts and in CI without duplicating logic.
- collect_status.py - writes a machine-readable status snapshot (the modeled
  topology plus the live intent result) to status/status.json, so the network's
  state can be captured in one file. A web console to render that snapshot is a
  future goal, not part of this phase.
- Six offline test suites - test_proposal, test_joint, test_gate, test_heal,
  test_redteam, test_blastradius. The device layer (docker/vtysh) and the agent
  backend (the Anthropic API) are mocked at module boundaries, so the suites run
  anywhere with no lab and no API key. That design is exactly what lets them run
  in CI.
- GitHub Actions runs the six suites on every push; an MIT license, a
  requirements.txt that pins the runtime dependencies, and a Makefile with one
  verb per workflow round out the repo.

## Live verification (the Phase 11 gate)

A single end-to-end run on the lab host, captured to docs/verification-run.txt:

1. Cold deploy of the four-node ring, every adjacency Full.
2. Intent 12/12.
3. All six offline suites pass.
4. inject - two changes safe alone, refused together, network intact.
5. redteam - 6/6 deadly combinations blocked, 4/4 safe allowed, 0 false verdicts.
6. blast - a ring shutdown graded ELEVATED, margin 2 -> 1, three new single
   points of failure.
7. chaos breaks a live link; the watcher heals it on the first attempt.
8. The live agent turns a plain-language goal into a proposal, the critic reviews
   it, and the gate commits it.
9. Lab reset, final intent 12/12.

Every capability claim in the README is backed by a line in that log.

## Notes carried forward

- The CLI keeps each phase a thin passthrough, so the proven tools stay the
  source of truth and the CLI never grows its own logic to drift.
- Known limitations are tracked in the README rather than hidden: BGP uptime
  parsing past 24 hours, the ring-specific adjacency constant, and the healer's
  repeat-on-retry behavior.
- An operations dashboard that renders the status snapshot is a planned next
  step, deliberately left out until it can be built and verified properly.
