# Implementation — what was built and why

This document is the developer- and defense-facing record of the concrete
contributions made in this work. For each contribution it gives:

- **what** the addition is,
- **why** it was needed (the problem it solves),
- **why this approach** rather than the alternatives,
- **where** to find the code (file + section).

It complements [`architecture.md`](./architecture.md), which describes what
the system *is* once finished. The split is deliberate: the architecture doc
reads as if everything had always been there; this doc reads as a logbook of
deliberate decisions.

The starting point is the prior work of **Wouter Hennen** (initial WIT-based
host, single-backend, synchronous-only) and **Robbe Leroy** (`libusb-wasi.a`
with the `wasi_usb.c` backend and cguest bindings). Everything below is
**on top of** that baseline.

---

## Contributions at a glance

| # | Contribution | Files | Defense reference |
|---|--------------|-------|-------------------|
| 1 | Backend abstraction (`HostUsbBackend` trait) | `usb-wasi-host/src/usb_backend.rs` | §1 below |
| 2 | Isochronous transfer API + flat-buffer strategy | `wit/transfers.wit`, `usb-wasi-host/src/main.rs` | §2 |
| 3 | Resource-lifecycle correctness (3 critical bug fixes) | `usb-wasi-host/src/main.rs`, `libusb-wasi/libusb/os/wasi_usb.c` | §3 |
| 4 | Tokio oneshot async-transfer pattern | `usb-wasi-host/src/main.rs` | §4 |
| 5 | Host instrumentation (`instrument.rs`) | `usb-wasi-host/src/instrument.rs` | §5 |
| 6 | C4 cross-compile pipeline (rusb → WASM, no fork) | `sysroot-wasi/`, `benchmarks/build-c4.sh` | §6 |
| 7 | UVC webcam guest (smart-guest CPS workload) | `usb-wasi-guest/examples/webcam/` | §7 |
| 8 | Five-condition benchmark suite (C1–C5) | `benchmarks/usb-bench-c/`, `benchmarks/usb-bench-rs/` | [`benchmarking.md`](./benchmarking.md) |

---

## 1. Backend Abstraction — `HostUsbBackend` Trait

### Problem

In the inherited host, libusb FFI calls were inlined throughout `main.rs`.
This meant:

- *No way to swap backends* for the libusb-vs-rusb thesis question.
- *No way to mock* USB for unit tests without real hardware.
- *No clean place* to put cross-cutting concerns (logging, capability
  filtering at the enumeration boundary, descriptor flattening).

### Approach

A trait `HostUsbBackend` (in `usb-wasi-host/src/usb_backend.rs`) defines
*every* OS-level USB operation the host needs. `LibusbBackend`
implements it via `libusb1-sys`. The host stores `Box<dyn HostUsbBackend>`
in `MyState` and never references `libusb1_sys` outside the trait impl.

```rust
pub trait HostUsbBackend: Send + Sync {
    fn init(&mut self) -> Result<(), LibusbError>;
    fn list_devices(&mut self, allowed: &AllowedUSBDevices)
        -> Result<Vec<(UsbDevice, DeviceDescriptor, DeviceLocation)>, LibusbError>;
    fn open(&mut self, device: &UsbDevice) -> Result<UsbDeviceHandle, LibusbError>;
    fn claim_interface(&mut self, handle: &UsbDeviceHandle, ifac: u8) -> Result<(), LibusbError>;
    fn enable_hotplug(&mut self, allowed: AllowedUSBDevices) -> Result<(), LibusbError>;
    fn poll_events(&mut self) -> Vec<(Event, Info, UsbDevice)>;
    /* … set_configuration, get_*_descriptor, kernel_driver_*, etc. … */
}
```

### Why a trait, not generics?

A generic `MyState<B: HostUsbBackend>` would force a backend choice at
compile time and propagate the type parameter through every WIT impl,
duplicating the binary if multiple backends were ever desired in one build.
Dynamic dispatch through `Box<dyn …>` adds a single vtable indirection per
USB call — completely negligible compared to the syscall and hardware
latency that follows. The flexibility is worth the indirection.

### Why filter the allow-list inside the backend?

`list_devices(&mut self, allowed: &AllowedUSBDevices)` takes the allow-list
as a parameter and filters during the libusb enumeration loop. This means a
disallowed device is *never* assigned a `Resource` and is never visible to
the `MyState::table` at all. If the filter were applied higher up (after
the backend returned), a future capability bug elsewhere in the host could
expose disallowed devices. Push the policy down to where the data
originates.

---

## 2. Isochronous Transfer API

### Problem

The inherited WIT supported control / bulk / interrupt transfers but not
isochronous. Isochronous is mandatory for cameras (UVC), audio, and any
constant-bitrate USB device. Adding it required answering:

1. How does the guest specify "N packets of size S each"?
2. How are *per-packet* statuses (success / stall / overrun / …) reported?
3. How are variable-actual-length packets returned across the WASI ABI,
   which is severely restricted compared to native libusb?

### Approach — flat-buffer + sidecar metadata

```wit
enum iso-packet-status {
    success, error, timed-out, cancelled, stall, no-device, overflow,
}

record iso-packet {
    actual-length: u32,
    status:        iso-packet-status,
}

record transfer-result {
    data:    list<u8>,           // flat: pkt0 stride | pkt1 stride | …
    packets: list<iso-packet>,   // empty for non-iso; one entry per ISO packet
}

record transfer-options {
    endpoint:    u8,
    timeout-ms:  u32,
    stream-id:   u32,
    iso-packets: u32,            // NEW: number of ISO packets to allocate
}
```

The host:

1. Allocates `libusb_alloc_transfer(iso_packets)` so the underlying struct
   has the per-packet descriptor array (in `new_transfer`).
2. Configures every per-packet descriptor with `length = stride` (where
   `stride = total_bytes / num_packets`) so each packet has equal max
   reservation on the bus.
3. In the C callback, after libusb fills the descriptor array with the
   actual bytes received per packet, reads each `(actual_length, status)`
   into a `Vec<(u32, i32)>` and stores it in
   `Arc<Mutex<Option<Vec<(u32, i32)>>>>` shared with the `UsbTransfer`.
4. `await_transfer` reads this `Arc<Mutex<…>>` and reshapes it into
   `Vec<IsoPacket>` for the WIT return.

![ISO flat-buffer strategy](../diagrams/iso_flatbuffer.svg)

### Rejected alternatives — why not …

#### Alternative A — `list<list<u8>>`

```wit
record transfer-result {
    iso-packets: list<list<u8>>,
}
```

Rejected because the WASI component-model canonical ABI does not stably
support nested growable lists across the host/guest boundary. wit-bindgen
emits the marshalling code, but the lifetime and ownership of the inner
allocations is fragile and in some toolchain versions outright broken. A
flat `list<u8>` is one ABI memcpy and decades of compiler optimization
behind it.

#### Alternative B — separate `await-iso-transfer`

```wit
await-transfer:     func(...) -> result<list<u8>, libusb-error>;
await-iso-transfer: func(...) -> result<list<iso-packet>, libusb-error>;
```

Rejected because:
- it duplicates the entire async/oneshot machinery in the host,
- the guest has to pick which to call based on a transfer it submitted, which
  duplicates type information already in the WIT,
- isochronous is the only transfer type with per-packet status, but that
  doesn't justify a parallel API surface.

A single `await-transfer` that returns `TransferResult { data, packets }`
where `packets` is empty for non-iso transfers is cleaner. The guest
trivially detects "is this iso?" by `if !result.packets.is_empty()`.

#### Alternative C — pollable stream of frames

Rejected because UVC frame *reassembly* (FID-bit tracking, header parsing,
JPEG validation) is *guest* logic. The host should not know what UVC is. A
per-frame stream interface would push UVC semantics into the host runtime,
contradicting the dumb-host principle. The flat-packet view leaves all
protocol decoding in `webcam.rs` where it belongs.

### Why `iso_packet_results` is `Arc<Mutex<Option<…>>>`

The C callback runs on the libusb event thread; `await_transfer` runs on the
Tokio main thread. They communicate through the shared
`Arc<Mutex<Option<Vec<(u32, i32)>>>>`. The `Option` is `None` until the
callback fires, at which point it becomes `Some(vec)`. `await_transfer`
then `take()`s the value, leaving `None` again — so the cell is reset for
any future re-submit on the same `UsbTransfer` (for transfers that get
re-submitted in a tight loop, like the W-iso benchmark).

---

## 3. Resource-Lifecycle Bug Fixes

Three bugs in inherited code were fixed during this work. Each was found by
running real workloads (the webcam, the W-iso benchmark, the tight-loop
control transfer test) and is documented here because they reveal subtle
properties of the WASI component model and libusb that any future contributor
needs to know.

### 3.1 The borrow bug

#### Symptom

Webcam crashed on **frame #2** with:

```
wasi::io::streams::OutputStream::blocking_write_and_flush
  → "resource is of another type"
```

Frame #1 worked perfectly. The error came from the next `eprintln!` in the
guest, which suddenly couldn't find its stderr OutputStream resource.

#### Root cause

`await-transfer` is declared `borrow<transfer>` in the WIT. Wasmtime
allocates a *temporary* slot M in the ResourceTable, distinct from the
**owned** slot K from `new-transfer`. After the host call returns, Wasmtime
itself frees slot M.

The buggy implementation called `self.table.delete(self_)` inside
`await_transfer`, freeing slot M from underneath Wasmtime. After enough
ISO transfers, the freed slot index coincided with the OutputStream's
ResourceTable slot. The next `eprintln!` looked up that slot and found a
`UsbTransfer` instead of an `OutputStream` — hence "resource is of another
type."

#### Fix

Removed the line. The owned slot K is cleaned up entirely by
`HostTransfer::drop` at end of guest scope.

```rust
// usb-wasi-host/src/main.rs ~line 548
async fn await_transfer(&mut self, self_: Resource<UsbTransfer>) -> Result<...> {
    /* … receiver.await, build TransferResult … */

    // Do NOT call self.table.delete(self_) here.
    // `await-transfer` in the WIT is declared as `borrow<transfer>`, so
    // Wasmtime passes the host a *borrow* entry (a temporary ResourceTable
    // slot M that is distinct from the owned slot K created by new_transfer).
    // Calling table.delete on M would corrupt unrelated WASI resources
    // (e.g. the stderr OutputStream).

    Ok(TransferResult { data, packets })
}
```

#### Defense lesson

The WASI component model's resource model is not "shared pointer with
explicit free." It is "owned handle in K, transient borrow handle in M
distinct from K." Borrow lifetime is Wasmtime's responsibility, not the
host's. This is a **principled** design — once internalized — but the
failure mode (silent slot reuse) is sharp.

### 3.2 The three-state Drop

#### Problem

`UsbTransfer::drop` originally:

```rust
fn drop(&mut self, self_: Resource<UsbTransfer>) -> Result<(), Error> {
    if let Ok(transfer) = self.table.get(&self_) {     // get, not delete
        unsafe { libusb_cancel_transfer(transfer.transfer); }
    }
    Ok(())
    // BUG: libusb_free_transfer never called
    // BUG: table.delete never called → resource table grows unboundedly
}
```

This caused both a memory leak (transfers accumulate) and a use-after-free
(libusb_cancel_transfer on a transfer the callback already freed).

#### Fix — explicit state machine

```rust
fn drop(&mut self, self_: Resource<UsbTransfer>) -> Result<(), Error> {
    if let Ok(transfer) = self.table.delete(self_) {
        unsafe {
            if transfer.completed.load(Ordering::SeqCst) {
                // (a) Callback already fired and called libusb_free_transfer.
                //     Nothing to do.
            } else if transfer.receiver.is_some() {
                // (b) Submitted, still in flight. Cancel; the callback will
                //     fire with status=CANCELLED and call libusb_free_transfer.
                let _ = libusb_cancel_transfer(transfer.transfer);
            } else {
                // (c) Allocated by new_transfer but never submitted.
                //     No callback will ever fire. Free it ourselves.
                libusb_free_transfer(transfer.transfer);
            }
        }
    }
    Ok(())
}
```

| State | `completed` | `receiver` | Action |
|-------|-------------|------------|--------|
| Awaited | `true` | `None` | nothing (callback freed) |
| In flight | `false` | `Some` | `libusb_cancel_transfer` |
| Allocated only | `false` | `None` | `libusb_free_transfer` |

#### Defense lesson

Async resource cleanup is **not** symmetric with allocation. A submitted
transfer may complete on a different thread before drop runs, may be in
flight at drop, or may never have been submitted at all. The correct API
records sufficient state to disambiguate without race conditions.

### 3.3 LIBUSB_ERROR_BUSY on tight ISO loops

#### Symptom

C2/C4 isochronous benchmark (`w_iso.c`) fails on iteration #2 with
`LIBUSB_ERROR_BUSY` — a single re-used `libusb_transfer` cannot be
re-submitted.

#### Root cause

In the inherited `wasi_usb.c`, `wasm_submit_transfer` was synchronous: it
called the WIT `submit` *and* `await` *and then* signalled completion via
`usbi_handle_transfer_completion()`, all before returning to libusb's core.

The libusb core code in `libusb/io.c` does:

```
libusb_submit_transfer():
    1. state_flags = 0                ← clears IN_FLIGHT
    2. backend->submit_transfer()     ← synchronous: completes here!
    3. state_flags |= IN_FLIGHT       ← sets IN_FLIGHT *after* return
```

After step 3, `IN_FLIGHT` is set on a transfer that already completed. The
WASI event loop never clears it because there are no real fds to poll. The
next iteration sees `IN_FLIGHT` → `BUSY`.

#### Fix — defer completion to `wasm_handle_events`

In `libusb-wasi/libusb/os/wasi_usb.c`:

```c
// Don't signal completion from submit_transfer. Mark and queue.
tpriv->completed = 1;
tpriv->transfer_status = LIBUSB_TRANSFER_COMPLETED;
wasi_pending_completions++;
return LIBUSB_SUCCESS;

// In wasm_handle_events (called from the event loop *after* IN_FLIGHT is set):
list_for_each_entry(itransfer, &ctx->flying_transfers, list, ...) {
    if (tpriv->completed) {
        usbi_handle_transfer_completion(itransfer, tpriv->transfer_status);
        // ↑ now runs after IN_FLIGHT is set → correctly clears it
    }
}
```

#### Defense lesson

A synchronous backend in an async-by-design host is an impedance mismatch.
The fix is the textbook "defer to the event loop" pattern, but spotting the
bug requires understanding that `IN_FLIGHT` is set *after* the backend
returns, not before. This is documented in libusb but not obvious.

---

## 4. Async Transfer — Tokio Oneshot Pattern

USB transfers are inherently async: `libusb_submit_transfer` returns
immediately and the actual completion is signalled later via a C callback
on libusb's event thread. We need to bridge that to Wasmtime's async
runtime.

### Approach

```rust
struct TransferContext {
    sender:   oneshot::Sender<Result<Vec<u8>, LibusbError>>,
    completed: Arc<AtomicBool>,
    buffer:    Box<[u8]>,
    iso_packet_results: Arc<Mutex<Option<Vec<(u32, i32)>>>>,
}

// In submit_transfer:
let (sender, receiver) = oneshot::channel();
let ctx = Box::new(TransferContext { sender, ... });
(*transfer_ptr).user_data = Box::into_raw(ctx) as *mut _;
(*transfer_ptr).callback  = transfer_callback;
libusb_submit_transfer(transfer_ptr);
usb_transfer.receiver = Some(receiver);     // store on host side

// The C callback (different thread):
extern "system" fn transfer_callback(transfer: *mut libusb_transfer) {
    unsafe {
        let ctx = Box::from_raw((*transfer).user_data as *mut TransferContext);
        let result = parse_completion_status(transfer);
        ctx.completed.store(true, Ordering::SeqCst);
        let _ = ctx.sender.send(result);
        libusb_free_transfer(transfer);
        // ctx drops here — buffer freed, sender consumed
    }
}

// In await_transfer (Tokio thread, async):
async fn await_transfer(&mut self, self_: Resource<UsbTransfer>) -> ... {
    let receiver = self.table.get_mut(&self_).unwrap().receiver.take().unwrap();
    let data = receiver.await?;     // ← Tokio yields here; libusb thread resumes us
    /* … */
}
```

### Why oneshot, not Condvar / mpsc / pollable

- **One producer, one consumer**: oneshot is exactly the right shape.
- **Tokio integration**: `Receiver::await` cooperates with Wasmtime's async
  component support without blocking the executor. A `Condvar` would block
  a Tokio worker thread.
- **No fan-in**: only one transfer per resource, so no need for `mpsc`
  buffering.

### Why `Arc<AtomicBool>` for `completed`

Two readers need to know whether the callback has fired:

1. The C callback (writes `true`).
2. `HostTransfer::drop` (reads to choose the cleanup path — see §3.2).

`Arc` gives both ends a stable reference; `AtomicBool` lets the Drop path
read-modify the flag without a mutex (the flag is at most one transition
per transfer lifetime). The compiler inserts the right memory ordering
fences so the C callback's store is observable to the Drop path.

---

## 5. Instrumentation — `instrument.rs`

### Problem

The thesis evaluation needs per-call latency attribution: how much of the
total transfer time is host-side overhead vs. USB bus time vs. Wasmtime
boundary crossing. Without per-call data, the WASI overhead claim is
unfalsifiable.

### Approach — RAII trace guard

```rust
pub struct CallTrace {
    op: &'static str,
    started: Instant,
    detail: String,
    #[cfg(target_os = "linux")] ctx_start: Option<CtxSwitches>,
}

impl CallTrace {
    pub fn enter(op: &'static str) -> Self { /* records start time + ctx-switches */ }
    pub fn detail(mut self, kv: &str) -> Self { /* builder-style */ }
}

impl Drop for CallTrace {
    fn drop(&mut self) {
        // Fast path: skip everything if RUST_LOG doesn't include wasi_usb_trace
        if !log::log_enabled!(target: "wasi_usb_trace", log::Level::Info) { return; }
        let dur_us = self.started.elapsed().as_micros();
        log::info!(target: "wasi_usb_trace", "op={} dur_us={} {} {}",
            self.op, dur_us, ctx_deltas, self.detail);
    }
}
```

Used at the top of every interesting WIT method:

```rust
fn submit_transfer(&mut self, ...) {
    let _t = CallTrace::enter("submit_transfer")
        .detail(&format!("xfer_type={} len={} dir={}", ...));
    /* … existing impl … */
}   // _t drops here → log line emitted
```

Output (with `RUST_LOG=wasi_usb_trace=info`):

```
[INFO  wasi_usb_trace] op=submit_transfer dur_us=42 ctx_vol_delta=0 ctx_nvol_delta=1 xfer_type=Bulk len=65536 dir=In
[INFO  wasi_usb_trace] op=await_transfer  dur_us=18027 ctx_vol_delta=1 ctx_nvol_delta=0
[INFO  wasi_usb_trace] op=new_transfer    dur_us=5  ctx_vol_delta=0 ctx_nvol_delta=0 xfer_type=Isochronous buf_size=32768 ep=0x81 iso_pkts=32
```

Parseable by a 5-line shell or Python script for the thesis evaluation.

### Why RAII rather than function-entry/exit pairs

- **Cannot forget to log on early-return paths**. A function that returns
  `Err(LibusbError::Busy)` at the top still logs.
- **Composable**: the `.detail()` builder lets each method add context
  without a shared logging utility.
- **Zero cost when disabled**: the `log_enabled!` check is one atomic
  load (~1 ns); `Instant::now()` is ~20 ns; `/proc/self/status` is gated
  behind the same check so it's only paid when the trace is on.

### Linux-only ctx-switch counters

`/proc/self/status` exposes `voluntary_ctxt_switches` and
`nonvoluntary_ctxt_switches`. Reading the file at trace-enter and
trace-drop gives the delta during the call — a good proxy for OS
scheduling pressure during host work. Skipped on non-Linux because no
equivalent is portable.

---

## 6. C4 Cross-Compile Pipeline

### Problem

C4 in the benchmark matrix is *Rust rusb code → wasm32-wasip2 component*.
The expected approach was to fork `rusb` and `libusb1-sys`. That would
mean maintaining patches against two upstream crates indefinitely.

### Approach — pkg-config redirection (no forks)

`libusb1-sys`'s build.rs probes `pkg-config` to find `libusb-1.0`. By
publishing a tiny custom pkg-config file in a controlled sysroot and
setting `PKG_CONFIG_LIBDIR` + `PKG_CONFIG_ALLOW_CROSS=1`, we redirect the
probe to point at `libusb-wasi.a` instead of the host's
`libusb-1.0.so`.

![C4 cross-compile pipeline](../diagrams/crosscompile_pipeline.svg)

The single sysroot file:

```ini
# sysroot-wasi/usr/lib/pkgconfig/libusb-1.0.pc
prefix=${pcfiledir}/../../..
libusb_root=${prefix}/../libusb-wasi

Name: libusb-1.0
Description: libusb-1.0 cross-compiled for WASI (WIT-backed)
Version: 1.0.27
Libs: -L${libusb_root} -lusb-wasi-rust
Cflags: -I${libusb_root}/libusb
```

The build wrapper:

```bash
# benchmarks/build-c4.sh
export PKG_CONFIG_LIBDIR="${ROOT}/sysroot-wasi/usr/lib/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR="${ROOT}/sysroot-wasi"
export PKG_CONFIG_ALLOW_CROSS=1

cargo build --release --bins \
    --target wasm32-wasip2 \
    --features c4-rusb-wasi \
    --target-dir target-wasi-rusb
```

`build.rs` adds `guest_component_type.o` (built once for C2) to the link
arguments so the resulting `.wasm` carries the WIT component-type custom
section.

### Verification

```bash
wasm-tools print benchmarks/usb-bench-rs/target-wasi-rusb/wasm32-wasip2/release/w_bulk.wasm \
    | grep "import .*component:usb"
```

Lists the WIT imports — confirming the rusb call chain reaches the WIT
host runtime via `libusb-wasi.a`.

### Defense talking points

- **Zero upstream patches**. `rusb` and `libusb1-sys` from crates.io
  unchanged. The whole adaptation is one `.pc` file and an env-var.
- **Drop-in claim**: a Rust developer with existing rusb code only adds the
  build wrapper.
- **Isolates the WIT-overhead measurement**. C3 and C4 use the *same*
  Rust source. Differences are entirely in the link target →
  measured overhead is purely WASI-USB.

---

## 7. UVC Webcam Guest

The webcam is the framework's representative cyber-physical workload. It
demonstrates that complex, time-sensitive USB device-class protocols can
run entirely inside the Wasm sandbox.

### Pipeline

![Host/Guest architecture](../diagrams/host_guest_arch.svg)

The guest at `usb-wasi-guest/examples/webcam/src/webcam.rs` performs:

1. **Discovery**: `list_devices()` → find Brio 100 (`046d:094c`)
2. **Open**: `open()` → device handle
3. **Inspect**: `get_active_configuration_descriptor()` → enumerate alt-settings
4. **Claim**: `claim_interface(1)` → VideoStreaming interface
5. **UVC Probe** (Control transfer): negotiate format, framerate, resolution
6. **UVC Commit** (Control transfer): activate stream
7. **Switch alt-setting**: `set_interface_altsetting(1, 1)` → enable iso endpoints
8. **Loop**: `new_transfer(Isochronous, ep=0x81, buf=32 KiB, pkts=32)`
   → `submit_transfer()` → `await_transfer()` → reassemble frames
9. **Frame reassembly**: FID-bit tracking, MJPEG header validation
10. **Output**: write `out/latest.jpg` via WASI filesystem preopen

### UVC payload header

```
byte 0:  bHeaderLength  (typically 2 or 12)
byte 1:  bmHeaderInfo
  bit 0: FID  (Frame ID — toggles each new frame)
  bit 1: EOF  (end of frame)
  bit 2: PTS  (presentation time stamp)
  bit 3: SCR  (source clock reference)
  bit 6: ERR  (payload error)
  bit 7: EOH  (end of header)
```

The guest detects frame boundaries on FID flip; data after the header is
appended to a frame buffer until the JPEG EOI marker `0xFF 0xD9` or the
next FID flip.

### Buffer parameters

| Parameter | Value | Source |
|-----------|-------|--------|
| Transfer type | Isochronous | UVC mandates iso for VideoStreaming |
| Endpoint | `0x81` (IN, alt 1) | from configuration descriptor |
| Packets per transfer | 32 | balance between submit overhead and bus utilisation |
| Packet size (HS) | 1024 B | `wMaxPacketSize` for USB 2.0 HS iso |
| Buffer per transfer | 32 × 1024 = 32 KiB | flat buffer (see §2) |
| Frame size (640×480 MJPEG) | 20–40 KiB | scene-dependent |
| Frame rate | 30 fps | UVC negotiated |

### Why the host has zero UVC code

This is the dumb-host claim. The host's `main.rs` does not parse UVC
headers, does not understand frame boundaries, does not decode MJPEG. It
only forwards raw bytes between libusb's iso descriptor array and the WIT
boundary. All UVC logic — Probe/Commit, FID tracking, frame validation —
is in `webcam.rs` (~700 lines of Rust running inside the Wasm sandbox).
The host is reusable as-is for any USB device class.

### Platform note

| Platform | Status |
|----------|--------|
| Linux | Works end-to-end. `libusb_detach_kernel_driver` releases `uvcvideo`. |
| macOS | UVC interface is held exclusively by `IOUSBDeviceFamily`. Iso transfers time out at 5 s with 0 bytes. **Not a framework limitation** — same restriction applies to native libusb. |

---

## 8. Five-Condition Benchmark Suite

The benchmark suite is documented in detail in
[`benchmarking.md`](./benchmarking.md). Summary:

| Condition | Code path | Isolates |
|-----------|-----------|----------|
| **C1** native libusb (C) | C → libusb → OS | baseline |
| **C2** WASI libusb (C) | C → libusb-wasi.a → WIT → host | WASI overhead for C |
| **C3** native rusb (Rust) | Rust → rusb → libusb → OS | language baseline |
| **C4** WASI rusb (Rust) | Rust → rusb → libusb-wasi.a → WIT → host | WASI overhead for Rust |
| **C5** raw-WIT (Rust) | Rust → wit-bindgen → WIT → host | wrapper overhead vs raw |

The same C source compiles for C1 and C2 (only the link target differs);
the same Rust source compiles for C3 and C4. C5 is a separate raw-WIT
crate. This isolates the WIT overhead from language choice.

---

## 9. File-by-file change summary

| File | Status | Contribution |
|------|--------|-------------|
| `wit/transfers.wit` | Extended | iso-packet-status, iso-packet, transfer-result.packets |
| `wit/device.wit` | Extended | transfer-options.iso_packets |
| `usb-wasi-host/src/main.rs` | Largely rewritten | TransferContext, ISO callback, Tokio oneshot, three-state Drop, borrow-bug fix |
| `usb-wasi-host/src/usb_backend.rs` | New file | `HostUsbBackend` trait + `LibusbBackend` |
| `usb-wasi-host/src/instrument.rs` | New file | `CallTrace` RAII tracing |
| `libusb-wasi/libusb/os/wasi_usb.c` | Patched | Deferred-completion fix for IN_FLIGHT race |
| `libusb-wasi/libusb/os/wasi_usb.h` | Patched | Added `transfer_status` to `wasi_transfer_priv_t` |
| `usb-wasi-guest/examples/webcam/` | New sub-crate | UVC probe/commit, iso loop, frame reassembly |
| `benchmarks/usb-bench-c/` | New | C1+C2 benchmarks (W-bulk, W-ctrl, W-int, W-iso) |
| `benchmarks/usb-bench-rs/` | New | C3+C4+C5 benchmarks |
| `benchmarks/usb-native/` | New | C3 native rusb mass-storage workload source |
| `benchmarks/run.sh` | New | Robust harness with VID:PID device map, relative CSV paths, macOS auto-unmount |
| `benchmarks/analyze.py` | New | CSV → throughput/latency/heatmap plots |
| `benchmarks/build-c4.sh` | New | pkg-config redirection wrapper |
| `sysroot-wasi/usr/lib/pkgconfig/libusb-1.0.pc` | New | C4 cross-compile sysroot |

---

## See also

- [`architecture.md`](./architecture.md) — system as a whole
- [`benchmarking.md`](./benchmarking.md) — C1–C5 evaluation matrix and results
- [`compiling.md`](./compiling.md) — how to build everything
- [`thesis.md`](./thesis.md) — chapter mapping
- Diagrams in [`../diagrams/`](../diagrams/) — PlantUML sources + rendered SVG
