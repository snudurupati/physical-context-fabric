#!/bin/bash
# robot_002 — stop/start pattern, triggers unexpected_stop anomalies
echo "Starting robot_002 — stop/start waypoints"
source /opt/ros/jazzy/setup.bash
while true; do
  # Move for 8 seconds
  ros2 topic pub /robot_002/cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.15}, angular: {z: 0.3}}" --rate 10 --times 80
  # Stop for 3 seconds
  ros2 topic pub /robot_002/cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.0}, angular: {z: 0.0}}" --rate 10 --times 30
done
