# WASI-USB - Thesis Implementation

Master's thesis implementation by **Sibren Wieme** (IDLab Discover, Ghent University, 2025–2026).

**Title:** *Secure USB Access in WebAssembly: A Capability-Based Framework for Cyber-Physical IoT*

This repository contains the full implementation artefacts: the wasmtime-based host runtime,
Rust/C guest components, WIT interface definition, benchmark suite (C1–C5) and supporting
documentation. The thesis itself lives in `Masterproef_Sibren_Overleaf/` (gitignored, synced via Overleaf).

---

## WASI-USB context

WASI-USB is a proposed [WebAssembly System Interface](https://github.com/WebAssembly/WASI) API for USB hardware access, currently in **Phase 2**. This thesis is the third in a series at IDLab Discover:

| # | Author | Year | Contribution |
|---|--------|------|--------------|
| 1 | Wouter Hennen + Warre Dujarding | 2024 | Initial WIT-based host runtime; control + bulk transfers |
| 2 | Robbe Leroy | 2025 | `libusb-wasi.a` - WASI backend inside libusb |
| **3** | **Sibren Wieme** | **2026** | **Isochronous extension; backend abstraction; UVC CPS workload; C1–C5 benchmark evaluation** |

**Champions / contributors:** Merlijn Sebrechts (champion), Michiel Van Kenhove, Friedrich Vandenberghe, Sibren Wieme

### Portability targets

| Platform | Architecture | Reference hardware | Notes |
|----------|--------------|--------------------|-------|
| Linux    | amd64        |                    |       |
| Linux    | aarch64      | Raspberry Pi 4     |       |
| macOS    | aarch64      | MacBook Pro M3 MAX |       |
| *Windows*  | *amd64*        | *HP Omen 5*        | *Not tested yet* |

---

## Repository layout

```
.
├── wit/                    # WIT source - component:usb@0.2.1
│   ├── device.wit          # USB device management + hotplug
│   ├── transfers.wit       # Transfer types, options, results (incl. ISO extension)
│   ├── descriptors.wit     # Device/config/interface/endpoint descriptors
│   ├── configuration.wit   # Configuration values
│   ├── errors.wit          # libusb error codes
│   ├── hotplug.wit         # Hotplug events
│   └── world.wit           # host / guest / cguest / webcam-guest worlds
├── usb-wasi-host/          # wasmtime-based host binary (Rust)
│   ├── src/
│   │   ├── main.rs         # WIT method implementations, CLI, transfer callback, Wasmtime setup
│   │   ├── usb_backend.rs  # HostUsbBackend trait + LibusbBackend implementation
│   │   ├── host.rs         # Generated WIT bindings (do not edit)
│   │   └── instrument.rs   # RAII CallTrace guard - per-call duration + ctx-switch tracing
│   └── Cargo.toml
├── usb-wasi-guest/         # Rust guest library + examples
│   └── examples/
│       ├── webcam/         # UVC webcam capture (sub-crate)
│       ├── mass-storage/   # FAT32 mass storage (sub-crate)
│       ├── ps5-maze/       # Pacman - PS5/Xbox (sub-crate)
│       ├── xbox-maze/      # Pacman - Xbox (sub-crate)
│       ├── enumerate-devices-go/  # TinyGo device lister
│       ├── lsusb.rs        # Detailed USB device listing
│       ├── enumerate-devices-rust.rs
│       ├── control.rs      # Control transfer example
│       ├── ping.rs         # Bulk OUT/IN echo
│       ├── streams-test.rs # USB 3.0 bulk streams validation
│       ├── xbox.rs         # Xbox controller reader
│       └── identity.rs     # Trivial device lister
├── usb-wasi-cguest/        # Pre-built C bindings for benchmark components
├── benchmarks/             # Five-condition benchmark suite (C1–C5)
│   ├── usb-bench-c/        # C1 (native libusb) + C2 (WASI libusb via CMake)
│   ├── usb-bench-rs/       # C3 (native rusb) + C4 (rusb→WASM) + C5 (raw WIT)
│   ├── usb-native/         # C3 native Rust baseline
│   ├── build-c4.sh         # Cross-compile pipeline for C4 (rusb → WASM)
│   ├── run.sh              # Benchmark runner
│   └── analyze.py          # Result analysis + plots
├── docs/                   # All documentation (start here)
├── diagrams/               # PlantUML sources + rendered SVGs
├── libusb-wasi/            # Submodule: Robbe Leroy's WASI libusb backend
├── libusb-vanilla/         # Submodule: upstream libusb (reference)
├── rusb-wasi/              # Submodule: rusb WASI bindings
├── sysroot-wasi/           # pkg-config sysroot for wasm32-wasip2 cross-compile
└── Justfile                # Build + run recipes
```

---

## Quick start

```bash
# Build the host runtime
just build-host

# List connected USB devices
just lsusb

# Webcam demo (UVC, sudo required) - frames written to out/latest.jpg
mkdir -p out
just webcam

# USB 3.0 bulk streams validation
just streams-test 0781 5581 0 0x02 0x81
```

---

## Examples

| Command | Description |
|---------|-------------|
| `just lsusb` | Detailed device listing |
| `just enumerate-devices-rust` | Compact device list |
| `just webcam` | UVC capture → `out/latest.jpg` |
| `just control` | Control transfer to Arduino |
| `just xbox` | Xbox One S controller reader |
| `just ping` | Bulk OUT/IN echo |
| `just streams-test <vid> <pid> <iface> <ep_out> <ep_in>` | Bulk streams test |
| `just mass-storage tree` | FAT32 directory tree |
| `just ps5-maze` | Pacman controlled by PS5/Xbox |
| `just build-all` | Build everything |

---

## Benchmarks (C1–C5)

The thesis evaluation uses five conditions that isolate different overhead sources:

| Condition | Language | USB path | What it isolates |
|-----------|----------|----------|-----------------|
| C1 | C | native libusb | baseline native performance |
| C2 | C | WASI libusb (via WIT) | WASM + WIT overhead |
| C3 | Rust | native rusb | Rust vs C native |
| C4 | Rust | rusb compiled to WASM (no upstream forks) | rusb→WASM pipeline overhead |
| C5 | Rust | raw WIT bindings | minimal-wrapper WASM overhead |

```bash
just bench-build   # build all five conditions
just bench-smoke   # quick sanity run (1 iteration per cell)
just bench-run     # full measurement run (requires USB devices + root)
just bench-analyze # analyse most recent results/
```

See **[docs/benchmarking.md](docs/benchmarking.md)** for the full methodology.

---

## Documentation

| Document | Contents |
|----------|----------|
| **[docs/architecture.md](docs/architecture.md)** | System architecture - host/guest layering, WIT design, capability model, async transfer pattern, threading model |
| **[docs/implementation.md](docs/implementation.md)** | Concrete contributions - backend abstraction, ISO extension, bug fixes, C4 pipeline, UVC guest, benchmark suite |
| **[docs/benchmarking.md](docs/benchmarking.md)** | C1–C5 benchmark methodology, workloads, hardware, analysis |
| **[docs/compiling.md](docs/compiling.md)** | Build instructions - host, all guest examples, all five benchmark conditions, cross-compile sysroot |
| **[docs/thesis.md](docs/thesis.md)** | Thesis context, claimed contributions, doc-to-chapter mapping, defense cheat-sheet |

Diagrams (PlantUML sources + rendered SVG) live in [`diagrams/`](diagrams/):
host/guest architecture, transfer lifecycle, capability model, ISO flat-buffer
strategy, C4 cross-compile pipeline.

To re-render after edits:

```bash
plantuml -tsvg diagrams/*.puml   # SVG (for docs)
plantuml -tpdf diagrams/*.puml   # PDF (for LaTeX)
```

---

## WIT design notes

- `flags event { arrived; left; }` - bitflags, not an enum. Check `Event::ARRIVED` / `Event::LEFT`.
- `await-transfer(borrow<transfer>) -> result<transfer-result, libusb-error>` - borrow semantics; the host must **not** delete the borrow slot.
- Isochronous results: `TransferResult { data: list<u8>, packets: list<iso-packet> }` - flat buffer + sidecar metadata (one memcpy per transfer through the component ABI).
- `enable-hotplug` returns `result<_, libusb-error>` - no pollable; guest calls `poll-events` to drain the queue.

---

## Acknowledgements

Code, advice and feedback from: Warre Dujardin, Wouter Hennen, Robbe Leroy, Friedrich Vandenberghe, Michiel Vankenhove, Merlijn Sebrechts, Bruno Volckaert.

This work is partially supported by the **ELASTIC project**, funded by the Smart Networks and Services Joint Undertaking (SNS JU) under the European Union's Horizon Europe research and innovation programme, Grant Agreement No 101139067.
