# Phase 8 - The convergence gate

Goal of Phase 8: catch a combination of changes that are each safe on their own
but break the network together. The Phase 3 pipeline verifies one change at a
time, which has a blind spot: shutting one ring link is survivable, shutting
another is survivable, and shutting both strands a router. Each passes review
alone. The convergence gate evaluates the combined end-state of every queued
change before any of them is applied.

Outcome: achieved. Two changes that each pass alone are refused as a batch, with
nothing applied and the live network untouched.

## What was built

- proposal.py - every change enters as structured data (action, router,
  interface, optional value, rationale), not raw config. Malformed proposals are
  rejected at construction: a bad action, a cost without a value, a shutdown with
  a value, an out-of-range cost, a missing target. Field names mirror
  preflight(action, router, interface) exactly, so a Proposal bridges straight
  into the existing model.
- joint_preflight.py - the core of the idea: layer every queued change onto ONE
  copy of the topology model and check the combined end-state for partition,
  instead of checking each change against the untouched network.
- gate.py - the queue and the single write authority. It runs the joint check,
  refuses the whole batch if the combination is unsafe (even when every member
  is safe alone), commits the survivors one at a time through the Phase 3
  verify-then-rollback pipeline, and halts the rest of the batch if any commit
  rolls back. Every decision is logged to status/gate_log.json.
- inject.py - the demonstration: submit two changes that pass alone, watch the
  gate refuse them together, confirm nothing was applied, and re-verify intent.

## Design choices

- Refuse the whole batch, not part of it. If a set of changes is unsafe
  together, the safe-looking members are still rejected, because the danger is
  in the combination.
- Serialize commits even for proposals submitted concurrently. Lost parallelism
  costs milliseconds; a corrupted control plane costs an outage.
- Halt on rollback. If a commit inside a batch rolls back, the rest is stopped,
  because the network no longer matches the state the joint check assumed.
  Continuing would validate later changes against a stale assumption.
- The gate imports preflight.py and rollback_deploy.py rather than modifying
  them. The verified Phase 0-7 foundation stays frozen; the gate is additive.

## Verification (Phase 8 gate)

- Offline: test_proposal (schema validation, seven cases), test_joint (the
  partition math: each ring link removed alone stays connected, both together
  partition), test_gate (a SAFE batch commits, an UNSAFE combination is blocked
  with nothing committed, the batch halts after a rollback).
- Live: inject.py on the lab reported SAFE and SAFE for the two changes alone,
  UNSAFE for the batch, committed [], "GATE BLOCKED THE FAULT - NETWORK INTACT",
  and intent stayed 12/12.

## Notes carried forward

- The joint check models partition (connectivity). A degradation-aware joint
  check (path length, convergence) would reuse the same one-copy-of-the-model
  pattern.
- The decision ledger (status/gate_log.json) records every gate verdict for
  later inspection.
