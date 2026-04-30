# Building WASI-USB from Scratch

This document walks you through building the complete WASI-USB project from a fresh clone:
the host runtime, guest examples, and the full benchmark suite (conditions C1-C5). It
covers Linux, macOS, and Windows, including what to install before you start.

---

## 1. Prerequisites

You need the following tools. The sections below show how to install them per platform.

| Tool | Purpose |
|------|---------|
| Rust + `cargo` | Host binary and Rust guest builds |
| `wasm32-wasip2` target | Rust cross-compilation to WASM (`rustup target add wasm32-wasip2`) |
| `cargo-component` | WASI component model wrapper for Rust crates |
| WASI SDK | C/C++ cross-compilation to WASM (provides `wasm32-wasip2-clang` etc.) |
| CMake >= 3.20 | C benchmark builds |
| `wasm-tools` | Inspecting and composing WASM components |
| `just` | Build recipe runner |
| autoconf, automake, libtool | Needed to regenerate `configure` in `libusb-wasi/` |
| pkg-config | Used by the C4 cross-compile pipeline |

### 1.1 Linux (Debian/Ubuntu)

```bash
# Basic build tools
sudo apt update
sudo apt install -y build-essential cmake autoconf automake libtool pkg-config curl git

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
rustup target add wasm32-wasip2

# cargo-component and wasm-tools
cargo install cargo-component wasm-tools

# just
cargo install just
# or: sudo apt install just  (available in newer Ubuntu/Debian)

# WASI SDK - download the latest release from GitHub
# https://github.com/WebAssembly/wasi-sdk/releases
# Example for wasi-sdk-25:
wget https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-25/wasi-sdk-25.0-x86_64-linux.tar.gz
tar xf wasi-sdk-25.0-x86_64-linux.tar.gz
sudo mv wasi-sdk-25.0-x86_64-linux /opt/wasi-sdk
export WASI_SDK_PATH=/opt/wasi-sdk
# Add to ~/.bashrc or ~/.profile to make it permanent:
echo 'export WASI_SDK_PATH=/opt/wasi-sdk' >> ~/.bashrc
```

### 1.2 macOS

```bash
# Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Build tools
brew install cmake autoconf automake libtool pkg-config git just

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
rustup target add wasm32-wasip2

# cargo-component and wasm-tools
cargo install cargo-component wasm-tools

# WASI SDK - download from GitHub releases
# https://github.com/WebAssembly/wasi-sdk/releases
# Example for wasi-sdk-25 on Apple Silicon:
curl -LO https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-25/wasi-sdk-25.0-arm64-macos.tar.gz
tar xf wasi-sdk-25.0-arm64-macos.tar.gz
sudo mv wasi-sdk-25.0-arm64-macos /opt/wasi-sdk
export WASI_SDK_PATH=/opt/wasi-sdk
# For x86_64 Macs, replace 'arm64' with 'x86_64' in the filename above.
# Add to ~/.zshrc to make it permanent:
echo 'export WASI_SDK_PATH=/opt/wasi-sdk' >> ~/.zshrc
```

### 1.3 Windows

Windows support is limited. The host binary builds fine with Rust on Windows, but the
benchmark suite (C1/C2 CMake builds, C4 pkg-config pipeline) relies on Unix shell scripts
and was only tested on Linux and macOS.

For Windows, the recommended approach is to use **WSL 2** (Windows Subsystem for Linux)
and follow the Linux instructions above. This is what I used during development when
working on a Windows machine.

If you specifically need a native Windows build for the host:

```powershell
# Install Rust via the official installer
winget install Rustlang.Rustup
# Then in a new terminal:
rustup target add wasm32-wasip2
cargo install cargo-component wasm-tools just

# CMake
winget install Kitware.CMake

# WASI SDK - download the Windows tarball from GitHub releases
# https://github.com/WebAssembly/wasi-sdk/releases
# Extract to C:\wasi-sdk and add to PATH
```

For the benchmark builds on Windows you will still need a Unix shell (WSL or Git Bash
with autoconf/automake). The full benchmark pipeline has not been tested natively on Windows.

---

## 2. Getting the Code

The repository uses git submodules (`libusb-wasi`, `libusb-vanilla`, `rusb-wasi`). Make
sure to initialise them:

```bash
git clone https://github.com/idlab-discover/masters-sibren-wieme.git
cd masters-sibren-wieme
git submodule update --init --recursive
```

If you already cloned without `--recursive`:

```bash
git submodule update --init --recursive
```

---

## 3. Submodule Overview

| Directory | Description |
|-----------|-------------|
| `libusb-vanilla/` | Official, unmodified libusb (used for C1 native build) |
| `libusb-wasi/` | libusb with WASI backend by Robbe Leroy (used for C2 and C4) |
| `rusb-wasi/` | Rust rusb wrapper targeting the WASI-USB interface |

---

## 4. Building the Host Runtime

```bash
just build-host
# or:
cd usb-wasi-host && cargo build --release
```

The binary is placed at `usb-wasi-host/target/release/usb-wasi-host`.

---

## 5. Building Guest Examples

```bash
# Single example
just build-example lsusb
just webcam
just mass-storage

# All at once
just build-all
```

Examples are written to `out/*.wasm`. Run them with `sudo` because USB access requires root:

```bash
just lsusb                          # list connected USB devices
just webcam                         # capture webcam frames via UVC
just mass-storage -- /path/to/file  # FAT32 read on a USB drive
```

---

## 6. Benchmark Suite (C1-C5)

The benchmark suite evaluates five conditions across four USB workloads:

| Condition | Language | Target | Transfer path |
|-----------|----------|--------|--------------|
| C1 | C | Native ELF | OS -> vanilla libusb -> USB |
| C2 | C | WASM component | OS -> libusb-wasi.a -> WIT -> host |
| C3 | Rust | Native ELF | OS -> rusb -> libusb -> USB |
| C4 | Rust | WASM component | OS -> rusb -> libusb-wasi.a -> WIT -> host |
| C5 | Rust | WASM component | OS -> raw WIT calls -> host |

### 6.1 Building libusb-wasi.a (required for C2 and C4)

Before running `just bench-build`, you need `libusb-wasi/libusb-wasi.a`. This is the WASI
static library built from `libusb-wasi/`. It is not built by CMake or Cargo - you have to
build it once from the submodule directory.

```bash
export WASI_SDK_PATH=/opt/wasi-sdk   # adjust if you installed somewhere else

cd libusb-wasi

# Generate the configure script (only needed once after a fresh clone)
./autogen.sh

# Configure for WASI - you MUST re-run this even if autogen.sh already ran configure,
# because autogen.sh configures for your native OS by default.
./configure \
  --host=wasm32-unknown-wasi \
  --disable-shared \
  --enable-static \
  CC="$WASI_SDK_PATH/bin/clang --sysroot=$WASI_SDK_PATH/share/wasi-sysroot --target=wasm32-wasip2" \
  AR="$WASI_SDK_PATH/bin/llvm-ar" \
  RANLIB="$WASI_SDK_PATH/bin/llvm-ranlib"

make -j$(nproc)

# Assemble libusb-wasi.a
cp libusb/.libs/libusb-1.0.a libusb-wasi.a

# The cguest bindings object needs to be in there too.
# It is built by the C2 cmake step (see 6.2 step 2 below), so do a partial
# bench-build first to get it, then come back and add it:
#   ar r libusb-wasi.a /path/to/benchmarks/usb-bench-c/bindings/guest_component_type.o
# In practice 'just bench-build' handles this ordering for you.

cd ..
```

> **Note for the Rust archive (C4)**: `libusb-wasi-rust.a` is a variant of `libusb-wasi.a`
> where `cguest.o` has the `__wasm_export_exports_wasi_cli_run_run` symbol set to
> `VISIBILITY_HIDDEN` only. This prevents the Rust component linker from clashing with
> the C-specific run-export handler. The patched archive is checked in at
> `libusb-wasi/libusb-wasi-rust.a` and is used automatically by `benchmarks/build-c4.sh`.

### 6.2 Build all conditions

```bash
just bench-build
```

This runs in order:
1. **libusb-vanilla** - builds `libusb-vanilla/.libs/libusb-1.0.a` from source (skipped if already present). The C1 CMake build uses system libusb when `pkg-config` finds it; otherwise it falls back to this vendored archive automatically. You don't need to install `libusb-1.0-0-dev` / `libusb-devel` for this to work.
2. **C1** - `cmake -B benchmarks/usb-bench-c/build-native benchmarks/usb-bench-c`
3. **C2** - cmake with the WASI toolchain file (produces `guest_component_type.o` as a side effect)
4. **C3 + C5** - `cargo build --release --bins` targeting the current host
5. **C4** - `bash benchmarks/build-c4.sh` (pkg-config redirected to WASI sysroot)
6. **C5** - `cargo build --release --bins --target wasm32-wasip2`

### 6.3 Running benchmarks

You need the USB devices connected before running:
- SanDisk USB drive (bulk workload) - must NOT be mounted; eject first: `diskutil eject /Volumes/<name>` on macOS or `umount /dev/sdX` on Linux
- Raspberry Pi Pico running the USB identity firmware (control + interrupt workloads)
- Logitech Brio (or similar UVC webcam) for the iso workload

```bash
just bench-run          # full run (requires USB devices + sudo)
just bench-smoke        # 1 iteration per cell, quick sanity check
just bench-dry          # print all commands without running anything
just bench-analyze      # analyse the most recent results/ directory
```

You can restrict to specific workloads:

```bash
just bench-smoke --workloads ctrl,iso
just bench-run --workloads bulk
```

> **macOS note on iso**: the iso workload will time out on macOS for C1 and C3 (native
> builds) because `IOUSBDeviceFamily` holds the UVC camera exclusively. You get
> `bytes=0` but no error. Real isochronous throughput measurements need Linux.

### 6.4 C4 build details

C4 cross-compiles the Rust benchmark to `wasm32-wasip2` by pointing `pkg-config` at a
custom sysroot (`sysroot-wasi/`) that contains a `.pc` file for `libusb-1.0` pointing to
`libusb-wasi/libusb-wasi-rust.a`. This way `libusb1-sys` (rusb's FFI crate) links against
the WASI build instead of the host's system libusb, without any changes to rusb itself.

The entry point is `benchmarks/build-c4.sh`. If you need to rebuild only C4:

```bash
bash benchmarks/build-c4.sh
```

---

## 7. Workload Compilation Architecture

### 7.1 Overview

```
Application code
  -> rusb / libusb API
  -> libusb-wasi.a  (guest-side WIT bindings, WASI backend in wasi_usb.c)
  -> WASI-USB WIT interface  (component boundary)
  -> host runtime  (usb-wasi-host)
  -> OS USB stack  (libusb 1.0 / IOUSBLib / usbfs)
```

The key design choice is that the host exposes only generic USB primitives (open, claim,
transfer). All protocol logic - UVC probe/commit, FAT32 parsing, HID report decoding -
lives in the guest. The host has zero protocol-specific code.

### 7.2 libusb-wasi: the guest library

`libusb-wasi` adds `wasi_usb.c` as a new backend for libusb. This backend implements
libusb's internal `usbi_os_backend` interface but instead of talking to the kernel it
calls functions exported by the WASI-USB WIT interface. The cguest bindings glue
`wasi_usb.c` to those interface functions:

| File | Content |
|------|---------|
| `cguest.o` | Generated C code calling the WASI-USB host functions |
| `cguest_component_type.o` | Metadata: `component-type:cguest` custom section with the full WIT world |

The build product is `libusb-wasi.a` - a static archive of all object files.

**Note:** only synchronous transfers are supported in `libusb-wasi`. Asynchronous libusb
transfers need a real threading model, which is not yet standardised for WASI/Wasmtime.

### 7.3 Reactor model

WASI programs export a run function instead of defining a `main`:

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

### 7.4 rusb -> WASM cross-compilation (C4)

`rusb` uses `libusb1-sys` as its FFI binding crate. At cross-compile time, `pkg-config`
is redirected to the WASI sysroot so `libusb1-sys` links against `libusb-wasi-rust.a`:

```bash
export PKG_CONFIG_LIBDIR=sysroot-wasi/usr/lib/pkgconfig
export PKG_CONFIG_SYSROOT_DIR=sysroot-wasi
export PKG_CONFIG_ALLOW_CROSS=1
cargo build --target wasm32-wasip2 --features c4-rusb-wasi
```

The `sysroot-wasi/usr/lib/pkgconfig/libusb-1.0.pc` file points to `libusb-wasi/libusb-wasi-rust.a`
and the correct headers. The component-type metadata (`guest_component_type.o`) is pulled in
via `benchmarks/usb-bench-rs/build.rs`.

### 7.5 Summary table

| Aspect | libusb-wasi | rusb -> WASM (C4) |
|--------|-------------|------------------|
| Author | Robbe Leroy | pkg-config cross-compile config |
| Code changes needed | None | None - only build config |
| Key mechanism | New `wasi_usb.c` WASI backend | `PKG_CONFIG_LIBDIR` redirect |
| Link target | `libusb-wasi.a` | `libusb-wasi-rust.a` via sysroot |
| Build product | `libusb-wasi.a` | `.wasm` component |
| Compile target | `wasm32-wasip2` (WASI SDK) | `wasm32-wasip2` (Cargo + pkg-config) |

---

## 8. Troubleshooting

- **`LIBUSB_ERROR_ACCESS`**: USB access requires root. Run with `sudo`.
- **`libusb-wasi.a not found`**: Build it from `libusb-wasi/` as described in §6.1.
- **`guest_component_type.o not found`**: Run the C2 cmake step first (`cmake --build benchmarks/usb-bench-c/build-wasi`).
- **`error: could not find Cargo.toml`**: Make sure you are running cargo from the right crate root.
- **`SCSI Command Failed`**: The USB drive is still mounted. Eject it before running the mass-storage or bulk benchmarks.
- **`Invalid data length for control transfer OUT`**: This was a bug in `libusb-wasi/libusb/os/wasi_usb.c` (line 973, `if (true)` stub). Fixed in submodule commit `e38f249`.
- **Cargo doesn't rebuild after `.a` file changes**: Cargo doesn't watch external static libraries. Force a rebuild: `touch benchmarks/usb-bench-rs/build.rs`.
- **`autogen.sh` configured for the wrong target**: `autogen.sh` runs configure for the native host at the end. Always re-run `./configure` with the WASI env vars afterwards (see §6.1).
