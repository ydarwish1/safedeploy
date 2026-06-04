# Phase 3 - Verify-then-commit with automatic rollback

Goal of Phase 3: apply a change only if the network stays healthy afterward, and
automatically restore the pre-change config if it does not. This is the core of
SafeDeploy. It combines Phase 1 (capture state) and Phase 2 (apply change) with
a health gate and a rollback path.

Outcome: achieved. rollback_deploy.py captures a baseline, applies a change,
runs a two-layer health check, keeps the change if healthy, and rolls back and
confirms recovery if not. Verified in both directions: a safe change is kept, a
breaking change is detected and reverted.

## Design

Fail-safe gate (modeled on Juniper commit confirmed): a change is kept only if
health is affirmatively verified within a timeout. Failed checks, a timeout, or
an error all trigger rollback. The default is to revert, not to keep.

Two-layer health check:
- Control plane: every router still has its expected Full OSPF adjacencies.
- Data plane: every router can still reach every other loopback.
The checks are reported separately so the failing layer is named.

Baseline-first ordering: the restore point is captured before any change is
applied. We do not change what we cannot restore.

Decision record: every run writes a JSON record (timestamp, change, decision,
reason, health before and after rollback) for audit and for the later dashboard.

## Issue found and fixed - the first rollback mechanism did not work

First attempt restored config with frrinit.sh reload. In testing, the detection
worked correctly (it caught a broken adjacency) but the restore failed:
"restored r1: FAILED" and the network stayed down.

Diagnosis: running the reload manually returned exit code 137 (128 + SIGKILL).
The reload process was being killed on this image (likely resource/runtime
related), so it never restored anything. Separately, frr-reload.py was rejected
earlier because on malformed input it computed a full-config DELETION - a
dangerous failure mode for a safety tool.

Fix: restore by replaying the saved baseline config through vtysh, which is
lightweight and was already proven reliable by the Phase 2 change path. Two
details mattered:
- Interface admin state: a shut interface must be explicitly re-enabled with
  'no shutdown', because an enabled interface has no config line to replay
  (enabled = absence of 'shutdown'). The restore re-enables every interface in
  the baseline before replaying config.
- Mechanism choice is deliberate: a restore whose worst case is predictable
  (replay) was chosen over mechanisms whose worst case is "wipe the config"
  (frr-reload) or "get killed" (frrinit reload).

After the fix: the breaking-change test showed "restored r1: ok" and "Rollback
verified - network recovered."

## A real result worth noting - control plane vs data plane

The breaking change (shutting r1 eth2) broke an OSPF adjacency but did NOT break
reachability: the ring rerouted and traffic still reached every loopback. The
health check reported control_plane failing and data_plane clean. The tool
rolled back on control-plane degradation even though a simple ping test would
have reported everything fine. This is the "succeeded but degraded" case the
project set out to catch, and the two-layer check surfaced it automatically.

## Verification (Phase 3 gate)

- Safe change (set OSPF cost): health stayed healthy, change kept, recorded.
- Breaking change (interface shutdown): control-plane failure detected, baseline
  restored, recovery re-verified, recorded as rolled_back.
- Lab confirmed back to all-Full adjacencies after the rollback.

## Notes carried forward

- Health check currently covers two layers (adjacency + reachability).
  Degradation detection (suboptimal path length, convergence time - the
  "succeeded but degraded" research direction) is the planned next extension.
- Rollback currently restores per-router baselines for the targeted routers.
  A multi-router change would capture and restore all targets the same way.
