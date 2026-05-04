# WASI-USB

Master's thesis implementation by Sibren Wieme (IDLab Discover, Ghent University, 2025–2026).

**Title:** *Secure USB Access in WebAssembly: A Capability-Based Framework for Cyber-Physical IoT*

The idea is simple: run a WebAssembly component that talks to a USB device, without giving it access to the whole OS. The host runtime exposes only the primitives the guest explicitly needs; everything else is invisible. This repo contains the host runtime, guest examples, WIT interface, benchmark suite (C1–C5) and the supporting docs.

The thesis manuscript lives in `Masterproef_Sibren_Overleaf/` (gitignored, synced separately via Overleaf).

---

## Context

WASI-USB is a proposed [WebAssembly System Interface](https://github.com/WebAssembly/WASI) API for USB hardware access, currently Phase 2. This is the fourth thesis in a series at IDLab Discover building toward that standard:

| # | Author | Year | What they built |
|---|--------|------|-----------------|
| 1 | Wouter Hennen + Warre Dujardin | 2024 | Initial WIT-based host runtime; control + bulk transfers |
| 2 | Friedrich Vandenberghe | 2024 | WASI-I²C (parallel hardware bus interface) |
| 3 | Robbe Leroy | 2025 | `libusb-wasi.a` — WASI backend inside libusb |
| **4** | **Sibren Wieme** | **2026** | **Isochronous extension; backend abstraction; UVC workload; C1–C5 benchmarks** |

WASI-USB champion: Merlijn Sebrechts. Other contributors: Michiel Van Kenhove, Friedrich Vandenberghe.

### Platform support

Developed and tested mainly on Linux (amd64) and macOS (arm64). Windows was not tested; if you want to try, WSL 2 is the path of least resistance.

> **Bulk transfers on macOS**: the `IOUSBMassStorageClass` kernel extension stays attached even after unmounting, so `libusb_set_auto_detach_kernel_driver()` is a no-op there. The bulk benchmark conditions (C1–C5) should be run on Linux. Control and interrupt transfers work fine on both platforms.

---

## Repository layout

```
.
├── wit/                    # WIT source — component:usb@0.2.1
│   ├── device.wit
│   ├── transfers.wit       # includes isochronous extension
│   ├── descriptors.wit
│   ├── configuration.wit
│   ├── errors.wit
│   ├── hotplug.wit
│   └── world.wit
├── usb-wasi-host/          # wasmtime-based host binary (Rust)
│   └── src/
│       ├── main.rs         # WIT implementations, CLI, Wasmtime setup
│       ├── usb_backend.rs  # HostUsbBackend trait + LibusbBackend
│       ├── instrument.rs   # per-call timing + Linux ctx-switch tracing
│       └── host.rs         # generated WIT bindings (do not edit)
├── usb-wasi-guest/         # Rust guest library + example components
│   └── examples/
│       ├── webcam/         # UVC webcam capture
│       ├── mass-storage/   # FAT32 mass storage reader
│       ├── ps5-maze/       # Pacman via PS5 controller
│       ├── xbox-maze/      # Pacman via Xbox controller
│       ├── enumerate-devices-go/  # TinyGo device lister
│       ├── lsusb.rs
│       ├── control.rs
│       ├── ping.rs
│       └── ...
├── usb-wasi-cguest/        # pre-built C bindings for benchmark components
├── benchmarks/             # five-condition benchmark suite
│   ├── usb-bench-c/        # C1 (native libusb) + C2 (WASI libusb)
│   ├── usb-bench-rs/       # C3 (native rusb) + C4 (rusb→WASM) + C5 (raw WIT)
│   ├── build-c4.sh         # cross-compile pipeline for C4
│   ├── run.sh              # benchmark runner
│   └── analyze.py          # result analysis + plots
├── docs/                   # all documentation
├── diagrams/               # PlantUML sources + rendered SVGs
├── libusb-wasi/            # submodule: Robbe Leroy's WASI libusb backend
├── libusb-vanilla/         # submodule: upstream libusb (reference)
├── rusb-wasi/              # submodule: rusb WASI bindings
├── sysroot-wasi/           # pkg-config sysroot for wasm32-wasip2 cross-compile
└── Justfile                # build + run recipes
```

---

## Quick start

```bash
# Clone with submodules
git clone https://github.com/idlab-discover/masters-sibren-wieme.git
cd masters-sibren-wieme
git submodule update --init --recursive

# Build the host runtime
just build-host

# List connected USB devices (no sudo needed)
just lsusb

# Webcam demo — writes frames to out/latest.jpg (sudo required)
mkdir -p out
just webcam
```

---

## Examples

```bash
just lsusb                                      # detailed device listing
just enumerate-devices-rust                     # compact device list
just webcam                                     # UVC capture → out/latest.jpg
just control                                    # control transfer to Arduino
just xbox                                       # Xbox One S controller reader
just ping                                       # bulk OUT/IN echo
just mass-storage tree                          # FAT32 directory tree
just ps5-maze                                   # Pacman via PS5/Xbox controller
just streams-test <vid> <pid> <iface> <out> <in>  # USB 3.0 bulk streams test
just build-all                                  # build everything
```

---

## Benchmarks (C1–C5)

Five conditions that isolate different overhead sources:

| Condition | Language | USB path | What it measures |
|-----------|----------|----------|-----------------|
| C1 | C | native libusb | native C baseline |
| C2 | C | WASI libusb (WIT) | WASM + WIT overhead over C |
| C3 | Rust | native rusb | native Rust baseline |
| C4 | Rust | rusb compiled to WASM | rusb→WASM pipeline (no upstream forks) |
| C5 | Rust | raw WIT bindings | minimal-wrapper WASM overhead |

Three workloads: bulk (SanDisk USB drive), control (Raspberry Pi Pico), interrupt (HID device).

```bash
just bench-build    # build all five conditions
just bench-smoke    # quick sanity run (1 iteration per cell)
just bench-run      # full measurement run (requires USB devices + root)
just bench-analyze  # analyse most recent results/
```

See [docs/benchmarking.md](docs/benchmarking.md) for setup details and the full methodology.

---

## Documentation

- [docs/architecture.md](docs/architecture.md) — host/guest layering, WIT design, capability model, async transfer pattern
- [docs/implementation.md](docs/implementation.md) — the actual contributions: backend abstraction, ISO extension, bug fixes, C4 pipeline, UVC guest
- [docs/benchmarking.md](docs/benchmarking.md) — C1–C5 methodology, workloads, hardware, how to read the results
- [docs/compiling.md](docs/compiling.md) — build instructions for everything, including the cross-compile sysroot
- [docs/thesis.md](docs/thesis.md) — thesis context, chapter-to-code mapping, defense cheat-sheet

Diagrams (PlantUML + SVG) are in [`diagrams/`](diagrams/). To re-render:

```bash
plantuml -tsvg diagrams/*.puml   # for docs
plantuml -tpdf diagrams/*.puml   # for LaTeX
```

---

## WIT design notes

A few things that aren't obvious from reading the WIT files:

- `flags event { arrived; left; }` is a bitflag, not an enum. Check `Event::ARRIVED` / `Event::LEFT`.
- `await-transfer` takes a `borrow<transfer>`, not an owned resource. The host must not delete the borrow slot — see [implementation.md §3.1](docs/implementation.md#31-the-borrow-bug) for what goes wrong if it does.
- Isochronous results use a flat buffer + sidecar metadata: `data: list<u8>` is contiguous packets at fixed stride, `packets: list<iso-packet>` carries per-packet `actual_length` and `status`. One memcpy per transfer through the ABI.
- `enable-hotplug` has no pollable; the guest calls `poll-events` to drain the queue.

---

## Acknowledgements

**Promotors:** Prof. Dr. Bruno Volckaert, Dr. Merlijn Sebrechts

**Begeleiders:** ing. Michiel Vankenhove, Friedrich Vandenberghe

**Voorgangers** (the thesis students who built what this work extends):
Wouter Hennen, Warre Dujardin, Robbe Leroy

---

This work is partially supported by the **ELASTIC project**, funded by the Smart Networks and Services Joint Undertaking (SNS JU) under the European Union's Horizon Europe research and innovation programme, Grant Agreement No 101139067.
