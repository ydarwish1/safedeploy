# SafeDeploy Roadmap

## Where the project is now
Phases 0-7 complete: a reproducible 4-node FRR lab (OSPF underlay + iBGP
overlay), read-only snapshots, a config-change engine, verify-then-rollback,
offline pre-flight validation, data-plane path verification, and declarative
intent verification across both protocols.

## Next: the convergence gate
Today the pipeline verifies one change at a time. The convergence gate evaluates
several proposed changes *together*, so combinations that each pass individually
but partition or degrade the network jointly are caught before any are applied.

**How it works (planned):**
- Changes enter as structured *intents* (a proposed change as data, not raw config).
- The gate queues intents and commits one at a time, even when proposed
  concurrently. Lost parallelism costs milliseconds; a corrupted control plane
  costs an outage.
- Before committing a batch, the gate runs a *joint* check: it layers all queued
  intents onto the topology model and verifies the combined end-state. Each
  surviving change then still goes through the existing per-change
  verify-then-rollback pipeline.

**First milestone:** hand-fire two intents that each pass alone but partition the
network together, and show the gate catching the bad combination. This proves the
core idea with no agents involved.

## Longer term: safe multi-agent automation
The goal is to let multiple autonomous agents propose changes concurrently while
the gate keeps them safe. The design principle is strict:

**Agents never write to the network.** They emit intents; the gate alone decides
what is applied, verified, and rolled back. There is no code path from an agent to
a device, so AI is out of the write path by construction, not by policy. This
extends NetPilot's principle (the LLM is barred from the write path) from
diagnosis to change.

## Direction and learning goal
This is where network automation is heading: AI agents that can propose and
reason about network changes, with humans and safety systems keeping them in
check. I'm building toward that intentionally, starting with the convergence
gate. This isn't a claim the project is there yet; far from it, but it's the
direction I'm deliberately working toward!

## Status log
- *2026-06-08* - Roadmap created; designing the intent schema and joint-check
  extension to preflight.
