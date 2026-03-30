#!/usr/bin/env python3
"""
Physical Context Fabric — ROS2 Fleet Edge Gateway
==================================================
Runs on: jazzypi (Raspberry Pi 5, Ubuntu 24.04.3, ROS2 Jazzy)

Subscribes to namespaced topics for a 3-robot fleet:
    /robot_001/odom, /robot_001/cmd_vel
    /robot_002/odom, /robot_002/cmd_vel
    /robot_003/odom, /robot_003/cmd_vel

Implements delta + keyframe + heartbeat per robot independently.
All robots publish to a single Redis Stream: robot_events.
The robot_id field differentiates robots downstream.

Write strategy (per robot):
    keyframe  — full state every KEYFRAME_INTERVAL seconds
    delta     — position >5cm, velocity >0.05 m/s, state change
    anomaly   — always written, never suppressed
    heartbeat — alive ping every HEARTBEAT_INTERVAL seconds

Publishes to:
    Redis Stream: robot_events (on Mac at REDIS_HOST)

Event schema:
    timestamp         — Unix timestamp
    robot_id          — robot_001 | robot_002 | robot_003
    position_x/y      — current position in odom frame
    linear_vel        — actual linear velocity from odometry
    angular_vel       — actual angular velocity from odometry
    commanded_linear  — last commanded linear velocity
    commanded_angular — last commanded angular velocity
    event_type        — stopped | moving | turning | moving_and_turning
    frame_type        — keyframe | delta | anomaly | heartbeat
    anomaly_type      — unexpected_stop | velocity_drop (anomaly only)

Usage:
    source ~/pcf-venv/bin/activate
    source /opt/ros/jazzy/setup.bash
    REDIS_HOST=192.168.1.94 python3 odom_subscriber.py

Environment variables:
    REDIS_HOST  — IP of Mac running Redis (default: 192.168.1.94)
    REDIS_PORT  — Redis port (default: 6379)
"""

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
import redis
import math
import time
import os

REDIS_HOST = os.getenv("REDIS_HOST", "192.168.1.94")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
STREAM_NAME = "robot_events"

ROBOT_IDS = ['robot_001', 'robot_002', 'robot_003']

# --- Thresholds ---
KEYFRAME_INTERVAL = 30.0         # seconds
HEARTBEAT_INTERVAL = 60.0        # seconds
DELTA_POSITION_THRESHOLD = 0.05  # meters
DELTA_VELOCITY_THRESHOLD = 0.05  # m/s


class FleetEdgeGateway(Node):
    def __init__(self):
        super().__init__('fleet_edge_gateway')

        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        self.redis.ping()
        self.get_logger().info(
            f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")

        # Per-robot state tracking
        self.latest_cmd_vel = {
            rid: {"linear": 0.0, "angular": 0.0} for rid in ROBOT_IDS}
        self.last_written_event = {rid: None for rid in ROBOT_IDS}
        self.last_keyframe_time = {rid: 0.0 for rid in ROBOT_IDS}
        self.last_heartbeat_time = {rid: 0.0 for rid in ROBOT_IDS}

        # Per-robot compression counters
        self.total_received = {rid: 0 for rid in ROBOT_IDS}
        self.total_written = {rid: 0 for rid in ROBOT_IDS}

        # Subscribe to all robots
        for robot_id in ROBOT_IDS:
            self.create_subscription(
                Odometry,
                f'/{robot_id}/odom',
                lambda msg, rid=robot_id: self.odom_callback(msg, rid),
                10)
            self.create_subscription(
                Twist,
                f'/{robot_id}/cmd_vel',
                lambda msg, rid=robot_id: self.cmd_callback(msg, rid),
                10)

        self.get_logger().info(
            f"Fleet gateway started | robots={ROBOT_IDS} | "
            f"keyframe={KEYFRAME_INTERVAL}s | "
            f"heartbeat={HEARTBEAT_INTERVAL}s | "
            f"pos_threshold={DELTA_POSITION_THRESHOLD}m | "
            f"vel_threshold={DELTA_VELOCITY_THRESHOLD}m/s"
        )

    def cmd_callback(self, msg, robot_id):
        self.latest_cmd_vel[robot_id] = {
            "linear": round(msg.linear.x, 4),
            "angular": round(msg.angular.z, 4)
        }

    def classify_event(self, linear_vel, angular_vel):
        if abs(linear_vel) < 0.01 and abs(angular_vel) < 0.01:
            return "stopped"
        elif abs(linear_vel) >= 0.01 and abs(angular_vel) > 0.1:
            return "moving_and_turning"
        elif abs(linear_vel) >= 0.01:
            return "moving"
        else:
            return "turning"

    def euclidean_distance(self, x1, y1, x2, y2):
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    def detect_anomaly(self, robot_id, linear_vel):
        last = self.last_written_event[robot_id]
        if last is None:
            return False, None
        prev_vel = float(last["linear_vel"])
        if prev_vel > 0.1 and abs(linear_vel) < 0.01:
            return True, "unexpected_stop"
        if prev_vel > 0.05 and linear_vel < prev_vel * 0.5:
            return True, "velocity_drop"
        return False, None

    def should_write_delta(self, robot_id, x, y, linear_vel, event_type):
        last = self.last_written_event[robot_id]
        if last is None:
            return True, "initial"

        dist = self.euclidean_distance(
            float(last["position_x"]), float(last["position_y"]), x, y)
        if dist > DELTA_POSITION_THRESHOLD:
            return True, "position_delta"

        vel_change = abs(linear_vel - float(last["linear_vel"]))
        if vel_change > DELTA_VELOCITY_THRESHOLD:
            return True, "velocity_delta"

        if event_type != last["event_type"]:
            return True, "state_change"

        return False, None

    def build_event(self, robot_id, x, y, linear_vel, angular_vel,
                    event_type, frame_type, anomaly_type=None):
        event = {
            "timestamp": str(time.time()),
            "robot_id": robot_id,
            "position_x": str(round(x, 4)),
            "position_y": str(round(y, 4)),
            "linear_vel": str(round(linear_vel, 4)),
            "angular_vel": str(round(angular_vel, 4)),
            "commanded_linear": str(
                self.latest_cmd_vel[robot_id]["linear"]),
            "commanded_angular": str(
                self.latest_cmd_vel[robot_id]["angular"]),
            "event_type": event_type,
            "frame_type": frame_type,
        }
        if anomaly_type:
            event["anomaly_type"] = anomaly_type
        return event

    def write_event(self, robot_id, event):
        self.redis.xadd(STREAM_NAME, event)
        self.last_written_event[robot_id] = event
        self.total_written[robot_id] += 1

        if (self.total_received[robot_id] > 0 and
                self.total_received[robot_id] % 100 == 0):
            ratio = round(
                self.total_written[robot_id] /
                self.total_received[robot_id] * 100, 1)
            self.get_logger().info(
                f"{robot_id} | received={self.total_received[robot_id]} "
                f"written={self.total_written[robot_id]} "
                f"ratio={ratio}% frame={event['frame_type']}"
            )

    def odom_callback(self, msg, robot_id):
        self.total_received[robot_id] += 1
        now = time.time()

        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        linear_vel = msg.twist.twist.linear.x
        angular_vel = msg.twist.twist.angular.z
        event_type = self.classify_event(linear_vel, angular_vel)

        # Priority 1: Heartbeat
        if now - self.last_heartbeat_time[robot_id] >= HEARTBEAT_INTERVAL:
            event = self.build_event(
                robot_id, x, y, linear_vel, angular_vel,
                event_type, "heartbeat")
            self.write_event(robot_id, event)
            self.last_heartbeat_time[robot_id] = now
            return

        # Priority 2: Keyframe
        if now - self.last_keyframe_time[robot_id] >= KEYFRAME_INTERVAL:
            event = self.build_event(
                robot_id, x, y, linear_vel, angular_vel,
                event_type, "keyframe")
            self.write_event(robot_id, event)
            self.last_keyframe_time[robot_id] = now
            return

        # Priority 3: Anomaly — never suppressed
        anomaly, anomaly_type = self.detect_anomaly(robot_id, linear_vel)
        if anomaly:
            event = self.build_event(
                robot_id, x, y, linear_vel, angular_vel,
                event_type, "anomaly", anomaly_type)
            self.write_event(robot_id, event)
            return

        # Priority 4: Delta
        should_write, reason = self.should_write_delta(
            robot_id, x, y, linear_vel, event_type)
        if should_write:
            event = self.build_event(
                robot_id, x, y, linear_vel, angular_vel,
                event_type, "delta")
            self.write_event(robot_id, event)


def main():
    rclpy.init()
    node = FleetEdgeGateway()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()