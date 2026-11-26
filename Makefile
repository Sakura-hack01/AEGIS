.PHONY: test sim plot cpp-bench pages all clean

PYTHON ?= python
CXX ?= g++
CXXFLAGS ?= -std=c++23 -O3 -Wall -Wextra

test:
	$(PYTHON) -m pytest -v

sim:
	$(PYTHON) -m src.cli sim

plot:
	$(PYTHON) -m src.cli plot

cpp-bench:
	$(CXX) $(CXXFLAGS) cpp_inference/uav_edge_pipeline.cpp -o cpp_inference/uav_edge_pipeline
	./cpp_inference/uav_edge_pipeline --frames 2000 --json-out results/cpp_benchmark.json

pages:
	$(PYTHON) -m src.cli serve --port 8000

all: test cpp-bench sim plot

clean:
	rm -rf cpp_inference/uav_edge_pipeline cpp_inference/uav_edge_pipeline.exe cpp_inference/build .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
