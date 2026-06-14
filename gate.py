#!/usr/bin/env python3
"""
SafeDeploy - Convergence Gate.

The single authority that decides what touches the network. Proposals are
submitted to a queue; the gate judges the WHOLE batch with joint_preflight,
and only if the combined end-state is safe does it commit, one proposal at a
time, through the existing Phase 3 verify-then-rollback pipeline.
Agents (later) may only call submit(); there is no other path to a device.

Every gate decision is also appended to status/gate_log.json as a durable
record of the gate's history.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from joint_preflight import joint_preflight
from rollback_deploy import (deploy, apply_ospf_cost, apply_interface_shutdown,
                             vtysh)

STATUS_DIR = Path("status")
GATE_LOG = STATUS_DIR / "gate_log.json"
GATE_LOG_KEEP = 50          # keep the last N decisions


def apply_interface_enable(router, interface):
    # The healer's fix verb: clear an admin shutdown ('no shutdown').
    # Defined here (not in proven rollback_deploy.py) to keep Phase 3 frozen.
    res = vtysh(router, "configure terminal", f"interface {interface}",
                "no shutdown", "end")
    if res.returncode != 0:
        raise RuntimeError(f"enable failed on {router}: {res.stderr.strip()}")


def default_commit(p):
    # Bridge one Proposal into the existing Phase 3 pipeline (verify+rollback).
    if p.action == "cost":
        desc = f"[{p.id}] set OSPF cost {p.value} on {p.router} {p.interface}"
        fn = lambda: apply_ospf_cost(p.router, p.interface, p.value)
    elif p.action == "enable":
        desc = f"[{p.id}] enable (no shutdown) {p.router} {p.interface}"
        fn = lambda: apply_interface_enable(p.router, p.interface)
    else:
        desc = f"[{p.id}] shutdown {p.router} {p.interface}"
        fn = lambda: apply_interface_shutdown(p.router, p.interface)
    return deploy(fn, desc, [p.router])              # Phase 3 does the rest


def log_gate_decision(entry):
    """Append one decision to status/gate_log.json (best-effort, never fatal)."""
    try:
        STATUS_DIR.mkdir(exist_ok=True)
        log = []
        if GATE_LOG.exists():
            log = json.loads(GATE_LOG.read_text())
        log.append(entry)
        GATE_LOG.write_text(json.dumps(log[-GATE_LOG_KEEP:], indent=2))
    except Exception as e:                            # logging must never block the gate
        print(f"  (gate log write failed: {e})")


class ConvergenceGate:
    def __init__(self, commit_fn=default_commit):
        self.queue = []                 # proposals waiting to be judged
        self.commit_fn = commit_fn      # injectable so tests can fake commits

    def submit(self, proposal):
        # The ONLY entry point for proposers (human or agent).
        self.queue.append(proposal)
        return f"queued {proposal.id} ({len(self.queue)} pending)"

    def evaluate_and_commit(self):
        """Judge the whole batch together; commit serially only if SAFE."""
        if not self.queue:
            return {"verdict": "EMPTY", "committed": []}

        proposals = list(self.queue)
        safe, report = joint_preflight(proposals)    # the joint judgment
        result = {"verdict": report["verdict"], "report": report,
                  "committed": [], "halted_after_rollback": None}

        if safe:
            for p in proposals:                      # serial commits, one at a time
                record = self.commit_fn(p)           # Phase 3 verifies + rolls back
                # If a commit failed health and rolled back, the network no
                # longer matches what the joint check assumed: stop the batch.
                if isinstance(record, dict) and record.get("decision") == "rolled_back":
                    result["halted_after_rollback"] = p.id
                    break
                result["committed"].append(p.id)

        self.queue.clear()                           # batch consumed either way
        log_gate_decision({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "proposals": [p.as_dict() for p in proposals],
            "verdict": result["verdict"],
            "reasons": report["reasons"],
            "links_removed": report["links_removed"],
            "committed": result["committed"],
            "halted_after_rollback": result["halted_after_rollback"],
        })
        return result
