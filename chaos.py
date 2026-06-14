#!/usr/bin/env python3
"""
SafeDeploy - Chaos: REAL fault injection.

Unlike inject.py (which feeds the gate a dangerous batch and proves it gets
BLOCKED), chaos.py actually breaks the network: it admin-downs one ring link,
ON PURPOSE, OUTSIDE the gate. Real failures (dead optics, fiber cuts) don't
ask permission - this simulates one. The watcher + healer agent then detect
and repair it through the gate.

Safety: chaos only fires faults that are survivable ALONE (single pre-flight
must say SAFE), so the demo degrades the network without partitioning it.

Usage (lab up):
  python3 chaos.py                      # break a random survivable ring link
  python3 chaos.py -r r1 -i eth1        # break a specific link
"""

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from preflight import preflight
from rollback_deploy import apply_interface_shutdown
from termstyle import banner, step, good, bad, c

STATUS_DIR = Path("status")
CHAOS_LOG = STATUS_DIR / "chaos.json"

# The four ring links, each as the (router, interface) end we shut.
RING_LINKS = [("r1", "eth1"), ("r2", "eth2"), ("r3", "eth2"), ("r4", "eth2")]


def main():
    p = argparse.ArgumentParser(description="SafeDeploy chaos: real fault injection")
    p.add_argument("-r", "--router")
    p.add_argument("-i", "--interface")
    args = p.parse_args()

    banner("SAFEDEPLOY · CHAOS", "a real fault, no permission asked")

    if args.router and args.interface:
        target = (args.router, args.interface)
    else:
        target = random.choice(RING_LINKS)
    router, interface = target

    # Refuse to create an unsurvivable fault: the demo is degradation, not outage.
    print()
    step("check", f"is killing {router} {interface} survivable alone?")
    safe, rep = preflight("shutdown", router, interface)
    if not safe:
        bad(f"REFUSING: shutting {router} {interface} would partition the "
            f"network ({rep['reasons'][0]}). Heal the previous fault first.")
        return 2
    good("survivable - the ring can reroute")

    print()
    step("chaos", c(f"admin-downing {router} {interface} ", "red", "bold")
         + c("(bypassing the gate, as a real failure would)", "grey"))
    apply_interface_shutdown(router, interface)

    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "router": router, "interface": interface, "action": "shutdown"}
    STATUS_DIR.mkdir(exist_ok=True)
    CHAOS_LOG.write_text(json.dumps(record, indent=2))
    bad(f"fault injected: {router} {interface} is down (recorded in {CHAOS_LOG})")
    print(c("\nnow watch: python3 watcher.py --once   (or leave watcher.py running)", "grey"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
