# WASI-USB Benchmarks

This directory contains the comprehensive benchmarking suite used to evaluate the performance of USB hardware access in WebAssembly compared to native execution.

Original research and implementation by **IDLab Discover**.

## Role in the Project
The benchmarks measure the overhead introduced by the Wasm sandbox, the WASI-USB interface, and the host runtime. It calculates metrics such as bulk transfer throughput and round-trip latency. The tests compare native C/Rust executions against `libusb-wasi` and `rusb-wasi` executed on the `wasi-usb` host.

## Structure
- **`c/`**: Native and Wasm (libusb) benchmarking logic.
- **`rust/`**: Native and Wasm (rusb) benchmarking logic.
- **`plot.py`**: Python script used to parse the resulting logs and generate Boxplots over KDE plots (found in the thesis text).
- **`build_all.sh`**: Helper script to compile all targets (Native C, Wasm C, Native Rust, Wasm Rust).
- **`run_benchmarks.sh`**: Automation script to run iterations of the tests and record measurements.

## Usage

1. Compile the workloads:
   ```bash
   ./build_all.sh
   ```
2. Execute the test suite (make sure the Pico loopback device is connected):
   ```bash
   ./run_benchmarks.sh
   ```
