# Phase 9 - Agentic layer and the self-healing loop

Goal of Phase 9: let AI propose and repair network changes while keeping AI
structurally out of the write path, then close the loop so the network recovers
from a real fault on its own. The principle is strict and carried over from the
roadmap: agents never write to a device; they emit proposals, and the gate alone
decides what is applied, verified, and rolled back.

Outcome: achieved. A real fault injected outside the gate is detected, diagnosed
by the AI healer, repaired through the gate, and re-verified green, with no human
in the loop.

## What was built

- agents.py - three Claude roles, each backed by the Anthropic API: a proposer
  (plain-language goal -> Proposal), a critic (Proposal -> advisory verdict), and
  a healer (failure evidence -> repair Proposal). Each role answers through
  function calling: the model is forced (tool_choice) to call a tool whose schema
  we define, so its output is schema-checked structured data, not free text to
  parse. The only exit any role has to the network is gate.submit(); there is no
  function an agent can call that writes to a device.
- The "enable" action - added through the proposal schema and the gate so the
  healer has a repair verb (clear an admin shutdown). It can only add capacity,
  so it is topologically safe by construction.
- chaos.py - real fault injection. It admin-downs a survivable ring link OUTSIDE
  the gate, the way a real failure arrives, after a survivability pre-check so it
  refuses to create an unsurvivable fault.
- watcher.py - the loop. It polls intent; on violation it collects evidence (the
  failing assertions plus the admin-down interfaces read from running config),
  asks the healer for a repair, passes it through critic review and the gate, and
  re-verifies, capped at three attempts so a wrong fix can never loop forever.
  Every outcome is written to status/heal_log.json.

## Issue found and fixed - a convergence-timing race rolled back a correct fix

The first live heal sometimes rolled back a change that was actually correct.
Re-enabling an interface starts a fresh OSPF adjacency (default hello 10s, dead
40s), which can take roughly 40-50s to reach Full. The post-change health check
in rollback_deploy.py used a 45s window, which expired mid-convergence: it read
the adjacency as still forming (1/2 Full), judged the network UNHEALTHY, and
rolled back a good change. The retry loop recovered on the next attempt, but a
correct change should not need a retry.

Diagnosis: the live intent check named exactly the two assertions still failing
during convergence, and the gate's own health check disagreed with the longer
intent check - the "converged vs still converging" timing gap noted as far back
as the Phase 3 log.

Fix: widen wait_for_health to 90s (about twice the dead interval), so health is
judged only after the network has had time to settle. Any change that reaches
this stage has already passed the gate's joint partition pre-flight, so a longer
wait only ever lets a legitimate change converge; it never lets an unsafe one
through. After the fix the heal lands on the first attempt with no rollback,
verified live across three different broken links (r1 eth1, r2 eth2, r3 eth2).

## A second change worth noting - structured output

The agent output path was moved from regex-scraped free text to function
calling. The proposer, critic, and healer now return schema-checked tool input
instead of prose that had to be pattern-matched, with SDK retries on transient
API errors and a log line per call. The Proposal validation stays as a second
safety net behind the schema.

## Verification (Phase 9 gate)

- Offline: test_heal proves the whole chain with a mocked Claude and a fake lab:
  intent violated -> healer proposes enable -> critic approves -> gate commits ->
  intent satisfied.
- Live: chaos.py then watcher.py --once on the lab. The watcher detected the
  violation, the healer proposed the enable, the gate committed it, and intent
  returned to 12/12 - on the first attempt after the timing fix.

## Notes carried forward

- The critic is advisory by design. Its verdict informs; the gate decides.
- The healer reasons from evidence each attempt. If it infers "link down" from
  path evidence after the link is already back up, it can repeat the same
  proposal across retries - a place for de-duplicating already-applied fixes.
- Agents are barred from the write path by construction, not policy, which is the
  property the Phase 10 red team then audits.
