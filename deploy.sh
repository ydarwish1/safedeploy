#!/bin/bash
# Deploy the SafeDeploy lab and self-heal any node whose FRR/zebra
# loses the startup race (frrouting/frr:latest dev-image quirk).
set -e
sudo containerlab deploy -t topology.clab.yml --reconfigure
sleep 20
for r in r1 r2 r3 r4; do
  if ! sudo docker exec clab-safedeploy-$r vtysh -c "show interface brief" 2>/dev/null | grep -q "10.0"; then
    echo ">>> $r config not loaded, restarting FRR"
    sudo docker exec clab-safedeploy-$r /usr/lib/frr/frrinit.sh restart
  fi
done
sleep 40
echo "=== Adjacency check ==="
for r in r1 r2 r3 r4; do
  echo "--- $r ---"
  sudo docker exec clab-safedeploy-$r vtysh -c "show ip ospf neighbor" 2>/dev/null
done
