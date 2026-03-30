#!/bin/bash
# robot_003 — erratic velocity changes, triggers velocity_drop anomalies
echo "Starting robot_003 — erratic velocity"
source /opt/ros/jazzy/setup.bash
while true; do
  # Fast
  ros2 topic pub /robot_003/cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.25}, angular: {z: 0.1}}" --rate 10 --times 30
  # Sudden slow
  ros2 topic pub /robot_003/cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.05}, angular: {z: 0.8}}" --rate 10 --times 20
  # Fast again
  ros2 topic pub /robot_003/cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.22}, angular: {z: 0.2}}" --rate 10 --times 25
  # Drop to stop
  ros2 topic pub /robot_003/cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.0}, angular: {z: 0.0}}" --rate 10 --times 15
done
