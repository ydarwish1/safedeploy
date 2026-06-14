# Live Verification Runbook

The closing procedure for the convergence-gate milestone. Run top to bottom on
the lab host. Stop at the first step whose output does not match; do not push
past a red step. When every step is green, the project's status flips from
offline-verified to live-verified.

## A. Sync

1. On the workstation: stage and commit the new files, then push. The duplicate
   root-level `PHASE*-LOG.md` and `daemons` are gitignored, so they are not
   committed (the canonical copies live in `docs/` and `configs/`).
2. On the lab host: `cd ~/safedeploy && git pull`.

## B. Offline suites (lab may be down)

| Command | Pass looks like |
|---|---|
| `python3 test_proposal.py` | ALL PASS, exit 0 |
| `python3 test_joint.py` | True, True, False, ALL PASS |
| `python3 test_gate.py` | SAFE / UNSAFE / halt, ALL PASS |
| `python3 test_heal.py` | HEALED, ALL PASS |
| `python3 test_redteam.py` | AUDIT CLEAN 6/6 blocked, 4/4 allowed, ALL PASS |
| `python3 test_blastradius.py` | margins / SPOFs / grades, ALL PASS |

After running: `printf '[]\n' > status/gate_log.json && printf '[]\n' > status/heal_log.json`
(the suites write real ledger entries; start the live demos clean).

## C. Live pipeline (lab up: `./deploy.sh` if needed)

| Command | Pass looks like |
|---|---|
| `python3 safedeploy.py intent` | 12/12, INTENT SATISFIED, `echo $?` is 0 |
| `python3 safedeploy.py preflight -r r1 -i eth1 -a shutdown` | SAFE, matches direct preflight.py call |
| `python3 inject.py` | SAFE alone x2, batch UNSAFE, committed [], GATE BLOCKED THE FAULT - NETWORK INTACT |
| `python3 safedeploy.py redteam` | AUDIT CLEAN: 6/6 dangerous blocked, 4/4 safe allowed, 0 false verdicts |
| `python3 safedeploy.py blast -r r1 -i eth1 -a shutdown` | margin 2 -> 1, 3 new SPOFs, GRADE: ELEVATED, requires human ack |

## D. Agents and self-healing

1. `pip3 install -r requirements.txt` and `export ANTHROPIC_API_KEY=...`
   (environment only; never in a file in this repo).
2. `python3 agents.py "reduce traffic on the r1-r2 link"` - proposer, critic,
   and gate verdict print; if the API rejects the model name, update `MODEL`
   in agents.py to a current one.
3. `python3 chaos.py` then `python3 watcher.py --once`.
   Expect: INTENT VIOLATED -> healer proposes enable -> critic APPROVE ->
   gate SAFE, committed -> HEALED on the first attempt.

## E. One-shot full run

`bash verify_all.sh 2>&1 | tee docs/verification-run.txt` runs the whole
pipeline (deploy, intent, six suites, inject, redteam, blast, chaos + heal,
the live agent, reset, final intent) and captures it to one log.

## F. Close

1. `git add -A && git commit -m "Live verified: gate, fault injection, self-healing" && git push`.
2. Flip the README status line to live-verified and add the closing log entries.
3. Later, as separate verified steps: package-layout migration, BGP JSON-output
   fix in verify_intent.py, and the operations dashboard.
