#!/usr/bin/env python3
"""
SafeDeploy - status snapshot collector.

Reads the live lab and writes status/status.json, a machine-readable snapshot of
the current network state:
  - topology: the modeled adjacency graph (from preflight's builder)
  - intent:   verify_intent.py result (pass/fail + full output)

Run on the lab host: python3 collect_status.py   (or: safedeploy.py status)
A web console to render this snapshot is a future goal.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from preflight import build_topology

STATUS_DIR = Path("status")


def main():
    print("Collecting live status...")
    topo = build_topology()                          # live read, no writes

    res = subprocess.run([sys.executable, "verify_intent.py"],
                         capture_output=True, text=True)
    passed = res.returncode == 0

    status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topology": {r: sorted(nbrs) for r, nbrs in topo.items()},
        "intent": {
            "satisfied": passed,
            "exit_code": res.returncode,
            "output": res.stdout,
        },
    }
    STATUS_DIR.mkdir(exist_ok=True)
    out = STATUS_DIR / "status.json"
    out.write_text(json.dumps(status, indent=2))
    print(f"Wrote {out} (intent {'SATISFIED' if passed else 'VIOLATED'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
