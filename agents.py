#!/usr/bin/env python3
"""
SafeDeploy - Agentic layer: proposer + critic + healer.

Three LLM roles, all OUTSIDE the write path by construction:
  - proposer(goal)     : natural-language goal -> a structured Proposal
  - critic(proposal)   : a Proposal -> an ADVISORY verdict (cannot block or apply)
  - healer(evidence)   : failure evidence -> a repair Proposal

Each role gets its output via Claude function calling (tool use): the model is
forced to answer by calling a tool whose schema we define, so the reply is
schema-checked structured data instead of free text we have to parse.

The only way any agent output reaches the network is gate.submit(); the gate's
joint pre-flight and the Phase 3 verify-then-rollback pipeline remain the sole
authority. An agent literally has no function it can call that writes to a
device - that is the NetPilot principle extended to changes.

Requires: pip install anthropic, and ANTHROPIC_API_KEY in the environment.
Demo (lab up): python3 agents.py "reduce traffic on the r1-r2 link"
"""

import json
import logging
import os
import sys

from proposal import Proposal

log = logging.getLogger("safedeploy.agents")

MODEL = "claude-sonnet-4-5"   # change to taste
ROUTERS = ["r1", "r2", "r3", "r4"]

TOPOLOGY_BRIEF = """The lab is a 4-router FRR ring running OSPF (iBGP overlay):
r1 eth1 <-> r2 eth1   (10.0.12.0/30)
r2 eth2 <-> r3 eth1   (10.0.23.0/30)
r3 eth2 <-> r4 eth1   (10.0.34.0/30)
r4 eth2 <-> r1 eth2   (10.0.41.0/30)
Allowed actions: "shutdown" (admin-down an interface),
"cost" (set OSPF cost on an interface, value 1-65535), or
"enable" (clear an admin shutdown with 'no shutdown')."""

PROPOSER_SYSTEM = f"""You are a network change proposer. {TOPOLOGY_BRIEF}
Given a goal, call the submit_change tool with exactly one change that advances
the goal. Use 'value' only for a 'cost' action."""

CRITIC_SYSTEM = f"""You are a network change reviewer. {TOPOLOGY_BRIEF}
Given a proposed change, call the submit_review tool with your verdict and any
concerns. Your verdict is advisory; a deterministic safety gate makes the final
call."""

HEALER_SYSTEM = f"""You are a network repair agent. {TOPOLOGY_BRIEF}
You are given evidence of a failure: the intent-verification output and a list
of admin-down interfaces. Call the submit_change tool with ONE change that
repairs the network. Use 'value' only for a 'cost' action."""

# Tool schemas: the model answers by *calling* one of these (forced via
# tool_choice), so its reply is schema-checked structured data rather than free
# text we have to regex. This is the function-calling pattern production agents
# are built on; the Proposal validation downstream is the second safety net.
CHANGE_TOOL = {
    "name": "submit_change",
    "description": "Submit exactly one network change for the gate to evaluate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["shutdown", "cost", "enable"]},
            "router": {"type": "string", "enum": ROUTERS},
            "interface": {"type": "string", "enum": ["eth1", "eth2"]},
            "value": {"type": "integer",
                      "description": "OSPF cost 1-65535; include only for action 'cost'"},
            "rationale": {"type": "string", "description": "one-sentence reason"},
        },
        "required": ["action", "router", "interface", "rationale"],
    },
}

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Return an advisory review of the proposed change.",
    "input_schema": {
        "type": "object",
        "properties": {
            "recommendation": {"type": "string", "enum": ["APPROVE", "REJECT"]},
            "concerns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["recommendation", "concerns"],
    },
}


def _ask(system, user_msg):
    """One Claude call via function calling; returns the structured tool input.

    The model is forced (tool_choice) to answer by calling a tool whose schema
    we define, so the reply is schema-checked data - not free text we parse. The
    SDK retries transient API errors; every call is logged for observability.
    """
    import anthropic                                  # imported here so the
    client = anthropic.Anthropic(max_retries=3)       # rest works without it
    tool = REVIEW_TOOL if "reviewer" in system else CHANGE_TOOL
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=400, system=system, tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user_msg}])
    except anthropic.APIError as e:                   # typed SDK exception
        raise RuntimeError(f"Claude API call failed: {e}") from e
    log.info("claude model=%s req=%s in_tok=%s out_tok=%s tool=%s",
             resp.model, getattr(resp, "_request_id", None),
             resp.usage.input_tokens, resp.usage.output_tokens, tool["name"])
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return block.input
    raise ValueError(
        f"model did not call {tool['name']} (stop={resp.stop_reason})")


def proposer(goal, proposal_id="agent-001"):
    """Natural-language goal -> validated Proposal (raises if malformed)."""
    data = _ask(PROPOSER_SYSTEM, f"Goal: {goal}")
    if data.get("router") not in ROUTERS:
        raise ValueError(f"proposer named unknown router: {data.get('router')}")
    return Proposal(id=proposal_id, action=data["action"], router=data["router"],
                    interface=data["interface"], value=data.get("value"),
                    rationale=data.get("rationale", ""))


def critic(proposal):
    """Proposal -> advisory dict {'recommendation', 'concerns'}. Cannot act."""
    return _ask(CRITIC_SYSTEM,
                f"Proposed change: {json.dumps(proposal.as_dict())}")


def healer(evidence, proposal_id="heal-001"):
    """Failure evidence -> validated repair Proposal (raises if malformed)."""
    data = _ask(HEALER_SYSTEM, evidence)
    if data.get("router") not in ROUTERS:
        raise ValueError(f"healer named unknown router: {data.get('router')}")
    return Proposal(id=proposal_id, action=data["action"], router=data["router"],
                    interface=data["interface"], value=data.get("value"),
                    rationale=data.get("rationale", ""))


def main():
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("Set ANTHROPIC_API_KEY first (and: pip install anthropic).")
        return 2
    goal = " ".join(sys.argv[1:]) or "reduce traffic on the r1-r2 link"

    print(f"goal: {goal}")
    p = proposer(goal)
    print(f"proposer -> {p}")

    review = critic(p)
    print(f"critic   -> {review['recommendation']}: {review.get('concerns', [])}")

    # The ONLY exit to the network: the gate. Even an APPROVEd proposal still
    # faces the joint pre-flight and the verify-then-rollback pipeline.
    from gate import ConvergenceGate
    g = ConvergenceGate()
    print(g.submit(p))
    result = g.evaluate_and_commit()
    print(f"gate verdict: {result['verdict']}, committed: {result['committed']}")
    return 0 if result["verdict"] == "SAFE" else 1


if __name__ == "__main__":
    sys.exit(main())
