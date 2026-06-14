#!/usr/bin/env python3
"""
SafeDeploy - unified CLI.

One entry point for the whole pipeline. Each subcommand routes to the existing
phase tool, so the proven files stay untouched and this is just the front door.

  safedeploy.py snapshot                                -> Phase 1 state snapshot
  safedeploy.py preflight -r r1 -i eth1 -a shutdown     -> Phase 4 single check
  safedeploy.py deploy    -r r1 -i eth1 -a cost -c 50   -> Phase 3 verify/rollback
  safedeploy.py path      --src r1 --dst r3             -> Phase 5 path verify
  safedeploy.py intent                                  -> Phase 6/7 intent verification
  safedeploy.py inject                                  -> convergence-gate fault demo
  safedeploy.py status                                  -> write a status snapshot to JSON
"""

import argparse
import subprocess
import sys


def run(script, *args):
    # Route to the existing tool; pass its exit code through unchanged.
    return subprocess.run([sys.executable, script, *args]).returncode


def main():
    p = argparse.ArgumentParser(description="SafeDeploy unified CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("snapshot", help="capture network state (Phase 1)")

    pf = sub.add_parser("preflight", help="single-change pre-flight (Phase 4)")
    pf.add_argument("-r", "--router", required=True)
    pf.add_argument("-i", "--interface", required=True)
    pf.add_argument("-a", "--action", required=True, choices=["cost", "shutdown"])

    dp = sub.add_parser("deploy", help="verify-then-commit deploy (Phase 3)")
    dp.add_argument("-r", "--router", required=True)
    dp.add_argument("-i", "--interface", required=True)
    dp.add_argument("-a", "--action", required=True, choices=["cost", "shutdown"])
    dp.add_argument("-c", "--cost", type=int, default=50)

    pa = sub.add_parser("path", help="data-plane path verification (Phase 5)")
    pa.add_argument("--src", required=True)
    pa.add_argument("--dst", required=True)
    pa.add_argument("--expect", default=None)

    sub.add_parser("intent", help="verify declared intent (Phase 6/7)")
    sub.add_parser("inject", help="fault-injection demo: gate blocks bad combo")
    sub.add_parser("redteam", help="exhaustive adversarial audit of the gate")

    bl = sub.add_parser("blast", help="quantified impact forecast for a change")
    bl.add_argument("-r", "--router", required=True)
    bl.add_argument("-i", "--interface", required=True)
    bl.add_argument("-a", "--action", required=True,
                    choices=["shutdown", "enable", "cost"])
    sub.add_parser("status", help="write a status snapshot to status/status.json")

    a = p.parse_args()

    if a.cmd == "snapshot":
        return run("snapshot.py")
    if a.cmd == "preflight":
        return run("preflight.py", "--router", a.router,
                   "--interface", a.interface, "--action", a.action)
    if a.cmd == "deploy":
        return run("rollback_deploy.py", "--router", a.router,
                   "--interface", a.interface, "--action", a.action,
                   "--cost", str(a.cost))
    if a.cmd == "path":
        args = ["--src", a.src, "--dst", a.dst]
        if a.expect:
            args += ["--expect", a.expect]
        return run("verify_path.py", *args)
    if a.cmd == "intent":
        return run("verify_intent.py")
    if a.cmd == "inject":
        return run("inject.py")
    if a.cmd == "redteam":
        return run("redteam.py")
    if a.cmd == "blast":
        return run("blastradius.py", "--router", a.router,
                   "--interface", a.interface, "--action", a.action)
    if a.cmd == "status":
        return run("collect_status.py")


if __name__ == "__main__":
    sys.exit(main())
