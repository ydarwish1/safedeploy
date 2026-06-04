#!/usr/bin/env python3
"""
SafeDeploy Phase 2 - Apply a config change and verify it landed.

This is the "write" half of the tool. Phase 1 could only read; this can
change a router and confirm the change took effect. There is deliberately
NO rollback here yet - that is Phase 3. Phase 2's only job is: apply one
change, read it back, confirm it is present.

Change model (Phase 2): set the OSPF cost on one interface of one router.
OSPF cost is a good first change because it is real (it influences path
selection), easily verified (it appears in the running config and in
'show ip ospf interface'), and reversible later.
"""

import argparse
import subprocess
import sys

CONTAINER_PREFIX = "clab-safedeploy-"

# Commands that change state are config commands, not 'show'. Phase 1 forbade
# these; Phase 2 is the one place they are allowed, and only through this file.
READ_ONLY_PREFIXES = ("show ",)


def run_show(router: str, command: str) -> str:
    """Run a read-only command and return its output (used for verification)."""
    if not command.startswith(READ_ONLY_PREFIXES):
        raise ValueError(f"run_show only accepts show commands: {command!r}")
    container = f"{CONTAINER_PREFIX}{router}"
    result = subprocess.run(
        ["sudo", "docker", "exec", container, "vtysh", "-c", command],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{container} `{command}` failed: {result.stderr.strip()}")
    return result.stdout.strip()


def apply_ospf_cost(router: str, interface: str, cost: int) -> None:
    """Push an OSPF cost change to one interface via vtysh config mode.

    This is the only state-changing function in Phase 2. It enters config
    mode, sets the cost on the interface, and writes nothing else.
    """
    container = f"{CONTAINER_PREFIX}{router}"
    cmds = [
        "configure terminal",
        f"interface {interface}",
        f"ip ospf cost {cost}",
        "end",
    ]
    # vtysh takes repeated -c flags, one per config line.
    args = ["sudo", "docker", "exec", container, "vtysh"]
    for c in cmds:
        args += ["-c", c]
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"{container} config change failed: {result.stderr.strip()}")


def verify_ospf_cost(router: str, interface: str, expected_cost: int) -> bool:
    """Read the running config back and confirm the cost is present.

    Returns True only if the exact 'ip ospf cost <expected>' line appears
    under the target interface. This is the Phase 2 success test.
    """
    config = run_show(router, "show running-config")
    # Find the interface block and check the cost line is inside it.
    lines = config.splitlines()
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == f"interface {interface}":
            in_block = True
            continue
        if in_block:
            # A new top-level 'interface' or end of block stops the search.
            if stripped.startswith("interface ") or stripped == "!":
                in_block = False
                continue
            if stripped == f"ip ospf cost {expected_cost}":
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply and verify an OSPF cost change (Phase 2, no rollback)."
    )
    parser.add_argument("--router", required=True, help="e.g. r1")
    parser.add_argument("--interface", required=True, help="e.g. eth1")
    parser.add_argument("--cost", type=int, required=True, help="OSPF cost, e.g. 50")
    args = parser.parse_args()

    print(f"SafeDeploy Phase 2 - setting OSPF cost {args.cost} on "
          f"{args.router} {args.interface}")

    # Show the before state for this interface.
    before = run_show(args.router, f"show ip ospf interface {args.interface}")
    print("\n--- before ---")
    print(before)

    # Apply the change.
    apply_ospf_cost(args.router, args.interface, args.cost)
    print("\nChange applied. Verifying...")

    # Verify it landed in the running config.
    ok = verify_ospf_cost(args.router, args.interface, args.cost)

    # Show the after state.
    after = run_show(args.router, f"show ip ospf interface {args.interface}")
    print("\n--- after ---")
    print(after)

    if ok:
        print(f"\nVERIFIED: ip ospf cost {args.cost} is present on "
              f"{args.router} {args.interface}")
        return 0
    else:
        print(f"\nFAILED: cost {args.cost} not found in running config on "
              f"{args.router} {args.interface}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
