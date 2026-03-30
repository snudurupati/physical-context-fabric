#!/usr/bin/env python3
"""
Physical Context Fabric — Memgraph Ingestion
============================================
Runs on: Mac

Reads from:
    Redis Stream: robot_events (consumer group: memgraph_pcf)

Writes to:
    Memgraph knowledge graph (localhost:7687)

Graph schema:
    (Robot)-[:GENERATED]->(Event)
    (Robot)-[:EXPERIENCED]->(Anomaly)
    (Anomaly)-[:OCCURRED_IN]->(Environment_State)

Ingestion strategy:
    - Uses frame_type from edge gateway — no re-detection needed
    - keyframe/delta events: written every EVENT_WRITE_INTERVAL per robot
    - anomaly frames: always written immediately
    - Robot nodes upserted for all fleet robots on startup
    - Per-robot event counters — no cross-robot interference

Fleet robots:
    robot_001, robot_002, robot_003

Usage:
    source .venv/bin/activate
    python3 context_graph/memgraph_ingest.py

Requirements:
    Memgraph running on localhost:7687 (admin/admin)
    Redis running on localhost:6379
    pip install gqlalchemy redis
"""

from gqlalchemy import Memgraph
import redis
from datetime import datetime

REDIS_HOST = "localhost"
REDIS_PORT = 6379
STREAM_NAME = "robot_events"
CONSUMER_GROUP = "memgraph_pcf"
CONSUMER_NAME = "memgraph_worker_1"

MEMGRAPH_HOST = "localhost"
MEMGRAPH_PORT = 7687
MEMGRAPH_USER = "admin"
MEMGRAPH_PASS = "admin"

FLEET_ROBOTS = ["robot_001", "robot_002", "robot_003"]
EVENT_WRITE_INTERVAL = 100  # write every Nth non-anomaly event per robot


def setup_consumer_group(r):
    try:
        r.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id='0', mkstream=True)
        print(f"Created consumer group: {CONSUMER_GROUP}")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            print(f"Consumer group {CONSUMER_GROUP} already exists")
        else:
            raise


def ensure_schema(mg):
    mg.execute("CREATE INDEX ON :Robot(robot_id);")
    mg.execute("CREATE INDEX ON :Event(timestamp);")
    mg.execute("CREATE INDEX ON :Anomaly(type);")
    print("Schema indexes created")


def upsert_robot(mg, robot_id):
    mg.execute(f"""
        MERGE (r:Robot {{robot_id: '{robot_id}'}})
        ON CREATE SET r.first_seen = '{datetime.now().isoformat()}'
        ON MATCH SET r.last_seen = '{datetime.now().isoformat()}'
    """)
    print(f"  ✓ Robot node upserted: {robot_id}")


def write_event(mg, data):
    mg.execute(f"""
        MATCH (r:Robot {{robot_id: '{data['robot_id']}'}})
        CREATE (e:Event {{
            timestamp: '{data['timestamp']}',
            position_x: {data['position_x']},
            position_y: {data['position_y']},
            linear_vel: {data['linear_vel']},
            angular_vel: {data['angular_vel']},
            event_type: '{data['event_type']}',
            frame_type: '{data.get('frame_type', 'delta')}'
        }})
        CREATE (r)-[:GENERATED]->(e)
    """)


def write_anomaly(mg, data):
    anomaly_type = data.get("anomaly_type", "unknown")
    robot_id = data['robot_id']

    # Step 1: ensure Robot node exists (MERGE not MATCH — never silently fails)
    mg.execute(f"""
        MERGE (r:Robot {{robot_id: '{robot_id}'}})
        ON CREATE SET r.first_seen = '{datetime.now().isoformat()}'
        ON MATCH SET r.last_seen = '{datetime.now().isoformat()}'
    """)

    # Step 2: create Anomaly and relationships separately
    mg.execute(f"""
        MATCH (r:Robot {{robot_id: '{robot_id}'}})
        CREATE (a:Anomaly {{
            type: '{anomaly_type}',
            timestamp: '{data['timestamp']}',
            position_x: {data['position_x']},
            position_y: {data['position_y']},
            linear_vel: {data['linear_vel']},
            commanded_linear: {data['commanded_linear']},
            detected_at: '{datetime.now().isoformat()}'
        }})
        CREATE (es:Environment_State {{
            timestamp: '{data['timestamp']}',
            position_x: {data['position_x']},
            position_y: {data['position_y']}
        }})
        CREATE (r)-[:EXPERIENCED]->(a)
        CREATE (a)-[:OCCURRED_IN]->(es)
    """)
    print(f"  ✓ [{robot_id}] {anomaly_type} at "
          f"({data['position_x']}, {data['position_y']})")

def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    setup_consumer_group(r)

    mg = Memgraph(MEMGRAPH_HOST, MEMGRAPH_PORT,
                  username=MEMGRAPH_USER, password=MEMGRAPH_PASS)
    ensure_schema(mg)

    # Upsert all fleet robots
    for robot_id in FLEET_ROBOTS:
        upsert_robot(mg, robot_id)

    print("[physical-context-fabric] Memgraph ingest started")
    print(f"Fleet: {FLEET_ROBOTS}")
    print("-" * 60)

    # Per-robot event counters — no cross-robot interference
    event_counts = {rid: 0 for rid in FLEET_ROBOTS}

    while True:
        events = r.xreadgroup(
            CONSUMER_GROUP,
            CONSUMER_NAME,
            {STREAM_NAME: ">"},
            count=10,
            block=1000
        )

        if not events:
            continue

        for stream, messages in events:
            for msg_id, data in messages:
                r.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)

                robot_id = data.get("robot_id", "unknown")
                frame_type = data.get("frame_type", "delta")

                # Always write anomaly frames immediately
                if frame_type == "anomaly":
                    write_anomaly(mg, data)
                    continue

                # Write keyframes always — they are ground truth anchors
                if frame_type == "keyframe":
                    write_event(mg, data)
                    continue

                # Write delta/heartbeat every Nth event per robot
                if robot_id in event_counts:
                    event_counts[robot_id] += 1
                    if event_counts[robot_id] % EVENT_WRITE_INTERVAL == 0:
                        write_event(mg, data)


if __name__ == '__main__':
    main()