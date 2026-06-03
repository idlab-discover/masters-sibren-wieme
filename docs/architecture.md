# Architecture

This document describes the architecture of the WASI-USB framework: the host/guest split, the WIT interface design, the security model, the host runtime, and how async transfers work across the Wasm boundary.

**Build history**: the initial host runtime, WIT interface and bulk/control transfer support were built by Wouter Hennen and Warre Dujardin (2024). The async transfer pattern and `libusb-wasi.a` guest library were added by Robbe Leroy (2025). The isochronous extension, the refactor of the host's libusb FFI into a `HostUsbBackend` trait, instrumentation and the C1–C5 benchmark suite are contributions of this thesis (Sibren Wieme, 2026).

For the concrete design decisions and bug fixes in this thesis's contributions, see [implementation.md](./implementation.md).

---

## 1. High-Level Layering

![Host/Guest architecture](../diagrams/host_guest_arch.svg)

The framework has five layers, each separated by a well-defined interface:

| # | Layer | Purpose | Source |
|---|-------|---------|--------|
| 1 | Guest application | Application logic: UVC negotiation, FAT32 parsing, HID reports, benchmark code | `usb-wasi-guest/examples/` |
| 2 | Guest bindings | Translates library calls (rusb / libusb / raw) into WIT host calls | `rusb-wasi/`, `libusb-wasi/`, wit-bindgen |
| 3 | WIT interface | Stable contract: `component:usb@0.2.1` | `wit/` |
| 4 | Host runtime | Wasmtime + Rust host that dispatches WIT methods, owns USB resources, enforces capabilities | `usb-wasi-host/` |
| 5 | OS USB stack | libusb 1.0 + kernel driver (urb / IOUSBLib) | system |

The core design principle is **dumb host, smart guest**: the host exposes only generic USB primitives (open, claim, transfer). All protocol-specific logic (UVC Probe/Commit and MJPEG header parsing in the webcam guest, FAT32 traversal in the mass-storage guest) lives in the respective guest components. This keeps the host small and auditable, and means it works for any USB device class without changes.

---

## 2. WIT Interface Design

The interface is split across seven files under `wit/`: six interface files plus a `world.wit` that ties them together. Splitting by concern lets guest crates that only need a subset (for example, `lsusb` just wants `device.wit` + `descriptors.wit`) avoid pulling in the full surface.

| File | Defines |
|------|---------|
| `device.wit` | `usb-device`, `device-handle`, `list-devices`, `open`, `claim-interface`, `new-transfer`, `set-configuration`, … |
| `transfers.wit` | `transfer` resource, `transfer-type`, `transfer-options`, `transfer-result`, `submit-transfer`, `await-transfer`, isochronous extensions |
| `descriptors.wit` | Flattened `device-descriptor`, `configuration-descriptor`, `interface-descriptor`, `endpoint-descriptor` |
| `configuration.wit` | `config-value` variant (`unconfigured` / `value(u8)`) used by `set-configuration` |
| `hotplug.wit` | `event` flags (`arrived` / `left`), `info` record, `enable-hotplug`, `poll-events` |
| `errors.wit` | `libusb-error` enum mirroring libusb status codes |
| `world.wit` | `host`, `cguest`, `guest`, and `webcam-guest` world definitions |

### 2.1 Resource Model

Three resource types cross the host/guest boundary:

```wit
resource usb-device     // returned by list-devices; can be opened
resource device-handle  // returned by open(); claimable, can spawn transfers
resource transfer       // returned by new-transfer(); submit/await/cancel/drop
```

Resources are opaque integer handles on the guest side and live in the host's `wasmtime::component::ResourceTable`. The guest can hold a resource, pass it back to the host, or drop it, but it can't inspect or fabricate one. This is the basis of the capability model: a guest can only act on devices the host explicitly hands to it.

### 2.2 Borrow vs. Owned Semantics

The trickiest part of the WIT design is the owned vs. borrowed resource distinction:

```wit
new-transfer:    func(...) -> result<transfer, libusb-error>;          // returns OWNED
submit-transfer: func(self_: borrow<transfer>, data: list<u8>);        // BORROW
await-transfer:  func(xfer: borrow<transfer>) -> result<transfer-result, libusb-error>;
cancel-transfer: func(self_: borrow<transfer>);                        // BORROW
```

When the guest passes a `borrow<transfer>`, Wasmtime allocates a temporary ResourceTable slot for the duration of the host call, separate from the slot that owns the resource. Wasmtime cleans up that borrow slot itself after the call returns. The host must not call `table.delete` on it; see [implementation.md §3.1](./implementation.md#31-the-borrow-bug) for the crash this caused in practice.

### 2.3 Isochronous Transfer Extension

*Contribution of this thesis (Sibren Wieme, 2026).*

Isochronous transfers (camera, audio) deliver multiple variable-length packets per submit, with per-packet status. The original WIT didn't model this. The extension uses a flat-buffer + sidecar metadata strategy compatible with the WASI component ABI:

```wit
record transfer-result {
    data:    list<u8>,           // flat: pkt0 stride | pkt1 stride | ...
    packets: list<iso-packet>,   // empty for non-iso; one entry per iso packet
}

record iso-packet {
    actual-length: u32,
    status:        iso-packet-status,
}
```

![ISO flat-buffer strategy](../diagrams/iso_flatbuffer.svg)

The guest reconstructs per-packet views in O(N):

```rust
let mut offset = 0;
for pkt in &result.packets {
    let payload = &result.data[offset..offset + pkt.actual_length as usize];
    if pkt.status == IsoPacketStatus::Success { /* parse UVC header, append frame … */ }
    offset += stride;    // stride = max packet size, NOT actual_length
}
```

Why not `list<list<u8>>`? Nested growable lists aren't reliably supported in the stable component-model canonical ABI. A flat buffer means exactly one ABI memcpy per transfer. See [implementation.md §2](./implementation.md#2-isochronous-transfer-api) for the full rationale and the other rejected alternatives.

---

## 3. Capability-Based Security Model

![Capability model](../diagrams/capability_model.svg)

### 3.1 Allow-list

At startup, the host takes an explicit allow-list of `VendorID:ProductID` pairs:

```bash
sudo usb-wasi-host -c webcam.wasm \
    --use-allow-list \
    -d 046d:094c \   # Logitech Brio 100
    -d 054c:0ce6     # PS5 DualSense
```

This populates the runtime `AllowedUSBDevices` enum, checked on every device enumeration. Devices outside the list are invisible to the guest, filtered before any handle reaches the `ResourceTable`.

Two modes are supported:

```rust
pub enum AllowedUSBDevices {
    Allowed(Vec<USBDeviceIdentifier>),  // strict allow-list (with --use-allow-list)
    Denied(Vec<USBDeviceIdentifier>),   // deny-list (default; -d entries are blocked)
}
```

### 3.2 Comparison with container approaches

| Mechanism | Granularity | Bypass surface |
|-----------|-------------|----------------|
| Docker `--device=/dev/bus/usb/N/M` | Bus address, kernel-renumbered | Container can issue arbitrary transfers, enumerate via sysfs |
| Docker `--privileged` | Whole host | Full kernel access |
| WASI-USB allow-list | VID:PID per guest | Guest has no `ioctl`, no `open("/dev/...")`, no `libusb_init`; only the WIT surface is exposed |

A compromised guest can't enumerate beyond its allow-list because the Wasm sandbox has no system call that reaches the host USB stack directly. The only attack surface is the WIT world declaration.

### 3.3 Known limitations

**VID:PID spoofing**: a malicious device claiming `046d:094c` will pass the filter. Hardware-level attestation (USB Authentication Spec, TPM-backed identity) is complementary but out of scope.

**Per-endpoint policy**: once a device is opened, the guest can claim any interface and submit any transfer. A finer capability model (per-endpoint, per-class) is a natural extension.

---

## 4. Host Runtime

The host is a single Rust binary built from four source files:

| File | Lines | Role |
|------|------:|------|
| `main.rs` | ~975 | WIT method implementations, CLI, transfer callback, Wasmtime setup |
| `usb_backend.rs` | 545 | `HostUsbBackend` trait + `LibusbBackend` implementation |
| `instrument.rs` | 182 | Per-call duration + Linux ctx-switch tracing |
| `host.rs` | 309 | Generated WIT bindings (do not edit) |

### 4.1 `MyState`: the Wasmtime store data

```rust
struct MyState {
    table: ResourceTable,                    // owns all USB resources
    ctx: WasiCtx,                            // standard WASI capabilities (stdio, fs)
    allowed_usbdevices: AllowedUSBDevices,   // capability filter
    backend: Box<dyn HostUsbBackend>,        // pluggable USB backend
}
```

Every WIT method receives `&mut MyState`. The `table` is the single source of truth for resource lifetimes; the `backend` is the only path to the OS USB stack.

### 4.2 Backend abstraction

The `HostUsbBackend` trait separates what USB operations exist from how they're implemented. It is a refactor of Leroy's host: the libusb FFI that was inlined in `main.rs` now lives behind the trait, in a single `LibusbBackend` implementation. Every OS-level call goes through the trait, and the host never references `libusb1_sys` outside that impl. The trait leaves room for an alternative backend (a mock for testing, or a future `RusbBackend`), though only `LibusbBackend` is currently implemented.

Note that the thesis's libusb-vs-rusb comparison is not made by swapping this host backend: the host always runs `LibusbBackend`. That comparison happens one layer up, in the guest binding (rusb-wasi versus libusb-wasi), so the host backend stays constant across all benchmark conditions.

### 4.3 Resource tables and lifecycle

Three resource types live in `MyState::table`:

```
UsbDevice         // raw *libusb_device + ref-counted via libusb_ref_device
UsbDeviceHandle   // *libusb_device_handle from libusb_open
UsbTransfer       // *libusb_transfer + buffer + tokio receiver + iso results
```

Each has a `Drop` impl that handles the unsafe cleanup (`libusb_unref_device`, `libusb_close`, `libusb_free_transfer`). The Drop impls are the only place OS-level resources are released. The `UsbTransfer::Drop` is the most subtle, because three distinct states must be handled correctly; see [implementation.md §3.2](./implementation.md#32-the-three-state-drop).

---

## 5. Async Transfers: The Tokio Oneshot Pattern

*Implemented by Robbe Leroy (2025).*

USB transfers are inherently asynchronous: `libusb_submit_transfer` queues the transfer and returns immediately; completion is signalled later via a C callback fired from libusb's event thread. The bridge to Wasmtime's async runtime uses a Tokio oneshot channel per transfer.

![Transfer lifecycle](../diagrams/transfer_lifecycle.svg)

### 5.1 Three concurrent domains

| Thread | Owned by | Role |
|--------|----------|------|
| Tokio main thread | `#[tokio::main]` | Runs Wasmtime, executes WIT methods |
| libusb event thread | `LibusbBackend::init()` | Loops on `libusb_handle_events_timeout_completed()` (20 ms) |
| C callback (`transfer_callback`) | libusb event thread | Reads completion data, sends through oneshot |

The libusb event thread is a long-lived `std::thread::spawn` started once at host init, with no async runtime. The C callback runs on this thread, constructs a `Result<Vec<u8>, LibusbError>` from the libusb status, and fires it through the Tokio oneshot sender. The Tokio main thread, waiting on `receiver.await` inside `await_transfer`, wakes up and completes the WIT method.

### 5.2 Memory ownership in the callback

The C callback receives a `*mut TransferContext` via the libusb `user_data` pointer. The `TransferContext` is constructed with `Box::into_raw` in `submit_transfer` (transferring ownership to libusb) and reclaimed with `Box::from_raw` in the callback (transferring it back to Rust). The Box drops at the end of the callback, freeing the buffer, consuming the sender, and decrementing the `Arc` refcounts.

---

## 6. Hotplug

`enable-hotplug` registers a libusb callback that pushes events onto a global `Mutex<VecDeque<(Event, Info, UsbDevice)>>`. The guest polls with `poll-events`, which drains the queue.

The WIT definition uses `flags event { arrived; left; }`, a bitflag value, not an opaque resource. A list of events fits the flag-based model naturally. A pollable stream interface would require a host-side bridging future per registration, adding complexity for no measurable benefit at the guest API level.

The allow-list is consulted inside the C callback so disallowed devices never enter the queue.

---

## 7. Instrumentation

*Contribution of this thesis (Sibren Wieme, 2026).*

`instrument.rs` provides a RAII `CallTrace` guard that, on drop, logs the wall-clock duration of the host method and (on Linux) voluntary/involuntary context switch deltas from `/proc/self/status`.

Activated via `RUST_LOG=wasi_usb_trace=info`. Used in the thesis evaluation to attribute overhead to specific WIT calls. See [implementation.md §4](./implementation.md#4-instrumentation--instrumentrs) for how it is used and why the fast path is essentially free when disabled.

---

## 8. Threading model: summary

| Concern | Strategy |
|---------|----------|
| Host concurrency model | Tokio multi-threaded runtime via `#[tokio::main]` |
| WIT method execution | `&mut MyState`, serial within a guest instance |
| USB completion delivery | Dedicated libusb event thread; oneshot channel into Tokio |
| Hotplug delivery | libusb callback → global `Mutex<VecDeque>` → guest polls |
| Per-transfer state | `Arc<AtomicBool>` shared between C-callback and Rust drop path |

Each `usb-wasi-host` invocation runs one guest. Multi-tenant setups run multiple host processes with separate allow-lists. Running multiple guests in a single process would complicate the capability model without gaining anything over just using separate OS processes.

---

## See also

- [implementation.md](./implementation.md): concrete contributions, design decisions, bug fixes
- [compiling.md](./compiling.md): how to build host + guests + benchmarks
- [benchmarking.md](./benchmarking.md): C1-C5 evaluation matrix
- [thesis.md](./thesis.md): chapter mapping and research framing
