# wasi-usb Justfile
# Usage: just <recipe>
# Requires: just, cargo, cargo-component, wasm32-wasip2 toolchain, wasm-tools

HOST := "./usb-wasi-host/target/release/usb-wasi-host"
GUEST_TARGET := "wasm32-wasip2"
GUEST_OUT := "usb-wasi-guest/target/wasm32-wasip2/release/examples"

# ── Host ────────────────────────────────────────────────────────────────────

build-host:
    cd usb-wasi-host && cargo build --release

# ── Webcam (sub-crate with WASI filesystem + UVC) ───────────────────────────

build-webcam:
    mkdir -p out
    cargo build --target {{GUEST_TARGET}} --release -p webcam \
        --manifest-path usb-wasi-guest/examples/webcam/Cargo.toml
    cp usb-wasi-guest/examples/webcam/target/wasm32-wasip2/release/webcam.wasm out/webcam.wasm

webcam: build-host build-webcam
    mkdir -p out
    sudo {{HOST}} -c out/webcam.wasm -d "046d:094c" -u

# ── Generic example builder ─────────────────────────────────────────────────

build-example name:
    mkdir -p out
    cargo build --example {{name}} --target {{GUEST_TARGET}} --release \
        --manifest-path usb-wasi-guest/Cargo.toml
    cp {{GUEST_OUT}}/{{name}}.wasm out/{{name}}.wasm

# ── Per-example run recipes ─────────────────────────────────────────────────

lsusb: build-host (build-example "lsusb")
    sudo {{HOST}} -c out/lsusb.wasm

enumerate-devices-rust: build-host (build-example "enumerate-devices-rust")
    sudo {{HOST}} -c out/enumerate-devices-rust.wasm

control: build-host (build-example "control")
    sudo {{HOST}} -c out/control.wasm

identity: build-host (build-example "identity")
    sudo {{HOST}} -c out/identity.wasm

xbox: build-host (build-example "xbox")
    sudo {{HOST}} -c out/xbox.wasm

ping *args: build-host (build-example "ping")
    sudo {{HOST}} -c out/ping.wasm -- {{args}}

streams-test *args: build-host (build-example "streams-test")
    sudo {{HOST}} -c out/streams-test.wasm -- {{args}}

# ── Sub-crate guests ─────────────────────────────────────────────────────────

build-mass-storage:
    mkdir -p out
    cargo build --target {{GUEST_TARGET}} --release -p mass-storage \
        --manifest-path usb-wasi-guest/examples/mass-storage/Cargo.toml
    cp usb-wasi-guest/examples/mass-storage/target/wasm32-wasip2/release/mass-storage.wasm out/mass-storage.wasm

mass-storage *args: build-host build-mass-storage
    sudo {{HOST}} -c out/mass-storage.wasm -- {{args}}

build-ps5-maze:
    mkdir -p out
    cargo build --target {{GUEST_TARGET}} --release -p ps5-maze \
        --manifest-path usb-wasi-guest/examples/ps5-maze/Cargo.toml
    cp usb-wasi-guest/examples/ps5-maze/target/wasm32-wasip2/release/ps5_maze.wasm out/ps5-maze.wasm

ps5-maze: build-host build-ps5-maze
    sudo {{HOST}} -c out/ps5-maze.wasm

build-xbox-maze:
    mkdir -p out
    cargo build --target {{GUEST_TARGET}} --release -p xbox-maze \
        --manifest-path usb-wasi-guest/examples/xbox-maze/Cargo.toml
    cp usb-wasi-guest/examples/xbox-maze/target/wasm32-wasip2/release/xbox_maze.wasm out/xbox-maze.wasm

xbox-maze: build-host build-xbox-maze
    sudo {{HOST}} -c out/xbox-maze.wasm

# ── Go guest (requires tinygo + wit-bindgen-go) ──────────────────────────────

build-enumerate-devices-go:
    cd usb-wasi-guest/examples/enumerate-devices-go && ./build.sh

enumerate-devices-go: build-host build-enumerate-devices-go
    sudo {{HOST}} -c usb-wasi-guest/examples/enumerate-devices-go/out/main.component.wasm

# ── Benchmark suite (thesis evaluation) ─────────────────────────────────────

# Build vendored libusb-vanilla (native host) — used as C1 fallback when system libusb-1.0 is absent.
# Skipped automatically when .libs/libusb-1.0.a already exists.
build-libusb-vanilla:
    #!/usr/bin/env bash
    set -euo pipefail
    # Use an absolute path so the skip-check and the final verify both agree on location.
    TARGET="$(pwd)/libusb-vanilla/libusb/.libs/libusb-1.0.a"
    if [ -f "$TARGET" ]; then
        echo "libusb-vanilla already built, skipping."
        exit 0
    fi
    echo "Building libusb-vanilla (native)..."
    cd libusb-vanilla
    # autogen.sh ends with 'exec ./configure ...' which would run configure with wrong flags.
    # Use autoreconf -fi instead: it only regenerates the build-system files (aclocal, automake,
    # autoconf) without running configure itself, so our explicit configure call below is the
    # only one that runs.
    autoreconf -fi
    ./configure --disable-shared --enable-static --disable-examples-build --disable-tests-build \
        --without-libudev
    # Remove stale object files from previous (partial) builds so make compiles everything fresh.
    make clean || true
    make -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
    if [ ! -f "$TARGET" ]; then
        echo "ERROR: build finished but $TARGET was not created" >&2
        exit 1
    fi
    echo "Done: $TARGET"

# Build all benchmark binaries (C1+C2 via CMake, C3+C5 via Cargo)
bench-build: build-libusb-vanilla
    # C1 — native libusb (C)
    cmake -B benchmarks/usb-bench-c/build-native benchmarks/usb-bench-c
    cmake --build benchmarks/usb-bench-c/build-native
    # C2 — wasi-libusb (C WASM)
    cmake -B benchmarks/usb-bench-c/build-wasi benchmarks/usb-bench-c \
        -DCMAKE_TOOLCHAIN_FILE={{justfile_directory()}}/benchmarks/usb-bench-c/toolchain-wasi.cmake
    cmake --build benchmarks/usb-bench-c/build-wasi
    # C3 — native rusb (Rust)
    cargo build --release --bins --manifest-path benchmarks/usb-bench-rs/Cargo.toml
    # C4 — wasi-rusb (Rust + rusb → libusb-wasi.a → WIT)
    bash benchmarks/build-c4.sh
    # C5 — wasi-raw-wit (Rust WASM)
    cargo build --release --bins --target wasm32-wasip2 \
        --manifest-path benchmarks/usb-bench-rs/Cargo.toml

# Run full benchmark suite (requires USB devices connected, run as root)
bench-run *ARGS:
    sudo bash benchmarks/run.sh {{ARGS}}

# Quick smoke run — 1 iteration per cell, no real devices needed for dry-run
bench-smoke *ARGS:
    sudo bash benchmarks/run.sh --smoke {{ARGS}}

# Dry-run: print all commands without executing
bench-dry:
    bash benchmarks/run.sh --dry-run --smoke

# Run analysis on the most recent results directory
bench-analyze:
    python3 benchmarks/analyze.py results/$(ls -t results/ | head -1)

# ── Build all guests ─────────────────────────────────────────────────────────

build-all: build-host build-webcam \
    (build-example "lsusb") \
    (build-example "enumerate-devices-rust") \
    (build-example "control") \
    (build-example "identity") \
    (build-example "xbox") \
    (build-example "ping") \
    (build-example "streams-test") \
    build-mass-storage build-ps5-maze build-xbox-maze

# ── Overige tools (uit super-repo) ───────────────────────────────────────────

nokhwa-test:
    cd ../nokhwa-test && cargo run

webcam-cv:
    cd ../usb-wasm && just webcam-cv
