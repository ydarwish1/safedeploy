# Phase 1 - Build & Verification Log

Goal of Phase 1: build a read-only tool that captures the current state of every
router in the lab and saves it as a timestamped JSON snapshot. This snapshot is
the known-good baseline that later phases compare against and roll back to. No
changes are made to the network in this phase; it only reads.

Outcome: achieved. `snapshot.py` captures all four routers, saves timestamped
JSON plus a stable `latest.json`, enforces read-only access in code, and handles
unreachable nodes without crashing. Verified against the live lab including a
deliberate node-failure test.

## Design decisions

Connection method: the tool reaches each router with `docker exec ... vtysh`
rather than SSH/Netmiko. For a containerlab setup this is the reliable choice and
keeps Phase 1 focused on the logic (read, structure, save) instead of SSH setup.
The connection call is isolated in a single function (`run_vtysh`), so a
production SSH/Netmiko collector can be dropped in later without touching the rest
of the tool. This mirrors the simulator-vs-live separation used elsewhere in the
portfolio.

Output format: structured JSON, not plain text. Later phases need to compare and
diff snapshots programmatically, which JSON supports and flat text does not. Each
run writes a timestamped file (history) and overwrites `latest.json` (a stable
pointer to the most recent known-good state for later phases to load).

Read-only by construction: `run_vtysh` refuses any command that does not start
with `show`. The snapshotter cannot change a device even if a bad command were
added later. This enforced-by-design safety is the same philosophy SafeDeploy is
built to demonstrate, so it appears even in the read-only phase.

Graceful partial failure: if a router is unreachable, its error is recorded in an
`errors` list and the snapshot still saves with the other routers intact. A
partial known-good baseline with recorded errors is more useful than no snapshot.
The process returns a non-zero exit code if any router was unreachable, so later
automation can refuse to proceed on an incomplete snapshot.

## What is captured per router

- running configuration (`show running-config`)
- OSPF neighbors (`show ip ospf neighbor`)
- OSPF interface detail (`show ip ospf interface`)
- routing table (`show ip route`)
- interface summary (`show interface brief`)

## Issue found and fixed - wrong OSPF interface command

Symptom: the `ospf_interfaces` field came back as `No such interface name` on
every router, an error string rather than data.

Root cause: the command `show ip ospf interface brief` is not valid on this FRR
version (8.4_git). The `brief` variant is not supported here.

Fix: changed the command to `show ip ospf interface`, which returns full
per-interface OSPF state (interface up/down, address, area, cost, timers,
neighbor count). Confirmed the field then contained real data.

Lesson: validate that every collected command actually returns data, not just
that the tool runs without crashing. A snapshot with a silently broken field is
not a complete snapshot. Capturing the error string instead of crashing was the
correct behavior; the fix was to use the right command.

## Verification (Phase 1 gate)

- Ran `snapshot.py` against the live lab: reported 4 routers, 4 reachable, 0 with
  errors, and wrote a timestamped file plus `latest.json`.
- Validated the saved file is well-formed JSON and contains all four routers.
- Failure-path test: stopped one router (`docker stop clab-safedeploy-r4`), ran
  the snapshot, and confirmed it reported 3 reachable, 1 with errors and still
  saved a usable snapshot rather than crashing. Restarted the node and confirmed
  it returned to 4 reachable, 0 with errors.
- Confirmed the `ospf_interfaces` field contains real interface detail after the
  command fix.

## Notes carried forward

- The snapshot currently stores raw command text per field. A future phase can
  add structured parsing (for example, a list of neighbors with state) on top of
  the raw capture, without changing how snapshots are taken. Raw text is retained
  regardless so nothing is lost to a parser bug.
- `snapshots/` is gitignored; snapshot output is runtime data, not source. A
  single sanitized example snapshot could be committed later to show output shape.
