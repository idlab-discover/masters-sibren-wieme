#!/bin/bash
# run_benchmarks.sh — Voer alle benchmarks uit en sla resultaten op in benchmarks/results/
#
# Gebruik (vanuit projectroot):
#   sudo ./benchmarks/run_benchmarks.sh [--latency | --throughput | --all]
#
# Standaard: --all

set -e

# ── Paden ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"   # absoluut pad naar benchmarks/
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"  # absoluut pad naar projectroot
WASI_HOST_DIR="$PROJECT_ROOT/wasi-usb/usb-wasi-host"
RESULTS_DIR="$SCRIPT_DIR/results"

mkdir -p "$RESULTS_DIR"

# ── Latency device parameters (Loopback) ───────────────────────────────────────
LATENCY_VID="cafe"
LATENCY_PID="4002"
LATENCY_INTERFACE="0"
LATENCY_EP_OUT="01"
LATENCY_EP_IN="81"

# ── Throughput device parameters (Mass Storage) ────────────────────────────────
THROUGHPUT_VID="0781"
THROUGHPUT_PID="5581"
THROUGHPUT_INTERFACE="0"
THROUGHPUT_EP_OUT="02"
THROUGHPUT_EP_IN="81"

# ── Latency parameters ─────────────────────────────────────────────────────────
# Alleen veelvouden van 64 (USB 2.0 bulk max-packet-size)
LATENCY_SIZES=(64 128 192 256 512 1024)
LATENCY_ITERATIONS=10000

# ── Throughput parameters ──────────────────────────────────────────────────────
THROUGHPUT_START_LBA=2048
THROUGHPUT_SIZE_MB=(2 4 8 16 32 64)
THROUGHPUT_RUNS=10

# ── Helpers ────────────────────────────────────────────────────────────────────
run_latency_native() {
    local exe="$1"
    local variant="$2"
    echo "=== Latency native: $variant ==="
    for size in "${LATENCY_SIZES[@]}"; do
        echo "  -> $size bytes"
        # Verander naar benchmarks/ zodat results/ op de juiste plek aangemaakt wordt
        (cd "$SCRIPT_DIR" && sudo "$exe" "$LATENCY_VID" "$LATENCY_PID" "$LATENCY_INTERFACE" "$LATENCY_EP_OUT" "$LATENCY_EP_IN" \
            "$size" "$LATENCY_ITERATIONS" "$variant")
    done
}

run_latency_wasi() {
    local wasm="$1"       # absoluut pad naar de .component.wasm
    local variant="$2"
    echo "=== Latency WASI: $variant ==="
    for size in "${LATENCY_SIZES[@]}"; do
        echo "  -> $size bytes"
        # CWD = benchmarks/ zodat results/ op de juiste plek aangemaakt wordt.
        (cd "$SCRIPT_DIR" && sudo cargo run --release --manifest-path "$WASI_HOST_DIR/Cargo.toml" -- \
            --debug_level off --component-path "$wasm" \
            "$LATENCY_VID" "$LATENCY_PID" "$LATENCY_INTERFACE" "$LATENCY_EP_OUT" "$LATENCY_EP_IN" \
            "$size" "$LATENCY_ITERATIONS" "$variant")
    done
}


run_throughput_native() {
    local exe="$1"
    local variant="$2"
    echo "=== Throughput native: $variant ==="
    for size in "${THROUGHPUT_SIZE_MB[@]}"; do
        echo "  -> $size MB"
        (cd "$SCRIPT_DIR" && sudo "$exe" "$THROUGHPUT_VID" "$THROUGHPUT_PID" "$THROUGHPUT_INTERFACE" "$THROUGHPUT_EP_OUT" "$THROUGHPUT_EP_IN" \
            "$THROUGHPUT_START_LBA" "$size" "$THROUGHPUT_RUNS" "$variant")
    done
}

run_throughput_wasi() {
    local wasm="$1"
    local variant="$2"
    echo "=== Throughput WASI: $variant ==="
    for size in "${THROUGHPUT_SIZE_MB[@]}"; do
        echo "  -> $size MB"
        # CWD = benchmarks/ zodat results/ op de juiste plek aangemaakt wordt.
        (cd "$SCRIPT_DIR" && sudo cargo run --release --manifest-path "$WASI_HOST_DIR/Cargo.toml" -- \
            --debug_level off --component-path "$wasm" \
            "$THROUGHPUT_VID" "$THROUGHPUT_PID" "$THROUGHPUT_INTERFACE" "$THROUGHPUT_EP_OUT" "$THROUGHPUT_EP_IN" \
            "$THROUGHPUT_START_LBA" "$size" "$THROUGHPUT_RUNS" "$variant")
    done
}

run_yolo_benchmark() {
    local wasm="$PROJECT_ROOT/usb-wasm/command-components/yolo-detector/target/wasm32-wasip2/release/yolo_detector.component.wasm"
    local model_path="${YOLO_MODEL_PATH:-$PROJECT_ROOT/yolov8n.onnx}"
    
    echo "=== YOLO Benchmark ==="
    mkdir -p "$RESULTS_DIR"
    
    if [ ! -f "$wasm" ]; then
        echo "Error: YOLO component not found at $wasm. Run 'cargo component build --release' in the component directory."
        return 1
    fi

    local log_file="$RESULTS_DIR/yolo_host.log"
    echo "Running host with YOLO component... (Model: $model_path)"
    
    # Run host in background
    sudo cargo run --release --manifest-path "$WASI_HOST_DIR/Cargo.toml" -- \
        --component-path "$wasm" --enable-yolo -- "$model_path" > "$log_file" 2>&1 &
    HOST_PID=$!
    
    # Start resource tracker
    "$SCRIPT_DIR/yolo_resource_tracker.sh" "$HOST_PID" "$RESULTS_DIR/yolo_resources.csv" &
    TRACKER_PID=$!
    
    echo "Host PID: $HOST_PID, Tracker PID: $TRACKER_PID"
    echo "Benchmark running... (will stop when host exits or after timeout)"
    
    # Give it some time to run if it doesn't exit automatically (it's a stream)
    # For a benchmark, we might want to run for N seconds then kill it
    sleep 30
    sudo kill $HOST_PID 2>/dev/null || true
    wait $HOST_PID 2>/dev/null || true
    kill $TRACKER_PID 2>/dev/null || true
    
    # Extract latency
    grep "Inference took:" "$log_file" | sed 's/.*Inference took: //; s/ms//' > "$RESULTS_DIR/yolo_latency.csv"
    echo "YOLO results saved to $RESULTS_DIR/yolo_latency.csv and yolo_resources.csv"
}


# ── Mode ───────────────────────────────────────────────────────────────────────
MODE="${1:---all}"

# ── YOLO benchmark ─────────────────────────────────────────────────────────────
if [[ "$MODE" == "--yolo" || "$MODE" == "--all" ]]; then
    run_yolo_benchmark
fi

# ── Latency benchmarks ─────────────────────────────────────────────────────────
if [[ "$MODE" == "--latency" || "$MODE" == "--all" ]]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo " LATENCY BENCHMARKS  (loopback device)"
    echo "══════════════════════════════════════════"

    run_latency_native "$SCRIPT_DIR/c/latency_vanilla_native" "libusb_native"
    run_latency_native "$SCRIPT_DIR/rust/latency_native"      "rusb_native"

    run_latency_wasi "$SCRIPT_DIR/c/latency_leroy.component.wasm"    "libusb_wasi"
    run_latency_wasi "$SCRIPT_DIR/rust/latency_rusb.component.wasm"  "rusb_wasi"
fi

# ── Throughput benchmarks ──────────────────────────────────────────────────────
if [[ "$MODE" == "--throughput" || "$MODE" == "--all" ]]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo " THROUGHPUT BENCHMARKS  (mass storage)"
    echo "══════════════════════════════════════════"

    run_throughput_native "$SCRIPT_DIR/c/throughput_vanilla_native"      "libusb_native"
    run_throughput_native "$SCRIPT_DIR/rust/throughput_native"           "rusb_native"

    run_throughput_wasi "$SCRIPT_DIR/c/throughput_leroy.component.wasm"   "libusb_wasi"
    run_throughput_wasi "$SCRIPT_DIR/rust/throughput_rusb.component.wasm" "rusb_wasi"
fi

echo ""
echo "Resultaten staan in: $RESULTS_DIR"
