#!/bin/bash
set -e

# Configuration
PROJECT_ROOT=$(pwd)
BENCH_DIR="$PROJECT_ROOT/benchmarks"
WASI_SDK_PATH="/opt/wasi-sdk"
WASM_TOOLS="wasm-tools"
WIT_PATH="$PROJECT_ROOT/wasi-usb/wit"
RUSB_SYSROOT="$PROJECT_ROOT/rusb-wasi/examples/wasi-workload/wasi-sysroot"

# Ensure directories exist
mkdir -p "$BENCH_DIR/c/utils"
mkdir -p "$BENCH_DIR/rust/utils"

echo "=== Building Latency Benchmarks ==="

# Permutation 1: Native Vanilla C
echo "Building Native Vanilla C Latency..."
gcc -I"$PROJECT_ROOT/libusb-vanilla/libusb" \
    "$BENCH_DIR/c/usb_latency.c" \
    "$PROJECT_ROOT/libusb-vanilla/libusb/.libs/libusb-1.0.a" \
    -o "$BENCH_DIR/c/latency_vanilla_native" \
    -framework CoreFoundation -framework IOKit -framework Security

echo "Building Native Vanilla C usb_io, lsusb, and read_device..."
gcc -I"$PROJECT_ROOT/libusb-vanilla/libusb" \
    "$BENCH_DIR/c/usb_io.c" \
    "$PROJECT_ROOT/libusb-vanilla/libusb/.libs/libusb-1.0.a" \
    -o "$BENCH_DIR/c/utils/usb_io_vanilla_native" \
    -framework CoreFoundation -framework IOKit -framework Security

gcc -I"$PROJECT_ROOT/libusb-vanilla/libusb" \
    "$PROJECT_ROOT/libusb-wasi/examples/lsusb.c" \
    "$PROJECT_ROOT/libusb-vanilla/libusb/.libs/libusb-1.0.a" \
    -o "$BENCH_DIR/c/utils/lsusb_vanilla_native" \
    -framework CoreFoundation -framework IOKit -framework Security

gcc -I"$PROJECT_ROOT/libusb-vanilla/libusb" \
    "$PROJECT_ROOT/libusb-wasi/examples/read_device.c" \
    "$PROJECT_ROOT/libusb-vanilla/libusb/.libs/libusb-1.0.a" \
    -o "$BENCH_DIR/c/utils/read_device_vanilla_native" \
    -framework CoreFoundation -framework IOKit -framework Security

# Permutation 2: WASI Leroy C
echo "Building WASI Leroy C Latency..."
cd "$BENCH_DIR/c"
"$WASI_SDK_PATH/bin/clang" --target=wasm32-wasip2 --sysroot="$WASI_SDK_PATH/share/wasi-sysroot" \
    -I"$RUSB_SYSROOT/usr/include/libusb-1.0" \
    -c -o "usb_latency.o" "usb_latency.c"

    "$WASI_SDK_PATH/bin/wasm-ld" -m wasm32 \
        -L"$RUSB_SYSROOT/usr/lib" \
        -L"$WASI_SDK_PATH/share/wasi-sysroot/lib/wasm32-wasip2" \
        "$WASI_SDK_PATH/share/wasi-sysroot/lib/wasm32-wasip2/crt1-command.o" \
        -lusb-1.0 "usb_latency.o" -lc \
        "$WASI_SDK_PATH/lib/clang/21/lib/wasm32-unknown-wasip2/libclang_rt.builtins.a" \
        -o "latency_leroy.wasm"

"$WASM_TOOLS" component embed "$WIT_PATH" "latency_leroy.wasm" -o "latency_leroy.embedded.wasm" --world cguest
"$WASM_TOOLS" component new "latency_leroy.embedded.wasm" -o "latency_leroy.component.wasm"
rm "usb_latency.o" "latency_leroy.wasm" "latency_leroy.embedded.wasm"

echo "Building WASI Leroy C lsusb, read_device, and usb_io..."
cp "$BENCH_DIR/c/usb_io.c" "$PROJECT_ROOT/libusb-wasi/examples/"
cd "$PROJECT_ROOT/libusb-wasi/examples"
# Update build_component call if necessary, or just run it here
build_component() {
    local src_file=$1
    local name=$(basename "$src_file" .c)
    "$WASI_SDK_PATH/bin/clang" --target=wasm32-wasip2 --sysroot="$WASI_SDK_PATH/share/wasi-sysroot" \
        -I"$RUSB_SYSROOT/usr/include/libusb-1.0" \
        -c -o "$name.o" "$src_file"
    "$WASI_SDK_PATH/bin/wasm-ld" -m wasm32 \
        -L"$RUSB_SYSROOT/usr/lib" \
        -L"$WASI_SDK_PATH/share/wasi-sysroot/lib/wasm32-wasip2" \
        "$WASI_SDK_PATH/share/wasi-sysroot/lib/wasm32-wasip2/crt1-command.o" \
        -lusb-1.0 "$name.o" -lc \
        "$WASI_SDK_PATH/lib/clang/21/lib/wasm32-unknown-wasip2/libclang_rt.builtins.a" \
        -o "$name.wasm"
    "$WASM_TOOLS" component embed "$WIT_PATH" "$name.wasm" -o "$name.embedded.wasm" --world cguest
    "$WASM_TOOLS" component new "$name.embedded.wasm" -o "$name.component.wasm"
    rm "$name.o" "$name.wasm" "$name.embedded.wasm"
}

build_component "lsusb.c"
build_component "read_device.c"
build_component "usb_io.c"

cp lsusb.component.wasm "$BENCH_DIR/c/utils/"
cp read_device.component.wasm "$BENCH_DIR/c/utils/"
cp usb_io.component.wasm "$BENCH_DIR/c/utils/"
rm usb_io.c

cd "$PROJECT_ROOT"

# Permutation 3: Native rusb
echo "Building Native rusb Latency..."
cd "$BENCH_DIR/rust/latency"
cargo build --release
cp target/release/latency "$BENCH_DIR/rust/latency_native"

echo "Building Native rusb Workloads (lsusb, read_device, usb_io)..."
cd "$PROJECT_ROOT/rusb-wasi/examples/wasi-workload"
cargo build --release
cp target/release/rusb_workload "$BENCH_DIR/rust/utils/rusb_workload_native"

cargo build --release --example lsusb
cp target/release/examples/lsusb "$BENCH_DIR/rust/utils/lsusb_native"

cargo build --release --example usb_io
cp target/release/examples/usb_io "$BENCH_DIR/rust/utils/usb_io_native"

cd "$PROJECT_ROOT"

# Permutation 4: WASI rusb
echo "Building WASI rusb Latency..."
cd "$BENCH_DIR/rust/latency"
PKG_CONFIG_PATH="$RUSB_SYSROOT/usr/lib/pkgconfig" \
PKG_CONFIG_LIBDIR="$RUSB_SYSROOT/usr/lib" \
PKG_CONFIG_SYSROOT_DIR="$RUSB_SYSROOT" \
PKG_CONFIG_ALLOW_CROSS=1 \
LIBUSB_1_0_NO_PKG_CONFIG=0 \
cargo build --release --target wasm32-wasip2

cp target/wasm32-wasip2/release/latency.wasm "$BENCH_DIR/rust/latency_rusb.component.wasm"

echo "Building WASI rusb Workloads (lsusb, read_file, usb_io)..."
cd "$PROJECT_ROOT/rusb-wasi/examples/wasi-workload"
PKG_CONFIG_PATH="$RUSB_SYSROOT/usr/lib/pkgconfig" \
PKG_CONFIG_LIBDIR="$RUSB_SYSROOT/usr/lib" \
PKG_CONFIG_SYSROOT_DIR="$RUSB_SYSROOT" \
PKG_CONFIG_ALLOW_CROSS=1 \
LIBUSB_1_0_NO_PKG_CONFIG=0 \
cargo build --release --target wasm32-wasip2 --example lsusb

PKG_CONFIG_PATH="$RUSB_SYSROOT/usr/lib/pkgconfig" \
PKG_CONFIG_LIBDIR="$RUSB_SYSROOT/usr/lib" \
PKG_CONFIG_SYSROOT_DIR="$RUSB_SYSROOT" \
PKG_CONFIG_ALLOW_CROSS=1 \
LIBUSB_1_0_NO_PKG_CONFIG=0 \
cargo build --release --target wasm32-wasip2 --example usb_io

# rusb_workload is the main bin
cp target/wasm32-wasip2/release/rusb_workload.wasm "$BENCH_DIR/rust/utils/rusb_workload.component.wasm"
cp target/wasm32-wasip2/release/examples/lsusb.wasm "$BENCH_DIR/rust/utils/lsusb_rusb.component.wasm"
cp target/wasm32-wasip2/release/examples/usb_io.wasm "$BENCH_DIR/rust/utils/usb_io_rusb.component.wasm"

cd "$PROJECT_ROOT"

echo "=== Building Init Benchmark ==="

# Native C
echo "Building Native Vanilla C usb_init..."
gcc -I"$PROJECT_ROOT/libusb-vanilla/libusb" \
    "$BENCH_DIR/c/usb_init.c" \
    "$PROJECT_ROOT/libusb-vanilla/libusb/.libs/libusb-1.0.a" \
    -o "$BENCH_DIR/c/usb_init_native" \
    -framework CoreFoundation -framework IOKit -framework Security

# WASI Leroy C
echo "Building WASI Leroy C usb_init..."
cd "$BENCH_DIR/c"
"$WASI_SDK_PATH/bin/clang" --target=wasm32-wasip2 --sysroot="$WASI_SDK_PATH/share/wasi-sysroot" \
    -I"$RUSB_SYSROOT/usr/include/libusb-1.0" \
    -c -o "usb_init.o" "usb_init.c"
"$WASI_SDK_PATH/bin/wasm-ld" -m wasm32 \
    -L"$RUSB_SYSROOT/usr/lib" \
    -L"$WASI_SDK_PATH/share/wasi-sysroot/lib/wasm32-wasip2" \
    "$WASI_SDK_PATH/share/wasi-sysroot/lib/wasm32-wasip2/crt1-command.o" \
    -lusb-1.0 "usb_init.o" -lc \
    "$WASI_SDK_PATH/lib/clang/21/lib/wasm32-unknown-wasip2/libclang_rt.builtins.a" \
    -o "usb_init.wasm"
"$WASM_TOOLS" component embed "$WIT_PATH" "usb_init.wasm" -o "usb_init.embedded.wasm" --world cguest
"$WASM_TOOLS" component new "usb_init.embedded.wasm" -o "usb_init.component.wasm"
rm "usb_init.o" "usb_init.wasm" "usb_init.embedded.wasm"
cd "$PROJECT_ROOT"

echo "=== Building Streams-Test Component (USB 3.0 bulk streams validatie) ==="
cd "$PROJECT_ROOT/usb-wasm/command-components/streams-test"
cargo build --release --target wasm32-wasip2
cd "$PROJECT_ROOT"

echo "=== Building Throughput Benchmarks ==="

# Permutation 1: Native Vanilla C
echo "Building Native Vanilla C Throughput..."
gcc -I"$PROJECT_ROOT/libusb-vanilla/libusb" \
    "$BENCH_DIR/c/usb_throughput.c" \
    "$PROJECT_ROOT/libusb-vanilla/libusb/.libs/libusb-1.0.a" \
    -o "$BENCH_DIR/c/throughput_vanilla_native" \
    -framework CoreFoundation -framework IOKit -framework Security

# Permutation 2: Native Leroy C
echo "Building Native Leroy C Throughput..."
gcc -I"$PROJECT_ROOT/libusb-wasi/libusb" \
    "$BENCH_DIR/c/usb_throughput.c" \
    "$PROJECT_ROOT/libusb-wasi/libusb/.libs/libusb-1.0.a" \
    -o "$BENCH_DIR/c/throughput_leroy_native" \
    -framework CoreFoundation -framework IOKit -framework Security

# Permutation 3: WASI Leroy C
echo "Building WASI Leroy C Throughput..."
cd "$BENCH_DIR/c"
"$WASI_SDK_PATH/bin/clang" --target=wasm32-wasip2 --sysroot="$WASI_SDK_PATH/share/wasi-sysroot" \
    -I"$RUSB_SYSROOT/usr/include/libusb-1.0" \
    -c -o "usb_throughput.o" "usb_throughput.c"

    "$WASI_SDK_PATH/bin/wasm-ld" -m wasm32 \
        -L"$RUSB_SYSROOT/usr/lib" \
        -L"$WASI_SDK_PATH/share/wasi-sysroot/lib/wasm32-wasip2" \
        "$WASI_SDK_PATH/share/wasi-sysroot/lib/wasm32-wasip2/crt1-command.o" \
        -lusb-1.0 "usb_throughput.o" -lc \
        "$WASI_SDK_PATH/lib/clang/21/lib/wasm32-unknown-wasip2/libclang_rt.builtins.a" \
        -o "throughput_leroy.wasm"

"$WASM_TOOLS" component embed "$WIT_PATH" "throughput_leroy.wasm" -o "throughput_leroy.embedded.wasm" --world cguest
"$WASM_TOOLS" component new "throughput_leroy.embedded.wasm" -o "throughput_leroy.component.wasm"
rm "usb_throughput.o" "throughput_leroy.wasm" "throughput_leroy.embedded.wasm"
cd "$PROJECT_ROOT"

# Permutation 4: Native rusb
echo "Building Native rusb Throughput..."
cd "$BENCH_DIR/rust/throughput"
cargo build --release
cp target/release/throughput "$BENCH_DIR/rust/throughput_native"
cd "$PROJECT_ROOT"

# Permutation 5: WASI rusb
echo "Building WASI rusb Throughput..."
cd "$BENCH_DIR/rust/throughput"
PKG_CONFIG_PATH="$RUSB_SYSROOT/usr/lib/pkgconfig" \
PKG_CONFIG_LIBDIR="$RUSB_SYSROOT/usr/lib" \
PKG_CONFIG_SYSROOT_DIR="$RUSB_SYSROOT" \
PKG_CONFIG_ALLOW_CROSS=1 \
LIBUSB_1_0_NO_PKG_CONFIG=0 \
cargo build --release --target wasm32-wasip2

cp target/wasm32-wasip2/release/throughput.wasm "$BENCH_DIR/rust/throughput_rusb.component.wasm"
cd "$PROJECT_ROOT"

echo "=== All Benchmarking Permutations Built ==="
ls -l "$BENCH_DIR"/{c,rust}/*.component.wasm "$BENCH_DIR"/{c,rust}/*native
