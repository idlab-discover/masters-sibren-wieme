# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

This is a **monorepo-of-submodules** for a Master's thesis on capability-based USB access from WebAssembly. The top-level directory holds the benchmark suite and documentation; everything else is a git submodule developed independently:

- `usb-wasm/` — primary host + guest implementation. Wasmtime-based host (`usb-wasm/usb-wasm/`), guest bindings crate (`usb-wasm-bindings/`), WIT contracts (`wit/`), and guest components (`command-components/`). Its own `Justfile` drives per-component builds. The webcam demo lives here.
- `wasi-usb/` — Robbe Leroy's host runtime (`usb-wasi-host`). The **canonical WIT source of truth** lives at `wasi-usb/wit/`. Used by benchmark latency/throughput/init runners and by the C-guest path via `libusb-wasi`.
- `libusb-vanilla/` — upstream libusb, built as `.a` for native benchmark baselines.
- `libusb-wasi/` — Leroy's libusb fork compiled to `wasm32-wasip2`, speaks the WIT interface. Used to build C guests for benchmarks.
- `rusb-wasi/` — Rust rusb fork compiled to `wasm32-wasip2`.
- `benchmarks/` — harness (`build_all.sh`, `run_benchmarks.sh`, `plot.py`), C and Rust benchmark sources, results dir.

The superproject commits only submodule SHA bumps + benchmark changes + top-level docs. Real code changes belong in the respective submodule; commit there first, then bump the submodule ref in the superproject.

## WIT — single source of truth

**`wasi-usb/wit/` is the canonical WIT package.** The directory `usb-wasm/wit/` is an **exact mirror** — always kept in sync by `cp -R wasi-usb/wit/* usb-wasm/wit/` (one-directional, wasi-usb is authoritative).

The package is `component:usb@0.2.1` and contains six flat interface files:
- `errors.wit`, `configuration.wit`, `transfers.wit`, `descriptors.wit`, `device.wit`, `hotplug.wit`

Key design points of Leroy's WIT (relevant for editing):
- Hotplug uses **`flags event { arrived; left; }`** (not `enum`) — consumers must check flags, not match variants.
- `enable-hotplug` returns `result<_, libusb-error>` — no pollable.
- `poll-events` returns `list<tuple<event, info, usb-device>>` — note the tuple order.
- `device-handle` has a `close` method; there is **no** `exit` function.
- Package version `@0.2.1` must appear on every `use` that resolves across packages.

`usb-wasm/wit/world.wit` **extends** the mirror with three worlds (not part of wasi-usb's WIT):
- `host` — matches Leroy's host world (imports all six interfaces).
- `cguest` — same imports + exports `wasi:cli/run@0.2.5` (for C/Rust benchmark components).
- `webcam-guest` — same as `cguest` plus filesystem + CLI WASI imports (for the standalone webcam component).

Consumers:
- **usb-wasm host**: `usb-wasm/usb-wasm/src/lib.rs` via `wasmtime::component::bindgen!({ world: "host", path: "../wit" })`. The `with:` key format for versioned packages is `"component:usb/interface@0.2.1/ResourceName"`.
- **webcam guest**: inline `wit_bindgen::generate!({ world: "webcam-guest", path: "../../wit" })` — no pre-generated bindings crate dependency.
- **C/Rust benchmark guests**: use `usb-wasm-bindings` crate (only `cguest` world), or inline proc-macro.

## Architecture — dumb host, smart guest

Both hosts (`usb-wasm/usb-wasm/` and `wasi-usb/usb-wasi-host/`) expose only generic USB primitives (list/open/claim/transfer). No UVC, no MJPEG, no ML lives in any host. Everything protocol-specific runs in the guest. The webcam guest handles the full UVC handshake, MJPEG reassembly, and frame output.

Relevant implementation details:
- **Async callback flow**: libusb callbacks run on a dedicated event thread; the WIT `transfer` resource carries a `completed` flag they flip. `host_impl.rs::await_transfer` spins (yields to tokio) until the flag is set.
- **USB 3.0 Bulk Streams**: dispatched via `libusb_fill_bulk_stream_transfer` when `TransferOptions.stream_id != 0`. `stream_id == 0` uses vanilla bulk. Implemented in both `usb-wasm/usb-wasm/src/usb_backend.rs` and `wasi-usb/usb-wasi-host/src/usb_backend.rs`.
- **Two hosts, same backend logic**: `usb-wasm` has bulk-streams support; `wasi-usb` was ported to match. When editing `usb_backend.rs`, keep both in sync.

## Common commands

### Top-level

```bash
# Webcam demo:
cd usb-wasm && just build-webcam
just webcam   # sudo required on Linux/macOS

# Benchmarks (all modes):
./benchmarks/build_all.sh
sudo ./benchmarks/run_benchmarks.sh --all
# Individual modes: --latency | --throughput | --init | --streams
python3 benchmarks/plot.py
```

`build_all.sh` assumes `/opt/wasi-sdk` exists and `libusb-vanilla` + `rusb-wasi/examples/wasi-workload/wasi-sysroot` are present. It produces:
- C natives: `benchmarks/c/*_native` (linked against `libusb-vanilla/libusb/.libs/libusb-1.0.a`; IOKit/CoreFoundation/Security on macOS).
- C WASI components: `benchmarks/c/*.component.wasm` (via `wasi-sdk clang → wasm-ld → wasm-tools component embed/new --world cguest`).
- Rust variants: `cargo build --release` (native) and `--target wasm32-wasip2` with `PKG_CONFIG_*` pointing at the rusb-wasi sysroot.

### Inside `usb-wasm/` (uses `just`)

```bash
just lsusb                  # list USB devices (lsusb-clone)
just build-webcam           # build the webcam CLI component
just webcam                 # run it with sudo
just enumerate-devices-rust # enumerate via Rust
just streams-test           # USB 3.0 bulk streams validation
cargo build                 # build the wasmtime-usb host binary
```

### Benchmarks — device assumptions

Hardcoded VID/PID:
- **Latency** (USB 2.0 FS): Pico 2 loopback CDC — `cafe:4002`, iface 0, EP OUT `0x01` / IN `0x81`. Sizes 64/128/256/512/1024 B × 10 000 iterations.
- **Throughput** (USB 3.0 SS): SanDisk Ultra — `0781:5581`, iface 0, EP OUT `0x02` / IN `0x81`. Sizes 8/32/128/256/512 MB × 10 runs from LBA 2048.

Both devices must be physically attached for `--all`. `--streams` uses only the SanDisk.

### Host variants used by benchmarks

- `wasi-usb/usb-wasi-host` — used by `--latency`, `--throughput`, `--init`. Drives C + Rust WASI components.
- `usb-wasm/wasmtime-usb` — used by `--streams`. Same backend logic; used here for streams validation with the webcam-capable host binary.

## Editing conventions

- **Never add `Co-Authored-By` lines to commits** — explicit user requirement.
- Commit messages use conventional-commits prefixes (`feat`, `fix`, `refactor`, `chore`).
- `usb-wasm-bindings/src/cguest.rs` is a **generated artefact** checked into git. Regenerate via `usb-wasm-bindings/regenerate-bindings.sh` (uses `wit-bindgen` CLI for the `cguest` world only). Do not hand-edit.
- After changing `wasi-usb/wit/`, always mirror to `usb-wasm/wit/` (excluding `world.wit`): `cp wasi-usb/wit/*.wit usb-wasm/wit/` then verify `diff -r usb-wasm/wit wasi-usb/wit` only shows `world.wit`.
- The webcam guest (`command-components/webcam/`) uses **inline** `wit_bindgen::generate!` — no pre-generated bindings step needed.
- Working guest components as of current HEAD: `lsusb`, `enumerate-devices-rust`, `webcam`, `streams-test`. Several legacy guests (ping, control, mass-storage, xbox, ps5-maze) predate the current WIT shapes and will not compile without updates.

## Documentation files worth reading first

- `README.md` (top-level) — thesis context, demo invocations, architecture diagram.
- `benchmarks/README.md` — benchmark matrix, variants (`libusb_native`, `libusb_wasi`, `rusb_native`, `rusb_wasi`), statistical design.
- `masterproef_structuur.md`, `workload_compilatie.md` — thesis-oriented narrative docs in Dutch.
