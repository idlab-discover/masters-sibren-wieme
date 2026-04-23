# Secure USB Access in WebAssembly: A Capability-Based Framework for Cyber-Physical IoT
### Veilige USB-toegang in WebAssembly: een capability-gebaseerd raamwerk voor cyber-fysieke IoT-toepassingen

This repository contains the source code, submodules, and documentation for a Master's Thesis focused on bringing safe, portable, and capability-based USB hardware access to WebAssembly (Wasm) via the **WASI-USB** interface.

Original research and implementation are the work of the **contributors**!

## Project Overview

The core objective of this project is to bridge the gap between high-level, sandboxed WebAssembly execution and low-level hardware interaction. By leveraging the WebAssembly Component Model and WASI Preview 2/3, we provide a unified API that works across different operating systems (Linux, macOS) and hardware architectures.

### Key Components

- **[wasi-usb](./wasi-usb/)**: The canonical host runtime and single source of WIT truth. Implements the `component:usb@0.2.1` interface and translates Wasm guest calls into native USB operations. All guest components (webcam, lsusb, mass-storage, …) live under `wasi-usb/usb-wasi-guest/examples/`.
- **[libusb-wasi](./libusb-wasi/)**: A modified version of the standard `libusb` C library, featuring a custom WASI backend to route I/O through the WASI-USB interface.
- **[rusb-wasi](./rusb-wasi/)**: A Rust wrapper for `libusb-wasi`, enabling Rust applications to be compiled to `wasm32-wasip2` with secure USB access.
- **[benchmarks](./benchmarks/)**: A comprehensive benchmarking suite for measuring latency and throughput overhead compared to native execution.

## Architecture

The diagram below illustrates the relationship between the Wasm guest application, the host runtime, and the physical hardware.

```mermaid
graph TD
    App[Wasm Guest Component]
    App -->|Rust wit-bindgen| USB[component:usb@0.2.1 WIT]
    App -->|C libusb-wasi| USB
    USB -->|WASI-USB Interface| Host[usb-wasi-host]
    Host -->|libusb/OS APIs| HW[Physical USB Device]

    subgraph "Wasm Sandbox"
    App
    end

    subgraph "Host Runtime (wasi-usb)"
    USB
    Host
    end
```

**Dumb-host / smart-guest**: the host exposes only generic USB primitives (open/claim/transfer). All protocol-specific logic (UVC, MJPEG, FAT32, HID parsing) lives in the guest component.

## Hardware & Software Support

| Platform | Architecture | Reference Hardware |
|----------|--------------|--------------------|
| macOS    | aarch64      | Apple Silicon (M-series) |
| Linux    | x86_64       | Generic Workstation |
| Linux    | aarch64      | Raspberry Pi 4/5   |

## Getting Started

### 1. Clone the repository
```bash
git clone --recursive https://github.com/idlab-discover/masters-sibren-wieme.git
cd masters-sibren-wieme
```

### 2. Build the host
```bash
cd wasi-usb
just build-host   # cargo build --release -p usb-wasi-host
```

## Running the Demos

### 1. UVC Webcam Capture
A real-time UVC frame-capture demonstration. The webcam guest handles UVC probe/commit negotiation and MJPEG reassembly; the host only provides generic USB primitives.

```bash
cd wasi-usb
mkdir -p out
just webcam   # builds webcam component + runs with sudo
# Captured frames are written to wasi-usb/out/latest.jpg
# Open out/latest.jpg in Preview/feh and press ENTER to refresh
```

### 2. USB Device Listing

```bash
cd wasi-usb && just lsusb
# or enumerate-devices-rust for a compact list
just enumerate-devices-rust
```

### 3. DualSense (PS5) / Xbox Pacman Maze

```bash
cd wasi-usb && just ps5-maze   # PS5 DualSense or Xbox controller
cd wasi-usb && just xbox-maze  # Xbox controller
```

### 4. Mass Storage (FAT32)

```bash
cd wasi-usb && just mass-storage tree
cd wasi-usb && just mass-storage ls /
```

## Benchmarking Suite

```bash
cd benchmarks
./build_all.sh
sudo ./run_benchmarks.sh --all
# or individual modes: --latency | --throughput | --init | --streams
python3 plot.py
```

See [benchmarks/README.md](./benchmarks/README.md) for detailed analysis.

> [!TIP]
> If `just` is not in your `PATH`, install it via `brew install just` (macOS) or `cargo install just`.

## Contributors

This research and implementation is the result of master theses from:
- **Wouter Hennen**
- **Warre Dujardin**
- **Robbe Leroy**
- **Sibren Wieme**

## Licensing

This project is dual-licensed:
- **Infrastructure**: Components derived from the WASI community are subject to their original licenses (Apache 2.0 or LGPL).
- **Original Research**: All original work (USB host implementation, webcam guest, and benchmarks) is licensed under the **MIT License**.

Copyright (c) 2026 the contributors. All rights reserved.
