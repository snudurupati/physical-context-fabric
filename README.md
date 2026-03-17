# Physical Context Fabric

A streaming pipeline + operational knowledge graph for ROS2 robots.

Physical AI generates petabytes of sensor telemetry. Tools like Foxglove
let you replay it. Physical Context Fabric answers what replay can't:
why did the robot fail, what was the full operational context, and does
this pattern recur?

**Stack:** ROS2 Jazzy → Pathway → Memgraph

---

## Architecture

```
jazzypi (Pi 5)                    Mac
──────────────────────            ──────────────────────
ROS2 Jazzy (native)               Foxglove Studio
TurtleBot3 fake node    ───────►  ws://jazzypi:8765
odom_subscriber.py      ───────►  Pathway (stream processing)
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

## Hardware

| Device | Role | OS |
|---|---|---|
| Raspberry Pi 5 16GB + NVMe SSD | ROS2 edge compute | Ubuntu 24.04.3 LTS |
| MacBook Air M4 | Data infrastructure, Foxglove, development | macOS |

---

## Repo Structure

```
physical-context-fabric/
├── ros2_bridge/          # ROS2 → event stream (runs on Pi 5)
│   └── odom_subscriber.py
├── stream_pipeline/      # Pathway anomaly detection (runs on Mac)
├── context_graph/        # Memgraph schema + ingestion (runs on Mac)
├── queries/              # Cypher query library
├── docker/               # Docker setup for Mac development
│   ├── Dockerfile
│   └── docker-compose.yml
├── sim/                  # Gazebo launch files
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
```

### Run the robot

```bash
# Terminal 1 — start fake node
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_fake_node turtlebot3_fake_node.launch.py

# Terminal 2 — publish velocity commands
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.2}, angular: {z: 0.5}}" --rate 10

# Terminal 3 — start Foxglove bridge
ros2 launch foxglove_bridge foxglove_bridge_launch.xml

# Terminal 4 — structured event stream
python3 ros2_bridge/odom_subscriber.py
```

### Connect Foxglove Studio (Mac)

Open Foxglove Studio → Open connection → Foxglove WebSocket →
`ws://192.168.1.119:8765`

---

## What the event stream looks like

```json
{
  "timestamp": 1773718123.64,
  "position": {"x": 0.2869, "y": 0.1216},
  "velocity": {"linear": 0.2, "angular": 0.5},
  "commanded": {"linear": 0.2, "angular": 0.5},
  "event_type": "moving_and_turning"
}
```

This structured event stream is the input to the Pathway pipeline
and ultimately the Memgraph knowledge graph.

---

## Why this exists

Jensen Huang's best slide at GTC 2026: *"Structured data is the
foundation of trustworthy AI."*

Physical AI operators are running fleets. They need operational
context, not just replay. This is the data engineering layer
Physical AI is missing.

**Series:** [nadurupati.co](https://nadurupati.co)

---

## Status

- [x] ROS2 Jazzy running natively on Pi 5 (Ubuntu 24.04.3)
- [x] TurtleBot3 fake node publishing live topics
- [x] odom_subscriber.py — structured JSON event stream
- [x] Foxglove Studio connected via WebSocket bridge
- [ ] Redis bridge (Pi 5 → Mac)
- [ ] Pathway anomaly detection pipeline
- [ ] Memgraph knowledge graph ingestion
- [ ] Cypher query library

---

## Commit Message

```
feat: working ROS2 Jazzy stack on Pi 5 + structured event stream

Hardware setup:
- Raspberry Pi 5 16GB, NVMe SSD, Ubuntu 24.04.3 LTS (jazzypi)
- ROS2 Jazzy installed natively — no Docker, no virtualization
- TurtleBot3 fake node publishing /odom, /cmd_vel, /scan, /tf
- Foxglove bridge running on Pi 5, Studio connecting from Mac
- WiFi configured via netplan, fully wireless deployment

Software:
- odom_subscriber.py: reads /odom + /cmd_vel, emits structured
  JSON events with timestamp, position, velocity, event_type
- Docker setup retained for Mac fallback development

Architecture decision: Pi 5 runs ROS2 edge compute, Mac runs
Pathway + Memgraph data infrastructure. Mirrors real fleet deployments.

Built during GTC 2026 week. Post 1 live at nadurupati.co.
```
