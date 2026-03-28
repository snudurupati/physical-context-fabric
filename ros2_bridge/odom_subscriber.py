#!/usr/bin/env python3
"""
Physical Context Fabric — ROS2 Edge Gateway
============================================
Runs on: jazzypi (Raspberry Pi 5, Ubuntu 24.04.3, ROS2 Jazzy)

Implements delta + keyframe + heartbeat strategy for bandwidth-efficient
telemetry streaming. jazzypi acts as an edge processing gateway — not a
raw data forwarder.

Write strategy:
    keyframe  — full state snapshot every KEYFRAME_INTERVAL seconds
                ground truth anchor, always written unconditionally
    delta     — written only when something meaningful changed:
                  position moved > DELTA_POSITION_THRESHOLD meters
                  velocity changed > DELTA_VELOCITY_THRESHOLD m/s
                  event_type changed (stopped → moving etc.)
    anomaly   — always written immediately, never suppressed
                unexpected_stop, velocity_drop
    heartbeat — lightweight alive ping every HEARTBEAT_INTERVAL seconds
                written when robot is stationary and no delta fires

Subscribes to:
    /odom      — robot position and velocity (nav_msgs/Odometry)
    /cmd_vel   — commanded velocity (geometry_msgs/Twist)

Publishes to:
    Redis Stream: robot_events (on Mac at REDIS_HOST)

Event schema:
    timestamp         — Unix timestamp
    robot_id          — hostname of the robot (jazzypi)
    position_x/y      — current position in odom frame
    linear_vel        — actual linear velocity from odometry
    angular_vel       — actual angular velocity from odometry
    commanded_linear  — last commanded linear velocity
    commanded_angular — last commanded angular velocity
    event_type        — stopped | moving | turning | moving_and_turning
    frame_type        — keyframe | delta | anomaly | heartbeat
    anomaly_type      — unexpected_stop | velocity_drop (anomaly frames only)

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

REDIS_HOST = os.getenv("REDIS_HOST", "192.168.1.94")  # Mac IP
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
STREAM_NAME = "robot_events"

# --- Thresholds ---
KEYFRAME_INTERVAL = 30.0         # seconds — full state snapshot
HEARTBEAT_INTERVAL = 60.0        # seconds — alive ping when nothing changes
DELTA_POSITION_THRESHOLD = 0.05  # meters — 5cm movement triggers delta
DELTA_VELOCITY_THRESHOLD = 0.05  # m/s — velocity change triggers delta


class EdgeGatewayNode(Node):
    def __init__(self):
        super().__init__('edge_gateway_node')

        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        self.redis.ping()
        self.get_logger().info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")

        # State tracking
        self.last_keyframe_time = 0.0
        self.last_heartbeat_time = 0.0
        self.last_written_event = None
        self.latest_cmd_vel = {"linear": 0.0, "angular": 0.0}

        # Compression counters
        self.total_received = 0
        self.total_written = 0

        self.odom_sub = self.create_subscription(
            Odometry, '/odom', self.odom_callback, 10)
        self.cmd_sub = self.create_subscription(
            Twist, '/cmd_vel', self.cmd_callback, 10)

    def cmd_callback(self, msg):
        self.latest_cmd_vel = {
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

    def detect_anomaly(self, linear_vel):
        """Check for anomaly relative to last written event."""
        if self.last_written_event is None:
            return False, None
        prev_vel = float(self.last_written_event["linear_vel"])
        if prev_vel > 0.1 and abs(linear_vel) < 0.01:
            return True, "unexpected_stop"
        if prev_vel > 0.05 and linear_vel < prev_vel * 0.5:
            return True, "velocity_drop"
        return False, None

    def should_write_delta(self, x, y, linear_vel, event_type):
        """Return (should_write, reason) based on delta thresholds."""
        if self.last_written_event is None:
            return True, "initial"

        last = self.last_written_event

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

    def build_event(self, x, y, linear_vel, angular_vel,
                    event_type, frame_type, anomaly_type=None):
        event = {
            "timestamp": str(time.time()),
            "robot_id": "jazzypi",
            "position_x": str(round(x, 4)),
            "position_y": str(round(y, 4)),
            "linear_vel": str(round(linear_vel, 4)),
            "angular_vel": str(round(angular_vel, 4)),
            "commanded_linear": str(self.latest_cmd_vel["linear"]),
            "commanded_angular": str(self.latest_cmd_vel["angular"]),
            "event_type": event_type,
            "frame_type": frame_type,
        }
        if anomaly_type:
            event["anomaly_type"] = anomaly_type
        return event

    def write_event(self, event):
        self.redis.xadd(STREAM_NAME, event)
        self.last_written_event = event
        self.total_written += 1

        # Log compression ratio every 100 received events
        if self.total_received > 0 and self.total_received % 100 == 0:
            ratio = round(self.total_written / self.total_received * 100, 1)
            self.get_logger().info(
                f"Compression — received={self.total_received} "
                f"written={self.total_written} "
                f"ratio={ratio}% "
                f"frame={event['frame_type']}"
            )

    def odom_callback(self, msg):
        self.total_received += 1
        now = time.time()

        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        linear_vel = msg.twist.twist.linear.x
        angular_vel = msg.twist.twist.angular.z
        event_type = self.classify_event(linear_vel, angular_vel)

        # --- Priority 1: Heartbeat ---
        # Lightweight alive ping when robot is quiet and nothing else fires.
        # Resets the heartbeat clock so it doesn't fire again for HEARTBEAT_INTERVAL.
        if now - self.last_heartbeat_time >= HEARTBEAT_INTERVAL:
            event = self.build_event(
                x, y, linear_vel, angular_vel, event_type, "heartbeat")
            self.write_event(event)
            self.last_heartbeat_time = now
            return

        # --- Priority 2: Keyframe ---
        # Full state snapshot on a fixed schedule. Ground truth anchor.
        # Resets the keyframe clock.
        if now - self.last_keyframe_time >= KEYFRAME_INTERVAL:
            event = self.build_event(
                x, y, linear_vel, angular_vel, event_type, "keyframe")
            self.write_event(event)
            self.last_keyframe_time = now
            return

        # --- Priority 3: Anomaly ---
        # Always written immediately. Never suppressed by delta logic.
        anomaly, anomaly_type = self.detect_anomaly(linear_vel)
        if anomaly:
            event = self.build_event(
                x, y, linear_vel, angular_vel, event_type,
                "anomaly", anomaly_type)
            self.write_event(event)
            return

        # --- Priority 4: Delta ---
        # Only write if position, velocity, or state meaningfully changed.
        # This is where 90%+ of bandwidth reduction happens.
        should_write, reason = self.should_write_delta(
            x, y, linear_vel, event_type)
        if should_write:
            event = self.build_event(
                x, y, linear_vel, angular_vel, event_type, "delta")
            self.write_event(event)


def main():
    rclpy.init()
    node = EdgeGatewayNode()
    node.get_logger().info(
        f"Edge gateway started | "
        f"keyframe={KEYFRAME_INTERVAL}s | "
        f"heartbeat={HEARTBEAT_INTERVAL}s | "
        f"pos_threshold={DELTA_POSITION_THRESHOLD}m | "
        f"vel_threshold={DELTA_VELOCITY_THRESHOLD}m/s"
    )
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()