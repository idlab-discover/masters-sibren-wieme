# Compiling and Benchmarking WASI-USB

This document covers how to build all components of the WASI-USB project: the host runtime,
guest examples, and the full benchmark suite (conditions C1–C5).

---

## 1. Prerequisites

| Tool | Purpose |
|------|---------|
| Rust + `cargo` | Host and Rust guest builds |
| `wasm32-wasip2` target | Cross-compile Rust to WASM (`rustup target add wasm32-wasip2`) |
| `cargo-component` | Component model integration |
| WASI SDK (`/opt/wasi-sdk`) | C guest cross-compilation |
| CMake ≥ 3.20 | C benchmark builds |
| `wasm-tools` | WASM component inspection |
| `just` | Build recipe runner |

---

## 2. Submodule Overview

| Directory | Description |
|-----------|-------------|
| `libusb-vanilla/` | Official, unmodified libusb (reference / C1 native build) |
| `libusb-wasi/` | libusb with WASI backend by Robbe Leroy (C2 and C4 link target) |
| `rusb-wasi/` | Rust rusb wrapper targeting WASI-USB |

---

## 3. Building the Host Runtime

```bash
just build-host
# or:
cd usb-wasi-host && cargo build --release
```

The binary is placed at `usb-wasi-host/target/release/usb-wasi-host`.

---

## 4. Building Guest Examples

```bash
# Single example
just build-example lsusb
just webcam
just mass-storage

# All at once
just build-all
```

Examples are written to `out/*.wasm`.

---

## 5. Benchmark Suite (C1–C5)

The benchmark suite evaluates five conditions across four USB workloads:

| Condition | Language | Target | Transfer path |
|-----------|----------|--------|--------------|
| C1 | C | Native ELF | OS → vanilla libusb → USB |
| C2 | C | WASM component | OS → libusb-wasi.a → WIT → host |
| C3 | Rust | Native ELF | OS → rusb → libusb → USB |
| C4 | Rust | WASM component | OS → rusb → libusb-wasi.a → WIT → host |
| C5 | Rust | WASM component | OS → raw WIT calls → host |

### 5.1 Build all conditions

```bash
just bench-build
```

This runs:
1. **C1** - `cmake -B benchmarks/usb-bench-c/build-native benchmarks/usb-bench-c`
2. **C2** - `cmake -B benchmarks/usb-bench-c/build-wasi benchmarks/usb-bench-c -DCMAKE_TOOLCHAIN_FILE=...`
3. **C3+C5** - `cargo build --release --bins --manifest-path benchmarks/usb-bench-rs/Cargo.toml`
4. **C4** - `bash benchmarks/build-c4.sh` (pkg-config cross-compile via WASI sysroot)

### 5.2 Run benchmarks

```bash
just bench-run          # full run (requires USB devices + root)
just bench-smoke        # 1 iteration per cell (quick sanity check)
just bench-dry          # dry-run: print commands without executing
just bench-analyze      # analyse most recent results/
```

### 5.3 C4 build details (rusb → WASM via pkg-config)

C4 cross-compiles the Rust rusb benchmarks to `wasm32-wasip2` by directing
`pkg-config` to a custom WASI sysroot that points to `libusb-wasi.a` instead
of the host's system libusb. This follows the approach documented in
[libusb1-sys README - Cross-Compiling](https://github.com/dcuddeback/libusb1-sys#cross-compiling).

The sysroot lives at `sysroot-wasi/` and the wrapper script is `benchmarks/build-c4.sh`.

**Prerequisites for C4:**
- `libusb-wasi/libusb-wasi.a` must exist (build from `libusb-wasi/` following its README)
- `benchmarks/usb-bench-c/bindings/guest_component_type.o` must exist (built by C2 step)

---

## 6. Workload Compilation Architecture

This section explains how C and Rust code is compiled to WASI components using the
libusb-wasi and rusb-wasi toolchains.

### 6.1 Overview

```
Application code → rusb/libusb API → libusb-wasi (guest) → WASI-USB WIT interface → host runtime → USB syscalls
```

A guest workload calls `rusb` functions (e.g. `DeviceList::new()`). `rusb` translates these
to `libusb` C functions via FFI. Instead of linking against the standard `libusb` (which
talks directly to the OS), the build links against `libusb-wasi`: a modified libusb that
generates WASI-USB interface calls. These are intercepted by the host runtime and translated
to actual USB system calls.

### 6.2 libusb-wasi: the guest library

`libusb-wasi` (by Robbe Leroy) adds a new backend `wasi_usb.c` to libusb. This backend
implements the same internal libusb interface but replaces OS-specific syscalls with
functions defined in the WASI-USB WIT interface.

The cguest bindings bridge `wasi_usb.c` to the WASI-USB interface:

| File | Content |
|------|---------|
| `cguest.o` | Generated C code calling the WASI-USB functions |
| `cguest_component_type.o` | Metadata: `component-type:cguest` custom section describing the full WIT world |

The build product is `libusb-wasi.a` - a static archive combining all object files.

**Current limitation:** only synchronous transfers are supported. Asynchronous transfers
require threading support not yet standardised in WASI/Wasmtime.

### 6.3 Reactor model

WASI programs use the reactor model (no `main()`), exporting instead:

```c
// C
bool exports_wasi_cli_run_run(void);
```

```rust
// Rust
#[unsafe(no_mangle)]
pub extern "C" fn exports_wasi_cli_run_run() -> bool { true }
```

Compile with `-mexec-model=reactor` (C) or `crate-type = ["cdylib"]` (Rust).

### 6.4 rusb → WASM cross-compilation (C4)

`rusb` uses `libusb1-sys` as its FFI binding crate. At cross-compile time, `pkg-config`
is redirected to the WASI sysroot:

```bash
export PKG_CONFIG_LIBDIR=sysroot-wasi/usr/lib/pkgconfig
export PKG_CONFIG_SYSROOT_DIR=sysroot-wasi
export PKG_CONFIG_ALLOW_CROSS=1
cargo build --target wasm32-wasip2 --features c4-rusb-wasi
```

The `sysroot-wasi/usr/lib/pkgconfig/libusb-1.0.pc` file points to `libusb-wasi/libusb-wasi.a`
and the correct headers, so `libusb1-sys` links against Robbe's WASI build rather than
the host's native libusb.

The component-type metadata (`guest_component_type.o`) is linked via `benchmarks/usb-bench-rs/build.rs`.

### 6.5 Summary table

| Aspect | libusb-wasi | rusb → WASM (C4) |
|--------|-------------|-----------------|
| Author | Robbe Leroy | pkg-config cross-compile config |
| Code changes needed | None | None - only build config |
| Key mechanism | New `wasi_usb.c` WASI backend | `PKG_CONFIG_LIBDIR` redirect |
| Link target | `libusb-wasi.a` | `libusb-wasi.a` via sysroot |
| Build product | `libusb-wasi.a` | `.wasm` component |
| Compile target | `wasm32-wasip2` (WASI SDK) | `wasm32-wasip2` (Cargo + pkg-config) |

---

## 7. Troubleshooting

- **`LIBUSB_ERROR_ACCESS`**: USB access requires root. Always use `sudo`.
- **`libusb-wasi.a not found`**: Build from `libusb-wasi/` first - see its `BUILDING_WASI.md`.
- **`guest_component_type.o not found`**: Run the C2 cmake build step first.
- **`error: could not find Cargo.toml`**: Run cargo commands from the crate root directory.
- **`SCSI Command Failed`**: Unmount the USB drive before running mass-storage benchmarks.
