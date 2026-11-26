cmake_minimum_required(VERSION 3.20)
project(aegis_mach05_edge VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(uav_edge_pipeline uav_edge_pipeline.cpp)

if(MSVC)
    target_compile_options(uav_edge_pipeline PRIVATE /O2 /W4 /std:c++latest)
else()
    target_compile_options(uav_edge_pipeline PRIVATE -O3 -Wall -Wextra -Wpedantic)
endif()
