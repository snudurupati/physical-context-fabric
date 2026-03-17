FROM --platform=linux/arm64 osrf/ros:humble-desktop

# Install TurtleBot3 packages + foxglove bridge
RUN apt-get update && apt-get install -y \
    ros-humble-turtlebot3 \
    ros-humble-turtlebot3-simulations \
    ros-humble-foxglove-bridge \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Set TurtleBot3 model
ENV TURTLEBOT3_MODEL=burger

# Source ROS2 on every shell
RUN echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc

WORKDIR /workspace
