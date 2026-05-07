# Benchmark suite

Documentation for the five-condition benchmark suite used in the thesis evaluation.

---

## The benchmark matrix

The evaluation compares USB access across five conditions and three workloads, giving 15 measurement cells. The design is deliberately redundant — C1 and C3 are native baselines in two languages, C2 and C4 are the WASM equivalents, C5 is the lowest-overhead WASM path.

### Conditions

| ID | Name | Language | Runtime | What it does |
|----|------|----------|---------|--------------|
| C1 | native-libusb | C | native ELF | Direct libusb calls, no WASI |
| C2 | wasi-libusb | C | wasmtime + WIT | C compiled to WASM via libusb-wasi backend |
| C3 | native-rusb | Rust | native ELF | rusb calling libusb, no WASI |
| C4 | wasi-rusb | Rust | wasmtime + WIT | Same Rust source as C3, but rusb -> libusb-wasi.a -> WIT |
| C5 | wasi-raw-wit | Rust | wasmtime + WIT | Direct `component:usb::*` calls via wit-bindgen |

What the comparisons isolate:
- **C1 vs C2**: total WASI overhead for C (WASM runtime + WIT boundary)
- **C3 vs C4**: total WASI overhead for Rust (same)
- **C4 vs C5**: how much overhead rusb adds as a wrapper over raw WIT calls
- **C1 ≈ C3** and **C2 ≈ C4**: language shouldn't be the bottleneck; if it is, something's wrong

### Workloads

| ID | Transfer | Device | VID:PID | What it measures |
|----|----------|--------|---------|-----------------|
| bulk | Bulk | SanDisk 3.2Gen1 USB drive | 0781:5581 | 30x SCSI READ(10), 512 KB per transfer |
| ctrl | Control | WASI-USB Loopback (Pico firmware) | cafe:4002 | 1000x control transfers, RTT distribution |
| int | Interrupt | PS5 DualSense or similar HID device | 054c:0ce6 | 1000x interrupt-IN poll, jitter |

**Why no isochronous workload?**
Control, bulk and interrupt all have synchronous libusb wrappers (`libusb_control_transfer`, `libusb_bulk_transfer`, `libusb_interrupt_transfer`): one call in, one result out. The libusb-wasi backend maps each of those directly to a single WIT round-trip on the host, so no event loop or second thread is needed in the guest — which is exactly why benchmarking them works cleanly.

Isochronous is structurally different. libusb deliberately has no synchronous iso API because the USB host controller schedules multiple packets per transfer (typically 32), each on its own 125 µs microframe boundary, and reports per-packet `actual_length` and `status` separately. The only way to use iso correctly is to submit several transfers in-flight and pump `libusb_handle_events` in a loop to collect callbacks — that loop *must* keep running while new transfers are being submitted. On a native system you just spin a while-loop. On WASIp2 that's impossible: there are no guest threads (`wasi-threads` is still an unstabilised proposal), so there's no second execution context to pump the event loop.

A host-side workaround exists in this codebase (originally built by Leroy): `usb-wasi-host` moves the event loop to a Tokio task on the host and exposes a single blocking `await-transfer` WIT call to the guest. That's enough to get the webcam demo working (25–30 fps on a Logitech Brio, see Evaluation §13.4 in the thesis), but it makes meaningful *benchmarking* impossible: all the interesting timing — submit latency, per-packet jitter, queueing efficiency — is buried behind the host-async boundary, and the guest only ever sees "the await took roughly one USB frame period". In practice the `w_iso` binaries either returned `LIBUSB_ERROR_INVALID_PARAM` on submit or hit the 5-second await timeout — neither of which reflects real iso overhead. Rather than extending Leroy's workaround further, the cleaner path is to wait for WASIp3, where `stream<u8>` primitives will let the guest consume isochronous data natively without needing guest threads at all. This is discussed in the Evaluation and Future Work chapters of the thesis.

The `w_iso.c` and `w_iso.rs` source files are kept in the repository as a reference for that future WASIp3 implementation. See Future Work §16.1.2 in the thesis for the full story.

---

## Hardware requirements

You need all three devices for a full run. Individual workloads can be run separately.

| Device | Notes |
|--------|-------|
| SanDisk 3.2Gen1 (or similar USB 3.x drive) | Must not be mounted before the run; unmount and unbind usb-storage first |
| WASI-USB Loopback (`cafe:4002`) | Raspberry Pi Pico running the USB identity firmware |
| PS5 DualSense or DualShock 4 | Disconnect from wireless mode first |

The bulk workload only works reliably on Linux because `IOUSBMassStorageClass` on macOS can't be detached without SIP changes. See the note in the main README.

---

## Software requirements

Everything listed in [compiling.md](./compiling.md) applies here. For the analysis script specifically:

```bash
pip install pandas seaborn scipy matplotlib
```

---

## Building

### Everything at once

```bash
just bench-build
```

This runs in order: libusb-vanilla (C1 fallback), C1 (CMake native), C2 (CMake WASI), C3+C5 (cargo native + wasm32-wasip2), C4 (build-c4.sh). See [compiling.md §6](./compiling.md#6-benchmark-suite-c1-c5) for what each step produces.

### Per condition

```bash
# C1 - native libusb (C)
cmake -B benchmarks/usb-bench-c/build-native benchmarks/usb-bench-c
cmake --build benchmarks/usb-bench-c/build-native

# C2 - WASI libusb (C WASM)
cmake -B benchmarks/usb-bench-c/build-wasi benchmarks/usb-bench-c \
    -DCMAKE_TOOLCHAIN_FILE=benchmarks/usb-bench-c/toolchain-wasi.cmake
cmake --build benchmarks/usb-bench-c/build-wasi

# C3 - native rusb (Rust)
cargo build --release --bins --manifest-path benchmarks/usb-bench-rs/Cargo.toml

# C4 - rusb compiled to WASM
bash benchmarks/build-c4.sh

# C5 - raw WIT (Rust WASM)
cargo build --release --bins --target wasm32-wasip2 \
    --manifest-path benchmarks/usb-bench-rs/Cargo.toml
```

---

## Running

### Pre-flight: recovering a stuck SanDisk

The bulk binaries do a BOT Reset followed by `clear_halt` on both bulk endpoints at startup, which is enough to recover from most stuck states (a previous run interrupted mid-transfer, an aborted Ctrl-C, etc.). The harness's prep step also unmounts the drive and unbinds `usb-storage` before each bulk run.

If you still see sustained `CBW write failed: r=-1` across all five conditions, the drive's internal firmware is wedged at a level that no host-side reset can fix. The only reliable recovery is a physical unplug, **wait 15 seconds**, and plug back in. The 15 seconds isn't superstition — internal caps on USB sticks keep the firmware powered during short unplugs, so a quick yank-and-replug doesn't actually power-cycle anything.

### Quick sanity check

```bash
just bench-smoke       # 1 iteration per cell, all conditions and workloads
```

### Why these iteration counts?

The defaults — warmup=100, bulk=1500, ctrl=10000, int=10000 — aren't arbitrary. Leroy (2022) ran up to 1 million iterations for pure latency measurements, but that was a tight loopback on a local network; USB round-trips are two to three orders of magnitude slower. After a few exploratory runs I looked at how quickly the standard error of the mean (SEM) stabilised:

- **ctrl and int (10 000 iterations):** Round-trip time converges to a stable SEM within the first few hundred iterations. 10 000 gives a comfortable margin, keeps a single condition under two minutes, and matches typical HCI latency benchmark practice. Going to 1 million would take ~4 hours per condition for no meaningful gain in precision.
- **bulk (1 500 iterations):** Each iteration is a 512 KB SCSI READ(10) — 1 500 × 512 KB ≈ 750 MB of actual USB traffic per condition. The 512 KB size is deliberate: USB SuperSpeed bulk has a max packet size of 1 024 B and a typical burst depth of 16, giving 16 × 1 024 B = 16 KiB per physical transaction. 512 KB = 32 bursts, which amortises per-transfer latency well without blowing the guest's linear-memory budget. Throughput stabilises after roughly 200–300 iterations once the drive's internal cache effects average out. 1 500 gives several full cache-flush cycles while keeping the run under five minutes per condition.
- **warmup (250 iterations):** The first ~50 iterations show elevated latency in every condition (JIT warmup for WASM, page-fault storms for native). For bulk specifically, the SanDisk's internal cache distorts throughput for roughly the first 200 iterations (250 × 512 KB ≈ 125 MB of warmup reads gets it to steady state). 250 covers both effects across all three workloads; the logged data starts only after warmup completes.

All five conditions run sequentially with the same counts, so any remaining device-side variance (temperature, internal wear-levelling) affects all conditions equally.

### Full measurement run

```bash
just bench-run         # default iterations per workload (bulk=1500, ctrl=10000, int=10000), warmup=250

# Restrict to specific workloads or conditions
just bench-run --workloads bulk,ctrl
just bench-run --conditions C3,C4,C5

# Dry run (prints commands without executing)
just bench-dry
```

Results are written to `results/<ISO-timestamp>/` with one CSV per workload.

### Running a single binary manually

```bash
# C1 - native
sudo benchmarks/usb-bench-c/build-native/w_ctrl output.csv cafe:4002 100

# C2 - WASM via host
sudo usb-wasi-host/target/release/usb-wasi-host \
    -c benchmarks/usb-bench-c/build-wasi/w_ctrl.wasm -- \
    output.csv cafe:4002 100

# C3 - native Rust
sudo benchmarks/usb-bench-rs/target/release/w_ctrl output.csv cafe:4002 100

# C4 - WASM rusb
sudo usb-wasi-host/target/release/usb-wasi-host \
    -c benchmarks/usb-bench-rs/target-wasi-rusb/wasm32-wasip2/release/w_ctrl.wasm -- \
    output.csv cafe:4002 100

# C5 - WASM raw WIT
sudo usb-wasi-host/target/release/usb-wasi-host \
    -c benchmarks/usb-bench-rs/target/wasm32-wasip2/release/w_ctrl.wasm -- \
    output.csv cafe:4002 100
```

CLI arguments (all binaries): `<output.csv> <VID:PID> <iterations> [--condition <name>]`

---

## Analysing results

```bash
just bench-analyze                              # analyse most recent results/
python3 benchmarks/analyze.py results/<dir>/   # specific run
python3 benchmarks/analyze.py results/<dir>/ --plots out/figs/  # save figures
```

The analysis script produces:

1. Correctness table — SHA-256 checksums per workload across all 5 conditions (they should match)
2. Throughput bar chart — MB/s per condition for W-bulk
3. RTT violin plots — latency distribution for W-ctrl and W-int
4. CPU usage — user vs. sys time per condition
5. Memory usage — RSS peak + WASM linear memory (WASM conditions only)
6. Wrapper overhead — C4 vs C5 comparison (how much rusb adds)
7. Statistical tests — Mann-Whitney U + Cliff's delta for each pair

---

## CSV schema

One row per measurement:

```
timestamp_iso, condition, workload, iteration,
bytes, duration_ns,
user_cpu_us, sys_cpu_us, rss_peak_kb, guest_mem_bytes,
checksum_hex, notes
```

| Field | Type | Description |
|-------|------|-------------|
| `timestamp_iso` | string | ISO-8601 timestamp of the measurement |
| `condition` | string | `native-libusb`, `wasi-libusb`, `native-rusb`, `wasi-rusb`, `wasi-raw-wit` |
| `workload` | string | `bulk`, `ctrl`, `int` |
| `iteration` | integer | 0-based sequence number |
| `bytes` | integer | bytes transferred in this iteration |
| `duration_ns` | integer | RTT in nanoseconds (timed section only) |
| `user_cpu_us` | integer | user-CPU time delta (µs) via `getrusage` |
| `sys_cpu_us` | integer | sys-CPU time delta (µs) via `getrusage` |
| `rss_peak_kb` | integer | peak RSS in kB after the iteration |
| `guest_mem_bytes` | integer | WASM linear memory in bytes (0 for native) |
| `checksum_hex` | string | SHA-256 of payload (bulk only, empty for ctrl/int) |
| `notes` | string | free field (empty unless there's an error) |

---

## How C4 works under the hood

C4 is the interesting one: same Rust source as C3, compiled to `wasm32-wasip2`, linking against `libusb-wasi.a` instead of system libusb. The trick is that `rusb` uses `libusb1-sys`, whose `build.rs` probes `pkg-config` for `libusb-1.0`. By redirecting `PKG_CONFIG_LIBDIR` to a controlled sysroot, the probe finds our fake `.pc` file pointing at `libusb-wasi-rust.a` instead.

```
Rust source (w_bulk.rs, identical for C3 and C4)
    |
    v
rusb  ->  libusb1-sys  (pkg-config probe -> sysroot-wasi)
    |
    v
libusb-wasi-rust.a   (libusb API, WIT-backed)
    |
    v
component:usb/*@0.2.1   (WIT boundary)
    |
    v
usb-wasi-host  ->  OS USB stack
```

The sysroot file (`sysroot-wasi/usr/lib/pkgconfig/libusb-1.0.pc`) is four lines. No upstream forks, no patches to rusb or libusb1-sys. A developer with existing rusb code only needs to point pkg-config at the sysroot.

### Why `libusb-wasi-rust.a` and not `libusb-wasi.a`?

`libusb-wasi.a` was built as a C WASM component, so `cguest.o` inside it contains a run-export handler (`__wasm_export_exports_wasi_cli_run_run`) that bridges `wasi:cli/run` to C's `main()`. Rust's `wasm-component-ld` provides its own run-export via `__main_void`. Two providers = linker error.

The fix: patch `cguest.o` to mark that symbol `VISIBILITY_HIDDEN` instead of `EXPORTED|NO_STRIP`, then repack as `libusb-wasi-rust.a`. `--gc-sections` removes the dead handler and its unresolved import. The actual WIT import stubs (`component_usb_*`) survive because they're called from `wasi_usb.o`.

The patched archive is checked in at `libusb-wasi/libusb-wasi-rust.a` and used automatically by `benchmarks/build-c4.sh`.

### Transport selection in Rust source

Each `w_*.rs` binary selects its transport via cfg attributes, so no source duplication:

```rust
// Valid for C3 (native) and C4 (wasm32-wasip2 + feature c4-rusb-wasi)
#[cfg(any(not(target_family = "wasm"), feature = "c4-rusb-wasi"))]
use native::CtrlDevice as ActiveDevice;

// Valid for C5 (wasm32-wasip2, no c4-rusb-wasi)
#[cfg(all(target_family = "wasm", not(feature = "c4-rusb-wasi")))]
use wasm::CtrlDevice as ActiveDevice;
```

C3 and C4 compile the same source, only the build configuration differs.

---

## Troubleshooting

**`LIBUSB_ERROR_ACCESS` / Permission denied**: USB access requires root. Run with `sudo`.

**SanDisk bulk failures on macOS**: `IOUSBMassStorageClass` stays attached after unmounting. Run bulk benchmarks on Linux.

**SanDisk bulk failures even on Linux**: The drive may be in a stuck BBB state from a previous failed transfer. Unplug for ~15 seconds to let it reset. The `run.sh` prep automatically unmounts and unbinds `usb-storage`, but it can't fix a stuck drive.

**Checksums don't match between conditions**: Something is wrong in the data path (wrong SCSI command, wrong LBA, transfer truncated). Check the `notes` column in the CSV for error messages.

**USB device not found during smoke test**: Check it's connected and the OS driver isn't holding it. On Linux, `lsusb` should show it; on macOS, `system_profiler SPUSBDataType`.

**C4 linker error `failed to resolve import env::exports_wasi_cli_run_run`**: The `libusb-wasi-rust.a` isn't patched correctly. Check that `wasm-tools dump libusb-wasi/libusb-wasi-rust.a | grep __wasm_export_exports_wasi_cli_run_run` shows `VISIBILITY_HIDDEN`.

**C4 linker error `failed to find export of wasi:cli/run@0.2.5`**: Wrong `cguest_component_type.o`. The `build.rs` must point to `usb-bench-c/bindings/guest_component_type.o`, not the one in `rusb-wasi/examples/wasi-workload/wasi-sysroot/usr/lib/` (that one requires `@0.2.5` which Rust 1.93.x doesn't emit).

**`guest_component_type.o` not found**: Build the C2 WASM binaries first (`cmake --build benchmarks/usb-bench-c/build-wasi`), which generates it as a side effect.

---

*Thesis: Sibren Wieme, Ghent University, 2026.*
