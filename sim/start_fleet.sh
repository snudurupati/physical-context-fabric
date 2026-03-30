#!/bin/bash
# Physical Context Fabric — Fleet Start Script
# =============================================
# Starts the full stack in tmux sessions:
#
# jazzypi tmux (pcf):
#   window 0 - fleet    : 3x TurtleBot3 fake nodes
#   window 1 - drive    : behavior scripts for all 3 robots
#   window 2 - foxglove : Foxglove WebSocket bridge
#   window 3 - gateway  : edge gateway → Redis
#
# Mac tmux (pcf-mac):
#   window 0 - pathway  : Pathway sliding window + anomaly detection
#   window 1 - ingest   : Memgraph knowledge graph ingestion
#
# Usage:
#   bash sim/start_fleet.sh
#
# Attach to logs:
#   jazzypi : ssh ubuntu@192.168.1.119 then tmux attach -t pcf
#   Mac     : tmux attach -t pcf-mac  (Ctrl+B 0/1 to switch windows)
#
# Stop everything:
#   jazzypi : ssh ubuntu@192.168.1.119 then tmux kill-session -t pcf
#   Mac     : tmux kill-session -t pcf-mac

set -e

JAZZYPI="ubuntu@192.168.1.119"
PCF_DIR="$HOME/Projects/physical-context-fabric"
REDIS_HOST="192.168.1.94"

echo "=========================================="
echo " Physical Context Fabric — Fleet Startup"
echo "=========================================="

# -----------------------------------------------
# JAZZYPI SIDE — kill any existing session first
# -----------------------------------------------
echo "[1/6] Clearing any existing jazzypi tmux session..."
ssh $JAZZYPI "tmux kill-session -t pcf 2>/dev/null; sleep 1; echo done"

echo "[2/6] Starting fleet on jazzypi..."

# Window 0: fleet launch (3 robots)
ssh $JAZZYPI "tmux new-session -d -s pcf -n 'fleet' \
  'source /opt/ros/jazzy/setup.bash && \
   export TURTLEBOT3_MODEL=burger && \
   ros2 launch ~/physical-context-fabric/sim/fleet_launch.py; bash'"

sleep 4

# Window 1: drive all 3 robots
ssh $JAZZYPI "tmux new-window -t pcf -n 'drive' \
  'bash ~/physical-context-fabric/sim/drive_robot_001.sh & \
   bash ~/physical-context-fabric/sim/drive_robot_002.sh & \
   bash ~/physical-context-fabric/sim/drive_robot_003.sh & \
   wait'"

sleep 2

# Window 2: foxglove bridge
ssh $JAZZYPI "tmux new-window -t pcf -n 'foxglove' \
  'source /opt/ros/jazzy/setup.bash && \
   ros2 launch foxglove_bridge foxglove_bridge_launch.xml; bash'"

sleep 2

# Window 3: edge gateway
ssh $JAZZYPI "tmux new-window -t pcf -n 'gateway' \
  'source ~/pcf-venv/bin/activate && \
   source /opt/ros/jazzy/setup.bash && \
   REDIS_HOST=$REDIS_HOST python3 \
   ~/physical-context-fabric/ros2_bridge/odom_subscriber.py; bash'"

echo "      jazzypi stack started. Attach with:"
echo "      ssh ubuntu@192.168.1.119 then: tmux attach -t pcf"

# -----------------------------------------------
# MAC SIDE — Redis + Memgraph
# -----------------------------------------------
echo "[3/6] Starting Redis + Memgraph..."
docker compose -f $PCF_DIR/docker/docker-compose-mac.yml up -d 2>/dev/null || \
  echo "      (using existing containers)"

sleep 2

# -----------------------------------------------
# MAC SIDE — tmux for Pathway + Ingest
# -----------------------------------------------
echo "[4/6] Clearing any existing Mac tmux session..."
tmux kill-session -t pcf-mac 2>/dev/null || true
sleep 1

echo "[5/6] Starting Pathway consumer..."
tmux new-session -d -s pcf-mac -n 'pathway'
tmux send-keys -t pcf-mac:pathway \
  "cd $PCF_DIR && source .venv/bin/activate && python3 stream_pipeline/pathway_consumer.py" Enter

sleep 1

echo "[6/6] Starting Memgraph ingest..."
tmux new-window -t pcf-mac -n 'ingest'
tmux send-keys -t pcf-mac:ingest \
  "cd $PCF_DIR && source .venv/bin/activate && python3 context_graph/memgraph_ingest.py" Enter

# -----------------------------------------------
# DONE
# -----------------------------------------------
echo ""
echo "=========================================="
echo " Stack is running"
echo "=========================================="
echo ""
echo " jazzypi tmux  : ssh ubuntu@192.168.1.119"
echo "                 tmux attach -t pcf"
echo "   Ctrl+B 0    : fleet (3 robot nodes)"
echo "   Ctrl+B 1    : drive (behavior scripts)"
echo "   Ctrl+B 2    : foxglove bridge"
echo "   Ctrl+B 3    : edge gateway → Redis"
echo ""
echo " Mac tmux      : tmux attach -t pcf-mac"
echo "   Ctrl+B 0    : pathway consumer"
echo "   Ctrl+B 1    : memgraph ingest"
echo ""
echo " Foxglove      : ws://192.168.1.119:8765"
echo " Memgraph Lab  : http://localhost:3000"
echo ""
echo " Stop jazzypi  : ssh ubuntu@192.168.1.119"
echo "                 tmux kill-session -t pcf"
echo " Stop Mac      : tmux kill-session -t pcf-mac"
echo "=========================================="