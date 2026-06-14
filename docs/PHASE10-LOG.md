# Phase 10 - Adversarial audit and blast-radius forecasting

Goal of Phase 10: stop trusting the gate and start proving it, and turn the
question "will this change break the network?" into "what does this change do to
the network's ability to survive the next failure?" Two tools that interrogate
the safety system and quantify risk, both before anything is committed.

Outcome: achieved. The gate is held to zero false verdicts across every failure
combination on the topology, and every change gets a graded impact forecast.

## What was built

- redteam.py - an exhaustive adversarial audit. Enumerate every combination of
  link failures up to a chosen depth, find every combination that partitions the
  model, then replay each one through the gate's own joint pre-flight and check
  the verdict both ways: a dangerous combination must be refused, a safe change
  must be allowed. The exit code is nonzero on any false verdict, so the audit
  fails loudly. On the ring it independently rediscovers a graph-theory fact: a
  cycle survives any single edge loss and is disconnected by any two. It finds 4
  safe singles and 6 minimal deadly pairs, and verifies the gate blocks 6 of 6
  with 0 false verdicts.
- blastradius.py - a quantified impact forecast per change, computed before
  commit: the survivability margin (edge connectivity, the minimum number of
  simultaneous link failures that can partition the network), every link that
  becomes a single point of failure after the change, and every router pair whose
  shortest forwarding path shifts. Changes are graded LOW (auto-commit), ELEVATED
  (survivable but fragile, human ack), or UNSAFE (refuse), with the policy hint
  attached.

## Issue found and fixed - nondeterministic component ordering

Running the red-team test repeatedly to check its stability caught it producing a
different (but still correct) ordering of the stranded components between runs.
The cause was a set iteration whose order depends on Python's per-run hash
randomization. The fix was to sort components by (size, name), which is stable,
and it was confirmed by ten consecutive identical runs. A real bug surfaced by
paranoia and fixed at the source rather than by loosening the test.

## Design

Both tools are pure standard-library graph math: no lab, no network, no API.
Every number is verified offline against hand-computed graph facts - the ring
margin drops from 2 to 1 after one shutdown, three links become single points of
failure, the r1<->r2 flow stretches from 1 hop to 3, and the enable action
restores the margin to 2.

## Verification (Phase 10 gate)

- Offline: test_redteam (4/4 safe allowed, 6/6 deadly blocked, 0 false verdicts)
  and test_blastradius (margins, single points of failure, and grades checked
  against hand-computed values).
- Live: both run through the CLI against the live topology (safedeploy.py
  redteam, safedeploy.py blast).

## Notes carried forward

- The value of both tools scales with topology size. On four nodes the results
  are nearly hand-computable; on a larger mesh nobody can eyeball the
  combinations, which is the point of automating the audit.
- redteam depth is a parameter. --depth 3 hunts triples, which becomes
  meaningful once the network is large enough to have three-link kill sets.
