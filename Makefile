# SafeDeploy - one verb per workflow. Run from the repo root.
.PHONY: test compile lab verify block chaos heal redteam clean help

help:           ## list available targets
	@grep -E '^[a-z-]+:.*##' Makefile | awk -F':.*## ' '{printf "  make %-12s %s\n", $$1, $$2}'

test:           ## run the six offline suites (no lab, no API key)
	python3 test_proposal.py && python3 test_joint.py && python3 test_gate.py && python3 test_heal.py && python3 test_redteam.py && python3 test_blastradius.py
	@printf '[]\n' > status/gate_log.json; printf '[]\n' > status/heal_log.json
	@echo "all suites green, ledgers reset"

compile:        ## syntax-check every module
	python3 -m py_compile *.py && echo "all modules compile"

lab:            ## deploy / redeploy the 4-node lab (lab host only)
	./deploy.sh

verify:         ## prove live network matches declared intent
	python3 safedeploy.py intent

block:          ## demo: gate refuses the safe-alone/dangerous-together batch
	python3 inject.py

chaos:          ## demo: actually break a survivable ring link (outside the gate)
	python3 chaos.py

heal:           ## demo: one watcher cycle - detect, AI-diagnose, gate-commit fix
	python3 watcher.py --once

redteam:        ## exhaustive audit: every failure combo vs the gate
	python3 redteam.py

clean:          ## reset runtime ledgers to empty
	printf '[]\n' > status/gate_log.json; printf '[]\n' > status/heal_log.json
	@echo "ledgers reset"
