cmake_minimum_required(VERSION 3.8)
project(stewie_msgs)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Rock.msg" "msg/RockArray.msg" "msg/ArgusFactor.msg" "msg/ArgusFactorArray.msg"
  "msg/Trajectory.msg" "msg/WorkGoal.msg" "msg/SafeState.msg" "msg/ExecutiveDecision.msg"
  DEPENDENCIES std_msgs geometry_msgs)
ament_package()
