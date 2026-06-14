#!/usr/bin/env python3
"""
SafeDeploy - Fault injection demo (live).

Deliberately feeds the gate a dangerous COMBINATION: two shutdowns that are
each safe alone (the ring reroutes) but together strand r1. Shows:
  1. each proposal passes single pre-flight alone,
  2. the gate judges the batch jointly and BLOCKS it,
  3. nothing was applied - the live network is untouched.
Run on the lab host with all four nodes up: python3 inject.py
"""

import subprocess
import sys

from proposal import Proposal
from preflight import preflight
from gate import ConvergenceGate
from termstyle import banner, step, good, bad, verdict, c


def main():
    banner("SAFEDEPLOY · FAULT INJECTION",
           "safe alone, dangerous together - can the gate tell?")

    # The killer pair: r1's two ring links.
    p1 = Proposal(id="inj-001", action="shutdown", router="r1", interface="eth1",
                  rationale="fault injection: kill r1-r2 link")
    p2 = Proposal(id="inj-002", action="shutdown", router="r4", interface="eth2",
                  rationale="fault injection: kill r4-r1 link")

    # 1. Prove each is SAFE alone (old single-change check).
    print()
    for p in (p1, p2):
        safe, rep = preflight(*p.as_preflight_args())
        step("alone", f"{p.id}: {verdict(rep['verdict'])}  "
             + c(f"({rep['reasons'][0]})", "grey"))

    # 2. Fire BOTH at the gate as one batch.
    print()
    step("batch", "submitting both to the convergence gate...")
    g = ConvergenceGate()
    g.submit(p1)
    g.submit(p2)
    result = g.evaluate_and_commit()
    step("batch", f"verdict: {verdict(result['verdict'])}")
    for reason in result["report"]["reasons"]:
        print(c(f"        - {reason}", "grey"))
    step("batch", f"committed: {result['committed']}  "
         + c("(empty = nothing touched)", "grey"))

    # 3. Prove the live network is untouched: intent must still be satisfied.
    print()
    step("verify", "running intent verification against the live lab...")
    rc = subprocess.run([sys.executable, "verify_intent.py"]).returncode
    blocked = (result["verdict"] == "UNSAFE" and not result["committed"])
    print()
    if blocked and rc == 0:
        good("RESULT: GATE BLOCKED THE FAULT - NETWORK INTACT")
        return 0
    bad("RESULT: WARNING - unexpected outcome, investigate "
        f"(gate verdict={result['verdict']}, intent rc={rc})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
