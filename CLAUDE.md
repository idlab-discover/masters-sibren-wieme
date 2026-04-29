# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

This is a **monorepo-of-submodules** for a Master's thesis on capability-based USB access from WebAssembly. The top-level directory holds the benchmark suite and documentation:

- `wasi-usb/` — **canonical host + guest implementation** (Robbe Leroy's runtime). Contains:
  - `usb-wasi-host/` — wasmtime-based host binary that implements the WIT interfaces.
  - `usb-wasi-guest/` — Rust guest library + `examples/` with all demo components.
  - `wit/` — **single source of truth** for `component:usb@0.2.1`.
  - `usb-wasi-cguest/` — pre-built C bindings for benchmark components.
  - `Justfile` — drive all guest builds and run commands.
- `libusb-vanilla/` — upstream libusb, built as `.a` for native benchmark baselines.
- `libusb-wasi/` — Leroy's libusb fork compiled to `wasm32-wasip2`, speaks the WIT interface. Used to build C guests for benchmarks.
- `rusb-wasi/` — Rust rusb fork compiled to `wasm32-wasip2`.
- `benchmarks/` — harness (`build_all.sh`, `run_benchmarks.sh`, `plot.py`), C and Rust benchmark sources, results dir.

The superproject commits only submodule SHA bumps + benchmark changes + top-level docs. Real code changes belong in the respective submodule; commit there first, then bump the submodule ref in the superproject.

## WIT — single source of truth

**`wasi-usb/wit/` is the canonical WIT package.** There is no second copy — any component that needs USB interfaces points to this directory.

The package is `component:usb@0.2.1` and contains six flat interface files plus `world.wit`:
- `errors.wit`, `configuration.wit`, `transfers.wit`, `descriptors.wit`, `device.wit`, `hotplug.wit`
- `world.wit` — defines `host`, `cguest`, `guest`, and `webcam-guest` worlds.

Key design points (relevant for editing):
- Hotplug uses **`flags event { arrived; left; }`** (not `enum`) — consumers must check flags, not match variants. Bitflag constants are uppercase in Rust: `Event::ARRIVED`, `Event::LEFT`.
- `enable-hotplug` returns `result<_, libusb-error>` — no pollable.
- `poll-events` returns `list<tuple<event, info, usb-device>>` — note the tuple order.
- `await-transfer` takes `borrow<transfer>` → generated Rust signature is `await_transfer(xfer: &Transfer)`.
- `await-transfer` returns `TransferResult { data: Vec<u8>, packets: Vec<IsoPacket> }` — no separate `IsoResult` or `await-iso-transfer`.
- `device-handle` has a `close` method; there is **no** `exit` function.
- Package version `@0.2.1` must appear on every `use` that resolves across packages.

## Architecture — dumb host, smart guest

`wasi-usb/usb-wasi-host/` exposes only generic USB primitives (list/open/claim/transfer). No UVC, no MJPEG lives in the host. Everything protocol-specific runs in the guest. The webcam guest handles the full UVC handshake, MJPEG reassembly, and frame output.

Relevant implementation details:
- **Async callback flow**: libusb callbacks run on a dedicated event thread; the WIT `transfer` resource carries a `completed` flag they flip. `main.rs::await_transfer` spins (yields to tokio) until the flag is set.
- **USB 3.0 Bulk Streams**: `TransferOptions.stream_id != 0` triggers `libusb_transfer_set_stream_id`. `stream_id == 0` uses vanilla bulk. `alloc_streams`/`free_streams` on `DeviceHandle` are fully implemented.
- **WASI filesystem**: the host preopens the current working directory as `"."`. Guests write relative paths (`out/latest.jpg`). Run from a directory with an `out/` subdirectory.

## Common commands

### Top-level

```bash
# Webcam demo (Logitech Brio 100 or any UVC camera, sudo required):
cd wasi-usb
mkdir -p out
just webcam   # builds host + webcam guest, then runs with sudo

# Benchmarks:
./benchmarks/build_all.sh
sudo ./benchmarks/run_benchmarks.sh --all
# Individual modes: --latency | --throughput | --init | --streams
python3 benchmarks/plot.py
```

### Inside `wasi-usb/` (uses `just`)

```bash
just build-host                   # cargo build --release -p usb-wasi-host
just build-webcam                 # build webcam sub-crate → out/webcam.wasm
just webcam                       # build + sudo run webcam (mkdir -p out first)
just build-example lsusb          # build a .rs example → out/lsusb.wasm
just lsusb                        # build + sudo run lsusb
just streams-test <vid> <pid> ... # USB 3.0 bulk streams validation
just enumerate-devices-rust       # list all USB devices
just mass-storage tree            # FAT32 mass storage demo
just build-all                    # build everything
```

### Benchmarks — device assumptions

Hardcoded VID/PID:
- **Latency** (USB 2.0 FS): Pico 2 loopback CDC — `cafe:4002`, iface 0, EP OUT `0x01` / IN `0x81`.
- **Throughput** (USB 3.0 SS): SanDisk Ultra — `0781:5581`, iface 0, EP OUT `0x02` / IN `0x81`.

Both devices must be physically attached for `--all`. `--streams` uses only the SanDisk.

Single host for all benchmark modes: `wasi-usb/usb-wasi-host`.

## Guest components

All guest components live in `wasi-usb/usb-wasi-guest/examples/`:

| Component | Type | Description |
|-----------|------|-------------|
| `webcam` | sub-crate | UVC webcam capture → `out/latest.jpg` |
| `lsusb` | `.rs` example | Detailed USB device listing |
| `enumerate-devices-rust` | `.rs` example | Simple device enumeration |
| `control` | `.rs` example | Control transfer to Arduino |
| `ping` | `.rs` example | Bulk OUT/IN echo test |
| `streams-test` | `.rs` example | USB 3.0 bulk streams validation |
| `xbox` | `.rs` example | Xbox One S controller reader |
| `identity` | `.rs` example | Trivial device lister |
| `mass-storage` | sub-crate | FAT32 mass storage (ls/cat/tree/benchmark) |
| `ps5-maze` | sub-crate | Pac-man maze controlled by PS5/Xbox |
| `xbox-maze` | sub-crate | Pac-man maze controlled by Xbox |
| `enumerate-devices-go` | sub-crate | Go/tinygo device lister |

`.rs` examples use inline `wit_bindgen::generate!({ world: "guest", path: "../wit" })`.
Sub-crate guests (webcam, mass-storage, ps5-maze, xbox-maze) have their own `Cargo.toml` and use inline `wit_bindgen::generate!({ world: "guest" or "webcam-guest", path: "../../../wit" })`.

## Editing conventions

- **Never add `Co-Authored-By` lines to commits** — explicit user requirement.
- Commit messages use conventional-commits prefixes (`feat`, `fix`, `refactor`, `chore`).
- The webcam guest uses **inline** `wit_bindgen::generate!` — no pre-generated bindings step needed.
- All guests use `await_transfer(&xfer)` (borrow) and access bytes via `result.data`.
- The WIT `world.wit` is the only file with worlds — interface files contain no worlds.

## Documentation files worth reading first

- `README.md` (top-level) — thesis context, demo invocations, architecture diagram.
- `benchmarks/README.md` — benchmark matrix, variants, statistical design.
- `masterproef_structuur.md`, `workload_compilatie.md` — thesis-oriented narrative docs in Dutch.
