#!/usr/bin/env python3
"""
SafeDeploy - Proposal schema.

A Proposal is a proposed network change as structured data. It is the shared
format the convergence gate (and later, agent proposers) pass changes around in.
Field names mirror preflight.preflight(action, router, interface) exactly.
Nothing here touches a device.
"""

from dataclasses import dataclass
from typing import Optional

# shutdown/cost match preflight; "enable" (no shutdown) is the healer's fix
# verb - it can only ADD capacity, so it is topologically safe by construction.
VALID_ACTIONS = {"shutdown", "cost", "enable"}


@dataclass
class Proposal:
    id: str                      # unique label for tracking through logs
    action: str                  # "shutdown", "cost", or "enable"
    router: str                  # e.g. "r1"
    interface: str               # e.g. "eth1"
    value: Optional[int] = None  # OSPF cost number; only used when action=="cost"
    rationale: str = ""          # why this change was proposed (logs/agents later)

    def __post_init__(self):
        # Runs automatically on creation: reject malformed proposals at the door.
        if self.action not in VALID_ACTIONS:
            raise ValueError(
                f"action must be one of {sorted(VALID_ACTIONS)}, got '{self.action}'")
        if self.action == "cost":
            if self.value is None:
                raise ValueError("a 'cost' proposal must include a 'value'")
            if not isinstance(self.value, int) or self.value < 1 or self.value > 65535:
                raise ValueError("cost 'value' must be an integer 1-65535")
        if self.action in ("shutdown", "enable") and self.value is not None:
            raise ValueError(f"a '{self.action}' proposal should not have a 'value'")
        if not self.router or not self.interface:
            raise ValueError("router and interface are required")

    def as_preflight_args(self):
        # Bridge to existing code: returns exactly what preflight() takes.
        return (self.action, self.router, self.interface)

    def as_dict(self):
        # For JSON status logs.
        return {"id": self.id, "action": self.action, "router": self.router,
                "interface": self.interface, "value": self.value,
                "rationale": self.rationale}
