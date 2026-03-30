#!/bin/bash
# robot_001 — continuous circles, normal baseline behavior
echo "Starting robot_001 — continuous circles"
source /opt/ros/jazzy/setup.bash
while true; do
  ros2 topic pub /robot_001/cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.2}, angular: {z: 0.5}}" --rate 10 --times 50
done
