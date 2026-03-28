#!/usr/bin/env python3
"""
Physical Context Fabric — ROS2 Odometry Subscriber
===================================================
Runs on: jazzypi (Raspberry Pi 5, Ubuntu 24.04.3, ROS2 Jazzy)

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

Usage:
    source ~/pcf-venv/bin/activate
    source /opt/ros/jazzy/setup.bash
    REDIS_HOST=localhost python3 odom_subscriber.py

Environment variables:
    REDIS_HOST  — IP of Mac running Redis (default: localhost)
    REDIS_PORT  — Redis port (default: 6379)
"""

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
import redis
import json
import time
import os

REDIS_HOST = os.getenv("REDIS_HOST", "192.168.1.94")  # Mac IP
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
STREAM_NAME = "robot_events"

class OdomContextNode(Node):
    def __init__(self):
        super().__init__('odom_context_node')
        self.latest_cmd_vel = {"linear": 0.0, "angular": 0.0}

        # Redis connection
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        self.redis.ping()
        self.get_logger().info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")

        self.odom_sub = self.create_subscription(
            Odometry, '/odom', self.odom_callback, 10)
        self.cmd_sub = self.create_subscription(
            Twist, '/cmd_vel', self.cmd_callback, 10)

    def cmd_callback(self, msg):
        self.latest_cmd_vel = {
            "linear": round(msg.linear.x, 4),
            "angular": round(msg.angular.z, 4)
        }

    def odom_callback(self, msg):
        linear_vel = msg.twist.twist.linear.x
        angular_vel = msg.twist.twist.angular.z

        if abs(linear_vel) < 0.01 and abs(angular_vel) < 0.01:
            event_type = "stopped"
        elif abs(linear_vel) >= 0.01 and abs(angular_vel) > 0.1:
            event_type = "moving_and_turning"
        elif abs(linear_vel) >= 0.01:
            event_type = "moving"
        else:
            event_type = "turning"

        event = {
            "timestamp": str(time.time()),
            "robot_id": "jazzypi",
            "position_x": str(round(msg.pose.pose.position.x, 4)),
            "position_y": str(round(msg.pose.pose.position.y, 4)),
            "linear_vel": str(round(linear_vel, 4)),
            "angular_vel": str(round(angular_vel, 4)),
            "commanded_linear": str(self.latest_cmd_vel["linear"]),
            "commanded_angular": str(self.latest_cmd_vel["angular"]),
            "event_type": event_type
        }

        # Push to Redis Stream
        self.redis.xadd(STREAM_NAME, event)


def main():
    rclpy.init()
    node = OdomContextNode()
    node.get_logger().info("odom_context_node started — streaming to Redis")
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
