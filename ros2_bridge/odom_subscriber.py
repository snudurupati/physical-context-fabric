#!/usr/bin/env python3
"""
Physical Context Fabric — ROS2 Odometry Subscriber
Reads /odom and /cmd_vel, emits structured JSON events to stdout.
This is the first layer of the context pipeline.
"""

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
import json
import time

class OdomContextNode(Node):
    def __init__(self):
        super().__init__('odom_context_node')
        self.latest_cmd_vel = {"linear": 0.0, "angular": 0.0}

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
            "timestamp": time.time(),
            "position": {
                "x": round(msg.pose.pose.position.x, 4),
                "y": round(msg.pose.pose.position.y, 4),
            },
            "velocity": {
                "linear": round(linear_vel, 4),
                "angular": round(angular_vel, 4),
            },
            "commanded": self.latest_cmd_vel,
            "event_type": event_type
        }

        print(json.dumps(event), flush=True)


def main():
    rclpy.init()
    node = OdomContextNode()
    print("[physical-context-fabric] odom_context_node started", flush=True)
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
