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
I'm using Cisco's CCIE Automation v1.2 blueprint, Domain 1, Objective 1.6,
"Design a network automation solution that leverages AI to provide agentic
capabilities, conversational interfaces, and/or data processing," as a north
star for where I'm taking this project, this is where the future is heading!
This isn't a claim that the project meets an expert-level standard; in fact
far from it, but it's the direction I'm deliberately building toward!
Reference: https://ccie-automation.com/blueprint

## Status log
- *2026-06-08* - Roadmap created; designing the intent schema and joint-check
  extension to preflight.
