#!/usr/bin/env python3
"""
Physical Context Fabric — Fleet Simulation Launch
Launches 3 TurtleBot3 fake nodes in isolated namespaces.

robot_001 — continuous circles (baseline normal)
robot_002 — waypoint stop/start (triggers stop anomalies)
robot_003 — erratic velocity (triggers velocity_drop anomalies)
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import GroupAction
from launch_ros.actions import PushRosNamespace, Node

os.environ['TURTLEBOT3_MODEL'] = 'burger'

URDF_PATH = os.path.join(
    get_package_share_directory('turtlebot3_gazebo'),
    'urdf', 'turtlebot3_burger.urdf')

PARAM_PATH = os.path.join(
    get_package_share_directory('turtlebot3_fake_node'),
    'param', 'burger.yaml')


def make_robot(robot_id):
    return GroupAction([
        PushRosNamespace(robot_id),
        Node(
            package='turtlebot3_fake_node',
            executable='turtlebot3_fake_node',
            name='turtlebot3_fake_node',
            parameters=[{
                'wheels.separation': 0.160,
                'wheels.radius': 0.033,
                'joint_states_frame': 'base_footprint',
                'odom_frame': robot_id + '/odom',
                'base_frame': robot_id + '/base_footprint',
            }],
            output='screen'
        ),
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            parameters=[{'use_sim_time': False}],
            arguments=[URDF_PATH],
            output='screen'
        ),
    ])


def generate_launch_description():
    return LaunchDescription([
        make_robot('robot_001'),
        make_robot('robot_002'),
        make_robot('robot_003'),
    ])