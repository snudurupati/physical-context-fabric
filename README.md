# Physical Context Fabric

A streaming pipeline + operational knowledge graph for ROS2 robots.

Physical AI generates petabytes of sensor telemetry. Tools like Foxglove
let you replay it. Physical Context Fabric answers what replay can't:
why did the robot fail, what was the full operational context, and does
this pattern recur?

**Stack:** ROS2 Jazzy → Edge Gateway → Redis Streams → Pathway → Memgraph

---

## Architecture

```
jazzypi (Pi 5)                    Mac
──────────────────────            ──────────────────────
ROS2 Jazzy (native)               Foxglove Studio
TurtleBot3 fake node    ───────►  ws://jazzypi:8765
odom_subscriber.py      ───────►  Redis Streams
                                  Pathway (stream processing)
                                  Memgraph (knowledge graph)
```

The Pi 5 runs the robot compute layer. The Mac runs the data
infrastructure layer. This mirrors real fleet deployments.

---

## Knowledge Graph Schema

```
Robot → Task → Event → Anomaly → Environment_State
```

Core relationships:
- `(Robot)-[:EXECUTING]->(Task)`
- `(Task)-[:GENERATED]->(Event)`
- `(Event)-[:PRECEDED]->(Anomaly)`
- `(Anomaly)-[:OCCURRED_IN]->(Environment_State)`

The graph answers: *"What was the full context 30 seconds before this failure?"*

---

## Edge Gateway: Delta + Keyframe + Heartbeat

Raw ROS2 telemetry at 10Hz produces 3.6M events/hour per robot. Writing
all of it downstream defeats the purpose of a context layer, you just
recreate the replay problem. The edge gateway on jazzypi filters at the
source:

| Frame type | When written | Purpose |
|---|---|---|
| `keyframe` | Every 30 seconds | Full state snapshot — ground truth anchor |
| `delta` | Position >5cm, velocity >0.05 m/s, state change | Meaningful change only |
| `anomaly` | Immediately, never suppressed | unexpected_stop, velocity_drop |
| `heartbeat` | Every 60 seconds when quiet | Alive ping, no data loss |

**Result: 96% bandwidth reduction. Only contextually significant events
reach the knowledge graph.**

---

## Hardware

| Device | Role | OS |
|---|---|---|
| Raspberry Pi 5 16GB + NVMe SSD | ROS2 edge gateway | Ubuntu 24.04.3 LTS |
| MacBook Air M4 | Data infrastructure, Foxglove, development | macOS |

---

## Repo Structure

```
physical-context-fabric/
├── ros2_bridge/              # Edge gateway (runs on Pi 5)
│   └── odom_subscriber.py   # Delta+keyframe+heartbeat gateway
├── stream_pipeline/          # Pathway anomaly detection (runs on Mac)
│   └── pathway_consumer.py
├── context_graph/            # Memgraph schema + ingestion (runs on Mac)
│   └── memgraph_ingest.py
├── queries/                  # Cypher query library
│   ├── operational_queries.cypher
│   └── README.md
├── docker/                   # Docker setup for Mac development
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker-compose-mac.yml
├── sim/                      # Gazebo launch files
└── docs/
```

---

## Quick Start

### jazzypi setup (Pi 5)

```bash
# Ubuntu 24.04.3 LTS — install ROS2 Jazzy
sudo apt install -y software-properties-common curl
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=arm64 signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
  http://packages.ros.org/ros2/ubuntu noble main" | \
  sudo tee /etc/apt/sources.list.d/ros2.list
sudo apt update
sudo apt install -y ros-jazzy-ros-base \
  ros-jazzy-turtlebot3 \
  ros-jazzy-turtlebot3-simulations \
  ros-jazzy-foxglove-bridge
echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc

# Python environment
python3 -m venv ~/pcf-venv
source ~/pcf-venv/bin/activate
pip install redis numpy pyyaml
```

### Run the robot

```bash
# Terminal 1 — start fake node
source /opt/ros/jazzy/setup.bash
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_fake_node turtlebot3_fake_node.launch.py
```

```bash
# Terminal 2 — drive the robot in a circle
source /opt/ros/jazzy/setup.bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.2}, angular: {z: 0.5}}" --rate 10
```

```bash
# Terminal 3 — verify raw odometry (optional inspection)
source /opt/ros/jazzy/setup.bash
ros2 topic echo /odom
```

```bash
# Terminal 4 — start Foxglove bridge
source /opt/ros/jazzy/setup.bash
ros2 launch foxglove_bridge foxglove_bridge_launch.xml
```

```bash
# Terminal 5 — edge gateway (streams filtered events to Redis on Mac)
source ~/pcf-venv/bin/activate
source /opt/ros/jazzy/setup.bash
REDIS_HOST=<mac-ip> python3 ros2_bridge/odom_subscriber.py
```

Expected gateway output:
```
[INFO] Connected to Redis at 192.168.1.94:6379
[INFO] Edge gateway started | keyframe=30.0s | heartbeat=60.0s | pos_threshold=0.05m
[INFO] Compression — received=1400 written=56 ratio=4.0% frame=delta
```

Stop Terminal 2 with Ctrl+C to trigger an `unexpected_stop` anomaly.

### Mac infrastructure

```bash
# Start Redis + Memgraph
docker compose -f docker/docker-compose-mac.yml up -d

# Python environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install pathway redis gqlalchemy

# Terminal 1 — Pathway anomaly detection
python3 stream_pipeline/pathway_consumer.py

# Terminal 2 — Memgraph ingestion
python3 context_graph/memgraph_ingest.py
```

### Connect Foxglove Studio (Mac)

Open Foxglove Studio → Open connection → Foxglove WebSocket →
`ws://jazzypi.local:8765`

---

## What the event stream looks like

```json
{
  "timestamp": "1774705546.681",
  "robot_id": "jazzypi",
  "position_x": "0.3129",
  "position_y": "0.6493",
  "linear_vel": "0.0",
  "angular_vel": "0.0",
  "commanded_linear": "0.2",
  "commanded_angular": "0.5",
  "event_type": "stopped",
  "frame_type": "anomaly",
  "anomaly_type": "unexpected_stop"
}
```

`commanded_linear: 0.2` with `linear_vel: 0.0` — the command said move,
the robot stopped. That's the context the knowledge graph captures.

---

## Why this exists

Jensen Huang's best slide at GTC 2026: *"Structured data is the
foundation of trustworthy AI."*

Physical AI operators are running fleets. They need operational
context, not just replay. This is the data engineering layer
Physical AI is missing.

**Series:** [nudurupati.co](https://nudurupati.co)

---

## Status

- [x] ROS2 Jazzy running natively on Pi 5 (Ubuntu 24.04.3)
- [x] TurtleBot3 fake node publishing live topics
- [x] Foxglove Studio connected via WebSocket bridge
- [x] Edge gateway — delta + keyframe + heartbeat (96% compression)
- [x] Redis Streams — durable cross-machine event transport
- [x] Pathway sliding window metrics + anomaly detection
- [x] Memgraph knowledge graph ingestion
- [x] Cypher operational query library