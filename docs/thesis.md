# Thesis - context, scope and chapter mapping

This document links the codebase to the master's thesis manuscript.
It's meant as a reference for three groups:

1. **Readers of the repo** who want to know which thesis chapter discusses
   a piece of code.
2. **The defense committee** who want to map claims in the manuscript to
   evidence in the source tree.
3. **Me** writing the remaining chapters and needing a quick overview of
   which docs cover which arguments.

The thesis manuscript itself lives under `Masterproef_Sibren_Overleaf/`
(gitignored, kept in sync with Overleaf).

---

## 1. Project framing

### Title
**Secure USB Access in WebAssembly: A Capability-Based Framework for
Cyber-Physical IoT**

### Author
Sibren Wieme - Master of Science in Computer Science Engineering,
Faculty of Engineering and Architecture, Ghent University, 2025-2026.

### Promotors and counsellors
- **Promotors**: Prof. Dr. Bruno Volckaert, Dr. Merlijn Sebrechts
- **Counsellors**: ing. Michiel Vankenhove, Friedrich Vandenberghe

### Position in the WASI-USB programme
This thesis is the fourth in a sequence of master's theses on USB-over-WASI
at IDLab Discover:

| # | Author | Year | Contribution |
|---|--------|------|--------------|
| 1 | Wouter Hennen | 2024 | Initial WIT-based host runtime; control + bulk transfers |
| 2 | Friedrich Vandenberghe | 2024 | WASI-I²C (parallel hardware bus) |
| 3 | Robbe Leroy | 2025 | `libusb-wasi.a` - WASI backend inside libusb |
| **4** | **Sibren Wieme** | **2026** | **Isochronous extension; backend abstraction; UVC CPS workload; C1-C5 benchmark evaluation** |

The framework also draws on the broader cyber-physical WebAssembly research
of Van Kenhove et al.

---

## 2. Research objectives

The thesis has four main objectives:

1. **Architecture**. Design a system architecture integrating a WebAssembly
   host runtime, guest modules, and multiple USB backends under a
   capability-oriented security model suitable for IoT and CPS deployments.
2. **Implementation**. Implement WASI-USB compatible interfaces and
   backends, reusing and extending prior work, including backends based on
   `libusb` and `rusb`.
3. **Use cases**. Develop representative guest applications and benchmarks,
   including a UVC camera pipeline, exercising both single-threaded and
   high-bandwidth USB communication.
4. **Evaluation**. Evaluate performance (latency and throughput), resource
   usage (CPU and memory), and security/isolation properties against
   native and container-based baselines.

---

## 3. Contributions claimed

Five concrete contributions form the core of the thesis, each with code in
this repo and a corresponding section in the manuscript:

| # | Claim | Code | Manuscript section |
|---|-------|------|---------------------|
| 1 | Isochronous transfer API extending WIT with flat-buffer strategy | `wit/transfers.wit`, `usb-wasi-host/src/main.rs` (callback) | Ch 4 §4.3, Ch 5 §5.2 |
| 2 | Dual-backend host runtime via `HostUsbBackend` trait | `usb-wasi-host/src/usb_backend.rs` | Ch 4 §4.4, Ch 5 §5.3 |
| 3 | rusb→WASM cross-compile (no upstream forks) | `sysroot-wasi/`, `benchmarks/build-c4.sh` | Ch 5 §5.4 |
| 4 | UVC webcam CPS workload (entire UVC stack in Wasm) | `usb-wasi-guest/examples/webcam/` | Ch 6 §6.3, Ch 7 §7.2 |
| 5 | Five-condition (C1-C5) systematic benchmark evaluation | `benchmarks/`, `bench/run.sh`, `bench/analyze.py` | Ch 6 §6.4, Ch 7 §7.1 |

---

## 4. Documentation - chapter mapping

Per chapter, these are the docs to look at:

| Chapter | Title (LaTeX file) | Supporting docs |
|---------|-------------------|----------------|
| 1 | Introduction | This file (§1, §2) |
| 2 | Background and Related Work | This file (§1.5 prior work) |
| 3 | Problem Statement | [`architecture.md`](./architecture.md) §3 (capability vs containers) |
| 4 | System Architecture | [`architecture.md`](./architecture.md) §1-§7 |
| 5 | Implementation | [`implementation.md`](./implementation.md) §1-§7 |
| 6 | Use Cases & Experimental Setup | [`implementation.md`](./implementation.md) §7-§8, [`benchmarking.md`](./benchmarking.md) |
| 7 | Evaluation | [`benchmarking.md`](./benchmarking.md), [`implementation.md`](./implementation.md) §5 (instrumentation) |
| 8 | Discussion | [`architecture.md`](./architecture.md) §3.3 (limitations), [`implementation.md`](./implementation.md) §2 (rejected alternatives) |
| 9 | Conclusion and Future Work | This file (§3) |
| 10 | Societal Reflection | (manuscript only) |

### 4.1 Defense talking-point cheat sheet

| If asked … | Refer to |
|------------|----------|
| "Why a flat buffer for ISO?" | [`implementation.md`](./implementation.md) §2 - rejected alternatives |
| "Why a trait for the backend?" | [`implementation.md`](./implementation.md) §1 - design rationale |
| "How does rusb-wasi work without forking rusb?" | [`implementation.md`](./implementation.md) §6 - pkg-config pipeline |
| "What does the host actually do for UVC?" | [`implementation.md`](./implementation.md) §7 - "host has zero UVC code" |
| "How is WASI-USB stronger than `--device=/dev/bus/usb`?" | [`architecture.md`](./architecture.md) §3.2 - comparison table |
| "What broke and how was it fixed?" | [`implementation.md`](./implementation.md) §3 - three bug fixes with root causes |
| "How do you measure WASI overhead?" | [`implementation.md`](./implementation.md) §5 - `instrument.rs`; [`benchmarking.md`](./benchmarking.md) - methodology |
| "What does C1-C5 isolate?" | [`implementation.md`](./implementation.md) §8, [`benchmarking.md`](./benchmarking.md) |
| "Why a libusb event thread + tokio oneshot?" | [`architecture.md`](./architecture.md) §5 - three concurrent domains |

---

## 5. Thesis chapter outline (full structure)

Full chapter and section list, used as a writing checklist.

### Chapter 1 - Introduction
- 1.1 Context (CPS, IoT, hardware access in containers)
- 1.2 Motivation and Objective
- 1.3 Scope
- 1.4 Thesis Structure

### Chapter 2 - Background and Related Work
- 2.1 Cyber-Physical Systems and IoT
- 2.2 Container Technology in IoT
- 2.3 WebAssembly and WASI (Preview 3)
- 2.4 USB, libusb, rusb and WASI-USB
- 2.5 WebAssembly for IoT and Hardware Access
- 2.6 Synthesis

### Chapter 3 - Problem Statement
- 3.1 Current Situation
- 3.2 Shortcomings of Existing Solutions
- 3.3 Need for a New Framework
- 3.4 Goal and Positioning of the Proposed Framework

### Chapter 4 - System Architecture
- 4.1 Framework Overview → [`architecture.md` §1](./architecture.md#1-high-level-layering)
- 4.2 Security and Capability Model → [`architecture.md` §3](./architecture.md#3-capability-based-security-model)
- 4.3 WIT Interfaces and WASI Preview 3 → [`architecture.md` §2](./architecture.md#2-wit-interface-design)
- 4.4 Host Architecture → [`architecture.md` §4](./architecture.md#4-host-runtime)
- 4.5 Multithreading Design → [`architecture.md` §5](./architecture.md#5-async-transfers--the-tokio-oneshot-pattern), [§8](./architecture.md#8-threading-model--summary)
- 4.6 Guest Architecture and Use Cases → [`implementation.md` §7](./implementation.md#7-uvc-webcam-guest)
- 4.7 Architectural Reflection

### Chapter 5 - Implementation
- 5.1 Project and Code Structure → [README.md](../README.md)
- 5.2 WIT Interface Implementation → [`implementation.md` §2](./implementation.md#2-isochronous-transfer-api)
- 5.3 libusb Backend Integration → [`implementation.md` §1](./implementation.md#1-backend-abstraction--hostusbbackend-trait)
- 5.4 rusb Backend Integration → [`implementation.md` §6](./implementation.md#6-c4-cross-compile-pipeline)
- 5.5 Host Runtime Implementation → [`implementation.md` §3, §4](./implementation.md#3-resource-lifecycle-bug-fixes)
- 5.6 Multithreading in the Implementation → [`implementation.md` §4](./implementation.md#4-async-transfer--tokio-oneshot-pattern)

### Chapter 6 - Use Cases and Experimental Setup
- 6.1 Evaluation Goals → [`benchmarking.md` §1](./benchmarking.md)
- 6.2 Proof-of-Concept Guest Applications
- 6.3 Camera and Computer Vision Pipeline → [`implementation.md` §7](./implementation.md#7-uvc-webcam-guest)
- 6.4 Benchmark and Stress-Test Tools → [`benchmarking.md`](./benchmarking.md)
- 6.5 Experimental Setup
  - 6.5.1 Hardware Configuration
  - 6.5.2 Software Environment
  - 6.5.3 Workloads and Scenarios

### Chapter 7 - Evaluation
- 7.1 Performance: Latency and Throughput → [`benchmarking.md`](./benchmarking.md)
  - 7.1.1 Single-Threaded Baseline
  - 7.1.2 Multithreaded Scenarios
- 7.2 Cyber-Physical Demos → [`implementation.md` §7](./implementation.md#7-uvc-webcam-guest)
- 7.3 Resource Usage: CPU and Memory → [`implementation.md` §5](./implementation.md#5-instrumentation--instrumentrs)
- 7.4 Security and Isolation Analysis → [`architecture.md` §3](./architecture.md#3-capability-based-security-model)
- 7.5 Summary Evaluation

### Chapter 8 - Discussion
- 8.1 Interpretation of Results
- 8.2 Implications for IoT and CPS Deployments
- 8.3 Trade-offs and Design Choices → [`implementation.md` §2](./implementation.md#2-isochronous-transfer-api) (rejected alternatives)
- 8.4 Limitations of the Work → [`architecture.md` §3.3](./architecture.md#33-known-limitations)

### Chapter 9 - Conclusion and Future Work
- 9.1 Summary of Contributions → §3 above
- 9.2 Main Conclusions
- 9.3 Proposals for Future Work

### Chapter 10 - Societal Reflection
- 10.1 Impact on Security and Privacy
- 10.2 Ethical and Societal Considerations

### Chapters 11-12 - References, Appendices

---

## 6. Figures

The thesis manuscript references these figures, all of which have rendered
SVG and PlantUML sources in [`../diagrams/`](../diagrams/):

| Figure | Source | Used in |
|--------|--------|---------|
| High-level architecture | `host_guest_arch.puml` | Ch 4 §4.1 |
| Capability model | `capability_model.puml` | Ch 4 §4.2 |
| Transfer lifecycle | `transfer_lifecycle.puml` | Ch 5 §5.5 |
| ISO flat-buffer strategy | `iso_flatbuffer.puml` | Ch 5 §5.2 |
| C4 cross-compile pipeline | `crosscompile_pipeline.puml` | Ch 5 §5.4 |
| Webcam architecture (compact) | `webcam_arch_minimal.puml` | Ch 6 §6.3 |
| Webcam architecture (detailed) | `webcam_architecture.puml` | Appendix |

To re-render after edits:

```bash
plantuml -tsvg diagrams/*.puml
```

For LaTeX inclusion, also generate PDF:

```bash
plantuml -tpdf diagrams/*.puml
```

---

## 7. Acknowledgements

Code, advice and feedback gratefully received from:
- Warre Dujardin, Wouter Hennen, Robbe Leroy (prior thesis work)
- Friedrich Vandenberghe, Michiel Vankenhove (counsellors)
- Merlijn Sebrechts, Bruno Volckaert (promotors)

This work is partially supported by the **ELASTIC project**, funded by the
Smart Networks and Services Joint Undertaking (SNS JU) under the European
Union's Horizon Europe research and innovation programme, Grant Agreement
No 101139067.
