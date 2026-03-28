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
    - Every 10th telemetry event written as Event node
    - All anomalies written immediately with position context
    - Robot node upserted on startup

Anomaly types detected:
    unexpected_stop — velocity > 0.1 drops to < 0.01
    velocity_drop   — velocity drops > 50% in one step

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
import time
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
    """Create indexes for fast lookups."""
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

def write_event(mg, data):
    """Write a telemetry event to Memgraph."""
    mg.execute(f"""
        MATCH (r:Robot {{robot_id: '{data['robot_id']}'}})
        CREATE (e:Event {{
            timestamp: '{data['timestamp']}',
            position_x: {data['position_x']},
            position_y: {data['position_y']},
            linear_vel: {data['linear_vel']},
            angular_vel: {data['angular_vel']},
            event_type: '{data['event_type']}'
        }})
        CREATE (r)-[:GENERATED]->(e)
    """)

def write_anomaly(mg, data, anomaly_type, prev_vel, curr_vel):
    """Write an anomaly node linked to its triggering event."""
    mg.execute(f"""
        MATCH (r:Robot {{robot_id: '{data['robot_id']}'}})
        CREATE (a:Anomaly {{
            type: '{anomaly_type}',
            timestamp: '{data['timestamp']}',
            position_x: {data['position_x']},
            position_y: {data['position_y']},
            prev_velocity: {prev_vel},
            curr_velocity: {curr_vel},
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
    print(f"  ✓ Anomaly written to Memgraph: {anomaly_type} at "
          f"({data['position_x']}, {data['position_y']})")

def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    setup_consumer_group(r)

    mg = Memgraph(MEMGRAPH_HOST, MEMGRAPH_PORT,
                  username=MEMGRAPH_USER, password=MEMGRAPH_PASS)
    ensure_schema(mg)

    # Ensure robot node exists
    upsert_robot(mg, "jazzypi")
    print("[physical-context-fabric] Memgraph ingest started")
    print("-" * 60)

    prev_event = None
    event_count = 0

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
                event_count += 1

                # Write every 10th event to Memgraph (avoid flooding)
                if event_count % 10 == 0:
                    write_event(mg, data)

                # Real-time anomaly detection + write to Memgraph
                if prev_event:
                    prev_vel = float(prev_event["linear_vel"])
                    curr_vel = float(data["linear_vel"])

                    if prev_vel > 0.1 and curr_vel < 0.01:
                        write_anomaly(mg, data, "unexpected_stop",
                                     prev_vel, curr_vel)

                    elif prev_vel > 0.05 and curr_vel < prev_vel * 0.5:
                        write_anomaly(mg, data, "velocity_drop",
                                     prev_vel, curr_vel)

                prev_event = data

if __name__ == '__main__':
    main()