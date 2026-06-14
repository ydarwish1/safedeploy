#!/usr/bin/env bash
# SafeDeploy - one-shot end-to-end verification run.
# Runs the whole pipeline against the live lab and prints every stage.
# Capture it with:  bash verify_all.sh 2>&1 | tee docs/verification-run.txt
# Stages 7 and 8 need ANTHROPIC_API_KEY set; everything else does not.

echo "SafeDeploy full verification - started $(date -u)"

echo; echo "===== [1/9] deploy lab (clean baseline) ====="
bash deploy.sh

echo; echo "===== [2/9] intent (baseline) ====="
python3 safedeploy.py intent

echo; echo "===== [3/9] offline test suites ====="
for t in test_proposal test_joint test_gate test_heal test_redteam test_blastradius; do
  echo "--- $t ---"; python3 $t.py
done

echo; echo "===== [4/9] inject (gate blocks the killer combo) ====="
python3 inject.py

echo; echo "===== [5/9] redteam (exhaustive gate audit) ====="
python3 safedeploy.py redteam

echo; echo "===== [6/9] blast radius forecast ====="
python3 safedeploy.py blast -r r1 -i eth1 -a shutdown

echo; echo "===== [7/9] chaos + self-heal ====="
python3 chaos.py
python3 watcher.py --once

echo; echo "===== [8/9] live agent (proposer -> critic -> gate) ====="
python3 agents.py "reduce traffic on the r1-r2 link"

echo; echo "===== reset lab after the agent's change ====="
bash deploy.sh

echo; echo "===== [9/9] final intent (clean) ====="
python3 safedeploy.py intent

echo; echo "SafeDeploy full verification - finished $(date -u)"
