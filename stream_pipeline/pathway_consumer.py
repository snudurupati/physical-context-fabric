#!/usr/bin/env python3
"""
Physical Context Fabric — Pathway Stream Consumer
=================================================
Runs on: Mac

Reads from:
    Redis Stream: robot_events

Computes:
    - Sliding window metrics (50 events, ~5 seconds at 10Hz)
      avg/max/min linear velocity, stop ratio, moving count
    - Real-time anomaly detection:
      unexpected_stop — velocity > 0.1 drops to < 0.01
      velocity_drop   — velocity drops > 50% in one step

Output:
    stdout — window metrics every 10 events
    stdout — anomaly alerts with position context

Usage:
    source .venv/bin/activate
    python3 stream_pipeline/pathway_consumer.py
"""

import pathway as pw
import redis
import json
import time
from datetime import datetime

REDIS_HOST = "localhost"
REDIS_PORT = 6379
STREAM_NAME = "robot_events"
CONSUMER_GROUP = "pathway_pcf"
CONSUMER_NAME = "pathway_worker_1"

def setup_consumer_group(r):
    try:
        r.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id='0', mkstream=True)
        print(f"Created consumer group: {CONSUMER_GROUP}")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            print(f"Consumer group {CONSUMER_GROUP} already exists")
        else:
            raise

def detect_anomaly(events):
    """
    Anomaly detection on a window of events.
    Rules:
    - unexpected_stop: velocity was > 0.1 then dropped to 0 for 3+ consecutive events
    - velocity_drop: linear_vel dropped > 50% in one step
    """
    anomalies = []
    for i in range(1, len(events)):
        prev = events[i-1]
        curr = events[i]

        prev_vel = float(prev["linear_vel"])
        curr_vel = float(curr["linear_vel"])

        # Unexpected stop
        if prev_vel > 0.1 and float(curr["linear_vel"]) < 0.01:
            anomalies.append({
                "type": "unexpected_stop",
                "timestamp": curr["timestamp"],
                "position_x": curr["position_x"],
                "position_y": curr["position_y"],
                "prev_velocity": prev_vel,
                "curr_velocity": curr_vel
            })

        # Velocity drop > 50%
        if prev_vel > 0.05 and curr_vel < prev_vel * 0.5:
            anomalies.append({
                "type": "velocity_drop",
                "timestamp": curr["timestamp"],
                "position_x": curr["position_x"],
                "position_y": curr["position_y"],
                "prev_velocity": prev_vel,
                "curr_velocity": curr_vel,
                "drop_pct": round((1 - curr_vel/prev_vel) * 100, 1)
            })

    return anomalies

def compute_window_metrics(events):
    """Compute metrics over a window of events."""
    if not events:
        return {}

    linear_vels = [float(e["linear_vel"]) for e in events]
    angular_vels = [float(e["angular_vel"]) for e in events]
    event_types = [e["event_type"] for e in events]

    return {
        "window_size": len(events),
        "avg_linear_vel": round(sum(linear_vels) / len(linear_vels), 4),
        "max_linear_vel": round(max(linear_vels), 4),
        "min_linear_vel": round(min(linear_vels), 4),
        "avg_angular_vel": round(sum(angular_vels) / len(angular_vels), 4),
        "stopped_count": event_types.count("stopped"),
        "moving_count": event_types.count("moving") + 
                       event_types.count("moving_and_turning"),
        "stop_ratio": round(event_types.count("stopped") / len(events), 3)
    }

def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    setup_consumer_group(r)

    print("[physical-context-fabric] Pathway consumer started")
    print(f"Reading from Redis Stream: {STREAM_NAME}")
    print("-" * 60)

    window = []
    WINDOW_SIZE = 50  # ~5 seconds at 10Hz
    prev_event = None

    while True:
        # Read new events from Redis Stream
        events = r.xreadgroup(
            CONSUMER_GROUP,
            CONSUMER_NAME,
            {STREAM_NAME: ">"},
            count=10,
            block=1000  # block 1s waiting for new events
        )

        if not events:
            continue

        for stream, messages in events:
            for msg_id, data in messages:
                window.append(data)

                # Acknowledge message
                r.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                # Real-time transition detection
                if prev_event:
                    prev_vel = float(prev_event["linear_vel"])
                    curr_vel = float(data["linear_vel"])
                    if prev_vel > 0.1 and curr_vel < 0.01:
                        print(f"\n  ⚠️  ANOMALY: unexpected_stop at "
                            f"({data['position_x']}, {data['position_y']})")
                prev_event = data

                # Keep window at fixed size
                if len(window) > WINDOW_SIZE:
                    window.pop(0)

                # Compute metrics every 10 events
                if len(window) % 10 == 0 and len(window) >= 10:
                    metrics = compute_window_metrics(window)
                    anomalies = detect_anomaly(window[-10:])

                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] "
                          f"Window metrics ({metrics['window_size']} events):")
                    print(f"  avg_linear_vel : {metrics['avg_linear_vel']}")
                    print(f"  avg_angular_vel: {metrics['avg_angular_vel']}")
                    print(f"  stop_ratio     : {metrics['stop_ratio']}")
                    print(f"  moving_count   : {metrics['moving_count']}")
                    print(f"  stopped_count  : {metrics['stopped_count']}")

                    if anomalies:
                        for a in anomalies:
                            print(f"\n  ⚠️  ANOMALY DETECTED: {a['type']}")
                            print(f"     position: ({a['position_x']}, {a['position_y']})")
                            print(f"     velocity: {a['prev_velocity']} → {a['curr_velocity']}")

if __name__ == '__main__':
    main()
