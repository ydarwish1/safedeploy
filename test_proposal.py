#!/usr/bin/env python3
"""Test the Proposal schema and its alignment with preflight()."""

from proposal import Proposal

failures = 0

# 1. Valid proposals build cleanly
p1 = Proposal(id="prop-001", action="shutdown", router="r1", interface="eth1",
              rationale="test link-down")
p2 = Proposal(id="prop-002", action="cost", router="r2", interface="eth2",
              value=50, rationale="shift path preference")
p3 = Proposal(id="prop-003", action="enable", router="r1", interface="eth1",
              rationale="healer fix verb")
print("created:", p1)
print("created:", p2)
print("created:", p3)

# 2. Bad proposals get rejected by validation
for label, bad in [
    ("bad action", lambda: Proposal(id="b1", action="reboot", router="r1", interface="eth1")),
    ("cost w/o value", lambda: Proposal(id="b2", action="cost", router="r1", interface="eth1")),
    ("shutdown w/ value", lambda: Proposal(id="b3", action="shutdown", router="r1", interface="eth1", value=10)),
    ("cost out of range", lambda: Proposal(id="b4", action="cost", router="r1", interface="eth1", value=0)),
    ("missing router", lambda: Proposal(id="b5", action="shutdown", router="", interface="eth1")),
    ("enable w/ value", lambda: Proposal(id="b6", action="enable", router="r1", interface="eth1", value=10)),
]:
    try:
        bad()
        print(f"ERROR: {label} was NOT rejected")
        failures += 1
    except ValueError as e:
        print(f"rejected ok ({label}): {e}")

# 3. Alignment: maps onto preflight(action, router, interface)
args = p1.as_preflight_args()
print("preflight args:", args)
assert args == ("shutdown", "r1", "eth1"), "preflight args misaligned"

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURES")
raise SystemExit(failures)

# 4. LIVE test (only on AWS with lab up) - uncomment to run end-to-end:
# from preflight import preflight
# safe, report = preflight(*p1.as_preflight_args())
# print("live preflight verdict:", report["verdict"])
