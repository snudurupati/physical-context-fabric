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
Fleet simulation        ───────►  ws://jazzypi:8765
odom_subscriber.py      ───────►  Redis Streams
                                  Pathway (stream processing)
                                  Memgraph (knowledge graph)
```

The Pi 5 runs the robot compute layer. The Mac runs the data
infrastructure layer. This mirrors real fleet deployments.

---

## Knowledge Graph Schema

```
Robot → Event → Anomaly → Environment_State
```

Core relationships:
- `(Robot)-[:GENERATED]->(Event)`
- `(Robot)-[:EXPERIENCED]->(Anomaly)`
- `(Anomaly)-[:OCCURRED_IN]->(Environment_State)`

The graph answers: *"What was the full context 30 seconds before this failure?"*

---

## Edge Gateway: Delta + Keyframe + Heartbeat

Raw ROS2 telemetry at 10Hz produces 3.6M events/hour per robot. Writing
all of it downstream defeats the purpose of a context layer — you just
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

## Fleet Simulation

Three TurtleBot3 robots run in isolated ROS2 namespaces on jazzypi,
each with a different behavior pattern:

| Robot | Behavior | Anomaly pattern |
|---|---|---|
| `robot_001` | Continuous circles | Baseline — anomalies on stop |
| `robot_002` | Stop/start waypoints | Frequent unexpected_stop |
| `robot_003` | Erratic velocity changes | velocity_drop + unexpected_stop |

All three robots push to a single Redis Stream — the `robot_id` field
differentiates them downstream. Pathway and Memgraph require zero changes
to handle multiple robots.

**Verified fleet query results:**
- `robot_001` — 92 anomalies, hotspots at (-0.5, 0.5) and (0.5, 0.5)
- `robot_002` — 41 anomalies
- `robot_003` — 71 anomalies

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
│   └── odom_subscriber.py   # Fleet delta+keyframe+heartbeat gateway
├── stream_pipeline/          # Pathway anomaly detection (runs on Mac)
│   └── pathway_consumer.py
├── context_graph/            # Memgraph schema + ingestion (runs on Mac)
│   └── memgraph_ingest.py
├── queries/                  # Cypher query library
│   ├── operational_queries.cypher
│   └── README.md
├── docker/                   # Docker setup for Mac
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker-compose-mac.yml
├── sim/                      # Fleet simulation
│   ├── fleet_launch.py       # 3x TurtleBot3 in namespaces
│   ├── drive_robot_001.sh    # Continuous circles
│   ├── drive_robot_002.sh    # Stop/start waypoints
│   ├── drive_robot_003.sh    # Erratic velocity
│   └── start_fleet.sh        # One command starts full stack
└── docs/
```

---

## Quick Start

### One command — full fleet stack

```bash
bash sim/start_fleet.sh
```

This starts everything:
- jazzypi tmux (`pcf`): fleet nodes + drive scripts + foxglove + edge gateway
- Mac tmux (`pcf-mac`): Pathway consumer + Memgraph ingest

```bash
# Attach to logs
ssh ubuntu@jazzypi.local && tmux attach -t pcf     # robot side
tmux attach -t pcf-mac                              # data side
```

---

### Manual setup — jazzypi (Pi 5, one time)

```bash
# Install ROS2 Jazzy on Ubuntu 24.04.3
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

### Manual setup — single robot

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
[INFO] Fleet gateway started | robots=['robot_001', 'robot_002', 'robot_003']
[INFO] robot_001 | received=1400 written=56 ratio=4.0% frame=delta
```

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
  "robot_id": "robot_001",
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

## Cypher Queries

See `queries/operational_queries.cypher` for the full library.
Run in Memgraph Lab at `http://localhost:3000`.

> **Memgraph syntax note:** Omit label filters on node variables in
> relationship patterns and always alias properties in RETURN, using
> aliases in ORDER BY.

```cypher
-- Fleet anomaly summary
MATCH (r)-[:EXPERIENCED]->(a)
RETURN r.robot_id AS robot, a.type AS anomaly_type, count(a) AS total
ORDER BY robot, total DESC;

-- Geographic clustering — where do failures occur?
MATCH (r)-[:EXPERIENCED]->(a)-[:OCCURRED_IN]->(es)
RETURN r.robot_id AS robot,
       round(toFloat(a.position_x) * 2) / 2 AS grid_x,
       round(toFloat(a.position_y) * 2) / 2 AS grid_y,
       count(a) AS anomalies_in_cell
ORDER BY robot, anomalies_in_cell DESC
LIMIT 15;
```

---

## Coming Next: AI-Powered Q&A Interface

> *"The ChatGPT moment for Robotics is here."*

The knowledge graph answers structured queries. The next layer answers
natural language questions:

*"Why did robot_001 keep stopping in the top-left quadrant?"*
*"Which robot is most likely to fail in the next 10 minutes?"*
*"What was the full context 30 seconds before the last anomaly?"*

Architecture: natural language → LLM → Cypher → Memgraph → natural
language answer. Grounded entirely in the operational knowledge graph —
no hallucination, no speculation, only what the robots actually did.

**Status: in progress**

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
- [x] Fleet simulation — 3 robots, isolated namespaces, different behaviors
- [x] Fleet operational queries — anomaly counts, geographic clustering
- [ ] AI-powered Q&A interface — natural language → Cypher