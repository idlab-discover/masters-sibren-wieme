#!/bin/bash
# run_benchmarks.sh — Voert alle benchmarks uit en slaat resultaten op in benchmarks/results/
#
# Gebruik (vanuit projectroot):
#   sudo ./benchmarks/run_benchmarks.sh [--latency | --throughput | --init | --streams | --all]
#
# Standaard: --all
#
# Benchmarks:
#   --latency     Ping-pong RTT via Pico 2 loopback (USB 2.0 Full Speed).
#   --throughput  MSC read/write via SanDisk USB 3.0 stick (SuperSpeed).
#   --init        Tijd voor libusb_init + enumerate + open + claim (cold start).
#   --streams     USB 3.0 Bulk Streams validatie (alloc_streams + stream-bulk xfer).
#
# Resultaten: benchmarks/results/*.csv

set -e

# ── Paden ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WASI_HOST_DIR="$PROJECT_ROOT/wasi-usb/usb-wasi-host"
RESULTS_DIR="$SCRIPT_DIR/results"

mkdir -p "$RESULTS_DIR"

# ══════════════════════════════════════════════════════════════════════════════
# ── DEVICE-CONFIGURATIE  ─────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# Latency device — Pico 2 loopback CDC.
# Pico 2 (RP2350) exposeert Full-Speed USB (12 Mbps, bulk MPS = 64 B).
LATENCY_LABEL="usb2fs_pico"
LATENCY_VID="cafe"
LATENCY_PID="4002"
LATENCY_INTERFACE="0"
LATENCY_EP_OUT="01"
LATENCY_EP_IN="81"

# Throughput device — SanDisk Ultra USB 3.0.
# SuperSpeed bulk MPS = 1024 B, theoretisch plafond ~400 MB/s.
THROUGHPUT_LABEL="usb3ss_sandisk"
THROUGHPUT_VID="0781"
THROUGHPUT_PID="5581"
THROUGHPUT_INTERFACE="0"
THROUGHPUT_EP_OUT="02"
THROUGHPUT_EP_IN="81"

# ══════════════════════════════════════════════════════════════════════════════
# ── BENCHMARK-PARAMETERS  ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# Latency — veelvouden van 64 (USB 2.0 FS bulk MPS).
LATENCY_SIZES=(64 128 256 512 1024)
LATENCY_ITERATIONS=10000

# Throughput — schaalt omhoog tot dicht bij USB 3.0 SS plafond (~400 MB/s).
# Kleinste groottes belichten CBW/CSW-overhead, grootste het bus-plafond.
THROUGHPUT_START_LBA=2048
THROUGHPUT_SIZE_MB=(8 32 128 256 512)
THROUGHPUT_RUNS=10

# Init-benchmark — meet cold-start overhead.
# Ruim genoeg iteraties voor een stabiele mediaan zonder te lang te duren.
INIT_ITERATIONS=200

# Streams-test — USB 3.0 SanDisk stick.
STREAMS_NUM=16
STREAMS_PAYLOAD=1024  # 1 × SuperSpeed bulk MPS

# ══════════════════════════════════════════════════════════════════════════════
# ── RESOURCE-TRACKING (CPU + RSS tijdens run)  ───────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
#
# Start een achtergrond-poller die elke 200 ms %CPU + RSS vastlegt voor PID $1
# naar CSV $2. Stopt wanneer het proces verdwijnt.
start_resource_tracker() {
    local pid="$1"
    local csv="$2"
    echo "timestamp_ms,cpu_pct,rss_kb" > "$csv"
    (
        local t0=$(date +%s%3N 2>/dev/null || python3 -c 'import time;print(int(time.time()*1000))')
        while kill -0 "$pid" 2>/dev/null; do
            local line
            line=$(ps -o %cpu=,rss= -p "$pid" 2>/dev/null | awk '{printf "%s,%s", $1, $2}')
            if [ -n "$line" ]; then
                local t=$(date +%s%3N 2>/dev/null || python3 -c 'import time;print(int(time.time()*1000))')
                echo "$((t - t0)),$line" >> "$csv"
            fi
            sleep 0.2
        done
    ) &
    echo $!
}

# Wrap een bench-commando in resource-tracking.
# Args: $1=csv_pad voor resource, overige=commando
run_with_tracking() {
    local rescsv="$1"; shift
    ( "$@" ) &
    local pid=$!
    local tpid
    tpid=$(start_resource_tracker "$pid" "$rescsv")
    wait "$pid" 2>/dev/null || true
    kill "$tpid" 2>/dev/null || true
}

# ══════════════════════════════════════════════════════════════════════════════
# ── HELPERS: LATENCY  ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

run_latency_native() {
    local exe="$1"
    local variant="$2"
    echo "=== Latency native: $variant (${LATENCY_LABEL}) ==="
    for size in "${LATENCY_SIZES[@]}"; do
        echo "  -> $size bytes"
        local rescsv="$RESULTS_DIR/resources_latency_${variant}_${LATENCY_LABEL}_${size}.csv"
        (cd "$SCRIPT_DIR" && run_with_tracking "$rescsv" \
            sudo "$exe" "$LATENCY_VID" "$LATENCY_PID" "$LATENCY_INTERFACE" \
            "$LATENCY_EP_OUT" "$LATENCY_EP_IN" \
            "$size" "$LATENCY_ITERATIONS" "$variant")
    done
}

run_latency_wasi() {
    local wasm="$1"
    local variant="$2"
    echo "=== Latency WASI: $variant (${LATENCY_LABEL}) ==="
    for size in "${LATENCY_SIZES[@]}"; do
        echo "  -> $size bytes"
        local rescsv="$RESULTS_DIR/resources_latency_${variant}_${LATENCY_LABEL}_${size}.csv"
        (cd "$SCRIPT_DIR" && run_with_tracking "$rescsv" \
            sudo cargo run --release --manifest-path "$WASI_HOST_DIR/Cargo.toml" -- \
            --debug_level off --component-path "$wasm" \
            "$LATENCY_VID" "$LATENCY_PID" "$LATENCY_INTERFACE" \
            "$LATENCY_EP_OUT" "$LATENCY_EP_IN" \
            "$size" "$LATENCY_ITERATIONS" "$variant")
    done
}

# ══════════════════════════════════════════════════════════════════════════════
# ── HELPERS: THROUGHPUT  ─────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

run_throughput_native() {
    local exe="$1"
    local variant="$2"
    echo "=== Throughput native: $variant (${THROUGHPUT_LABEL}) ==="
    for size in "${THROUGHPUT_SIZE_MB[@]}"; do
        echo "  -> $size MB"
        local rescsv="$RESULTS_DIR/resources_throughput_${variant}_${THROUGHPUT_LABEL}_${size}MB.csv"
        (cd "$SCRIPT_DIR" && run_with_tracking "$rescsv" \
            sudo "$exe" "$THROUGHPUT_VID" "$THROUGHPUT_PID" "$THROUGHPUT_INTERFACE" \
            "$THROUGHPUT_EP_OUT" "$THROUGHPUT_EP_IN" \
            "$THROUGHPUT_START_LBA" "$size" "$THROUGHPUT_RUNS" "$variant")
    done
}

run_throughput_wasi() {
    local wasm="$1"
    local variant="$2"
    echo "=== Throughput WASI: $variant (${THROUGHPUT_LABEL}) ==="
    for size in "${THROUGHPUT_SIZE_MB[@]}"; do
        echo "  -> $size MB"
        local rescsv="$RESULTS_DIR/resources_throughput_${variant}_${THROUGHPUT_LABEL}_${size}MB.csv"
        (cd "$SCRIPT_DIR" && run_with_tracking "$rescsv" \
            sudo cargo run --release --manifest-path "$WASI_HOST_DIR/Cargo.toml" -- \
            --debug_level off --component-path "$wasm" \
            "$THROUGHPUT_VID" "$THROUGHPUT_PID" "$THROUGHPUT_INTERFACE" \
            "$THROUGHPUT_EP_OUT" "$THROUGHPUT_EP_IN" \
            "$THROUGHPUT_START_LBA" "$size" "$THROUGHPUT_RUNS" "$variant")
    done
}

# ══════════════════════════════════════════════════════════════════════════════
# ── HELPERS: INIT-TIJD  ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

run_init_native() {
    local exe="$1"
    local variant="$2"
    local vid="$3"; local pid="$4"; local iface="$5"; local label="$6"
    echo "=== Init native: $variant ($label) ==="
    (cd "$SCRIPT_DIR" && sudo "$exe" "$vid" "$pid" "$iface" "$INIT_ITERATIONS" \
        "${variant}_${label}")
}

run_init_wasi() {
    local wasm="$1"
    local variant="$2"
    local vid="$3"; local pid="$4"; local iface="$5"; local label="$6"
    echo "=== Init WASI: $variant ($label) ==="
    (cd "$SCRIPT_DIR" && sudo cargo run --release --manifest-path "$WASI_HOST_DIR/Cargo.toml" -- \
        --debug_level off --component-path "$wasm" \
        "$vid" "$pid" "$iface" "$INIT_ITERATIONS" "${variant}_${label}")
}

# ══════════════════════════════════════════════════════════════════════════════
# ── HELPERS: STREAMS (USB 3.0)  ──────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

run_streams_test() {
    local wasm="$PROJECT_ROOT/wasi-usb/out/streams-test.wasm"
    local log="$RESULTS_DIR/streams_test_${THROUGHPUT_LABEL}.log"
    echo "=== Streams test (${THROUGHPUT_LABEL}) ==="
    if [ ! -f "$wasm" ]; then
        echo "  ! streams-test component niet gebouwd. Run:"
        echo "    cd $PROJECT_ROOT/wasi-usb && just build-example streams-test"
        return 1
    fi

    sudo cargo run --release --manifest-path "$WASI_HOST_DIR/Cargo.toml" -- \
        --component-path "$wasm" -- \
        "$THROUGHPUT_VID" "$THROUGHPUT_PID" "$THROUGHPUT_INTERFACE" \
        "$THROUGHPUT_EP_OUT" "$THROUGHPUT_EP_IN" \
        "$STREAMS_NUM" "$STREAMS_PAYLOAD" 2>&1 | tee "$log"
    echo "  log: $log"
}

# ══════════════════════════════════════════════════════════════════════════════
# ── MAIN  ────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

MODE="${1:---all}"

if [[ "$MODE" == "--latency" || "$MODE" == "--all" ]]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo " LATENCY  — Pico 2 loopback (USB 2.0 FS)"
    echo "══════════════════════════════════════════"
    run_latency_native "$SCRIPT_DIR/c/latency_vanilla_native" "libusb_native"
    run_latency_native "$SCRIPT_DIR/rust/latency_native"      "rusb_native"
    run_latency_wasi   "$SCRIPT_DIR/c/latency_leroy.component.wasm"    "libusb_wasi"
    run_latency_wasi   "$SCRIPT_DIR/rust/latency_rusb.component.wasm"  "rusb_wasi"
fi

if [[ "$MODE" == "--throughput" || "$MODE" == "--all" ]]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo " THROUGHPUT  — SanDisk USB 3.0 SuperSpeed"
    echo "══════════════════════════════════════════"
    run_throughput_native "$SCRIPT_DIR/c/throughput_vanilla_native"      "libusb_native"
    run_throughput_native "$SCRIPT_DIR/rust/throughput_native"           "rusb_native"
    run_throughput_wasi   "$SCRIPT_DIR/c/throughput_leroy.component.wasm"   "libusb_wasi"
    run_throughput_wasi   "$SCRIPT_DIR/rust/throughput_rusb.component.wasm" "rusb_wasi"
fi

if [[ "$MODE" == "--init" || "$MODE" == "--all" ]]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo " INIT  — libusb stack cold-start"
    echo "══════════════════════════════════════════"
    # Pico (USB 2.0 FS)
    run_init_native "$SCRIPT_DIR/c/usb_init_native" "libusb_native" \
        "$LATENCY_VID" "$LATENCY_PID" "$LATENCY_INTERFACE" "$LATENCY_LABEL"
    run_init_wasi   "$SCRIPT_DIR/c/usb_init.component.wasm" "libusb_wasi" \
        "$LATENCY_VID" "$LATENCY_PID" "$LATENCY_INTERFACE" "$LATENCY_LABEL"
    # SanDisk (USB 3.0 SS)
    run_init_native "$SCRIPT_DIR/c/usb_init_native" "libusb_native" \
        "$THROUGHPUT_VID" "$THROUGHPUT_PID" "$THROUGHPUT_INTERFACE" "$THROUGHPUT_LABEL"
    run_init_wasi   "$SCRIPT_DIR/c/usb_init.component.wasm" "libusb_wasi" \
        "$THROUGHPUT_VID" "$THROUGHPUT_PID" "$THROUGHPUT_INTERFACE" "$THROUGHPUT_LABEL"
fi

if [[ "$MODE" == "--streams" || "$MODE" == "--all" ]]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo " STREAMS  — USB 3.0 Bulk Streams validatie"
    echo "══════════════════════════════════════════"
    run_streams_test || true
fi

echo ""
echo "Resultaten staan in: $RESULTS_DIR"
