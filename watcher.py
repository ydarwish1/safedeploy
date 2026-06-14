#!/usr/bin/env python3
"""
SafeDeploy - Watcher: the self-healing loop.

Continuously checks the network against declared intent. When intent is
violated (e.g. chaos.py killed a link), it collects evidence, asks the AI
healer for a repair Proposal, gets the critic's advisory review, and submits
the fix to the convergence gate - the only path to a device. Then re-verifies.

  fault happens -> watcher detects -> healer proposes -> critic advises
       -> GATE judges & commits (verify-then-rollback) -> intent green again

Usage (lab up, ANTHROPIC_API_KEY set, pip install anthropic):
  python3 watcher.py --once             # one check/heal cycle
  python3 watcher.py                    # run forever (every 15s)
  python3 watcher.py --interval 30
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from gate import ConvergenceGate
from termstyle import banner, step, good, bad, verdict, c

STATUS_DIR = Path("status")
HEAL_LOG = STATUS_DIR / "heal_log.json"
MAX_HEAL_ATTEMPTS = 3      # per violation: never loop a broken fix forever


def check_intent():
    """Run verify_intent.py; return (satisfied: bool, output: str)."""
    res = subprocess.run([sys.executable, "verify_intent.py"],
                         capture_output=True, text=True)
    return (res.returncode == 0, res.stdout)


def admin_down_interfaces():
    """Diagnosis evidence: every interface with 'shutdown' in running config."""
    from preflight import get_config, ROUTERS
    down = []
    for r in ROUTERS:
        cfg = get_config(r)
        current = None
        for line in cfg.splitlines():
            m = re.match(r"interface (\S+)", line.strip())
            if m:
                current = m.group(1)
            elif line.strip() == "shutdown" and current:
                down.append(f"{r} {current}")
    return down


def log_heal(entry):
    try:
        STATUS_DIR.mkdir(exist_ok=True)
        log = json.loads(HEAL_LOG.read_text()) if HEAL_LOG.exists() else []
        log.append(entry)
        HEAL_LOG.write_text(json.dumps(log[-50:], indent=2))
    except Exception as e:
        print(f"  (heal log write failed: {e})")


def heal_cycle(gate):
    """One detect->diagnose->propose->gate->verify pass. True if healthy after."""
    ok, output = check_intent()
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    if ok:
        print(c(f"[{now}]", "grey") + " intent " + c("SATISFIED", "green", "bold")
              + c(" - all assertions hold", "grey"))
        return True

    print()
    bad(f"[{now}] INTENT VIOLATED - engaging healer agent")
    from agents import healer, critic            # imported here: needs API key

    for attempt in range(1, MAX_HEAL_ATTEMPTS + 1):
        down = admin_down_interfaces()
        evidence = (f"Intent verification output:\n{output}\n"
                    f"Admin-down interfaces: {down or 'none found'}")
        p = healer(evidence, proposal_id=f"heal-{attempt:03d}")
        step("healer", f"attempt {attempt}: " + c(f"{p.action} {p.router} "
             f"{p.interface}", "bold") + c(f" - {p.rationale}", "grey"))

        review = critic(p)
        rec = review["recommendation"]
        step("critic", (c(rec, "green", "bold") if rec == "APPROVE"
             else c(rec, "red", "bold"))
             + c(f" (advisory): {review.get('concerns', [])}", "grey"))

        print(c("         " + gate.submit(p), "grey"))
        result = gate.evaluate_and_commit()       # joint check + Phase 3 commit
        step("gate", f"verdict: {verdict(result['verdict'])}, "
             f"committed: {result['committed']}")

        ok, output = check_intent()
        log_heal({"timestamp": datetime.now(timezone.utc).isoformat(),
                  "attempt": attempt, "proposal": p.as_dict(),
                  "critic": review, "gate_verdict": result["verdict"],
                  "committed": result["committed"], "healed": ok})
        if ok:
            print()
            good("HEALED - intent satisfied again\n")
            return True
        print(c("still violated, retrying...", "yellow"))

    print()
    bad("GAVE UP after max attempts - human needed\n")
    return False


def main():
    ap = argparse.ArgumentParser(description="SafeDeploy self-healing watcher")
    ap.add_argument("--once", action="store_true", help="one cycle, then exit")
    ap.add_argument("--interval", type=int, default=15, help="seconds between checks")
    args = ap.parse_args()

    banner("SAFEDEPLOY · WATCHER", "detect -> diagnose -> heal, through the gate")
    print()

    gate = ConvergenceGate()
    if args.once:
        return 0 if heal_cycle(gate) else 1
    print(c(f"watching every {args.interval}s (Ctrl+C to stop)...\n", "grey"))
    while True:
        heal_cycle(gate)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
