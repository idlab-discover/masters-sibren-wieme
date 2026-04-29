# Thesis Chapter Structure

## 1 Introduction

### 1.1 Context
Brief positioning of **WebAssembly** in the context of IoT and cyber-physical systems, with emphasis on why hardware access (USB, I2C, GPIO) and container security are problematic in these environments.

### 1.2 Motivation and Objective
Argumentation for why secure and portable USB access in WebAssembly is relevant for IoT/CPS, and a concrete formulation of the thesis objective (design, implementation, and evaluation of a USB framework for Wasm).

### 1.3 Scope
Delimitation of what this thesis covers and what it does not: focus on USB in WebAssembly (using WASI Preview 3 and WIT), limited attention to other buses (I2C/GPIO), and no general performance study of containers versus Wasm outside the USB domain.

### 1.4 Thesis Structure
Brief description of the content of each chapter, so the reader knows where to find context, problem statement, architecture, implementation, evaluation and conclusions.

> Note: keep the introduction as concise as possible — only the minimum context needed to understand the problem statement and objectives. In-depth background goes into chapter 2.

---

## 2 Background and Related Work

### 2.1 Cyber-Physical Systems and IoT
Definition and typical characteristics of CPS and IoT applications, focusing on timing requirements, reliability and security in real-time environments.

### 2.2 Container Technology in IoT
Overview of how containers are used today in embedded/IoT contexts, including advantages and limitations in terms of performance, security, footprint and hardware access.

### 2.3 WebAssembly and WASI (Preview 3)
Core concepts of WebAssembly, sandboxing and WASI, including the component model and the relevant aspects of WASI Preview 3 for system and hardware interfaces.

### 2.4 USB, libusb, rusb and WASI-USB
Fundamentals of USB (host, endpoints, transfers, bulk/interrupt/isochronous), and an overview of libusb, rusb and the existing WASI-USB work on which this thesis builds.

### 2.5 WebAssembly for IoT and Hardware Access
Discussion of existing literature and projects using WebAssembly as an alternative or complement to traditional containers in IoT scenarios, with emphasis on hardware communication (USB/I2C/GPIO) and security isolation.

### 2.6 Synthesis
Summary of the key insights from this chapter, focusing on current problems with sensor and USB communication in containers, and how this motivates the problem statement and design choices in subsequent chapters.

---

## 3 Problem Statement

### 3.1 Current Situation
Description of how IoT software is currently built and deployed (native C/C++, containers, vendor-specific tooling) and what problems arise regarding hardware access, maintainability and portability.

### 3.2 Shortcomings of Existing Solutions
Analysis of concrete gaps: limited portability across heterogeneous IoT platforms, inadequate security isolation around USB drivers, resource usage and operational complexity.

### 3.3 Need for a New Framework
Motivation for a lightweight, secure and portable framework for USB hardware access based on WebAssembly and WASI, fitting the IoT/CPS landscape.

### 3.4 Goal and Positioning of the Proposed Framework
Clear formulation of the framework's role: USB access for Wasm modules with capability-based isolation, and positioning relative to existing solutions such as containers and prior WASI-USB work.

> Note: focus here on the USB-in-Wasm problem. Refer only briefly to why Wasm is relevant — the reader should already understand this from chapter 2.

---

## 4 System Architecture

### 4.1 Framework Overview
High-level overview of the architecture: host runtime, WebAssembly modules (guests), USB backends (libusb, rusb) and the capability model.

### 4.2 Security and Capability Model
Description of how capabilities are granted, what access rights modules receive, how authorisation and isolation work, and how this fits an IoT threat model.

### 4.3 WIT Interfaces and WASI Preview 3
Description of the structure of the WIT interfaces (USB API, capability interfaces, configuration), and the design choices made to remain compatible with WASI Preview 3 and existing WASI-USB proposals.

### 4.4 Host Architecture
Architecture of the host runtime: abstraction layer to the OS, integration with libusb/rusb, configuration and logging facilities, backend plugging and capability filters.

### 4.5 Multithreading Design
Conceptual multithreading model within the framework: thread model, concurrency strategy (e.g. per-device threads, thread pool), and expected impact on latency, throughput and CPU usage.

### 4.6 Guest Architecture and Use Cases
Types of guest modules (proof-of-concepts, benchmarks, camera/CV pipeline) and how they communicate with the host runtime via the WIT interfaces and the capability model.

### 4.7 Architectural Reflection
Brief reflection on how the chosen architecture addresses the previously described problems around USB access, security and portability.

---

## 5 Implementation

### 5.1 Project and Code Structure
Overview of repositories, directory structure, build scripts, programming languages used and tooling (e.g. cargo, CMake).

### 5.2 WIT Interface Implementation
More concrete elaboration of the WIT interfaces described in chapter 4: definition of the USB API, capability interfaces and integration with existing WASI-USB definitions and WASI Preview 3 tooling.

### 5.3 libusb Backend Integration
Implementation of the libusb backend in the host runtime, with reference to the existing work, applied modifications, cleanup and additional functionality (logging, error mapping, configuration).

### 5.4 rusb Backend Integration
Description of the rusb backend, architectural differences with respect to libusb within the same framework, and any specific problems and solutions in the implementation.

### 5.5 Host Runtime Implementation
Key modules of the host runtime: capability filters, mapping of WIT calls to backend calls, configuration handling, logging, error handling and integration with the chosen Wasm runtime.

### 5.6 Multithreading in the Implementation
Concrete translation of the multithreading design into code: concurrency primitives used, thread pools, synchronisation mechanisms and any platform-specific considerations.

---

## 6 Use Cases and Experimental Setup

### 6.1 Evaluation Goals
Definition of what the evaluation should demonstrate: performance impact, resource usage, suitability for cyber-physical workloads and relevant security properties.

### 6.2 Proof-of-Concept Guest Applications
Description of the proof-of-concepts (pacman, enumerate-usb, Xbox controller, …) and their role in testing functionality and developer experience.

### 6.3 Camera and Computer Vision Pipeline
Description of the camera/CV demo as a representative cyber-physical workload: pipeline, dataflow and coupling to the USB framework.

### 6.4 Benchmark and Stress-Test Tools
Description of the USB 3.0 stress-test frameworks, microbenchmarks and supporting scripts used for performance and stress testing.

### 6.5 Experimental Setup

#### 6.5.1 Hardware Configuration
Description and table of the machines, USB devices, cameras and other relevant hardware used.

#### 6.5.2 Software Environment
Overview of OS and kernel versions, Wasm runtime, libusb/rusb versions, Docker versions, compiler options and configuration of the baselines.

#### 6.5.3 Workloads and Scenarios
Definition of the workloads (PoCs, benchmarks, camera/CV scenarios) in native, Docker and Wasm configurations.

---

## 7 Evaluation

### 7.1 Performance: Latency and Throughput

#### 7.1.1 Single-Threaded Baseline
Measurements of bulk latency and sequential throughput for USB I/O, comparing native, Docker and Wasm (libusb and rusb).

#### 7.1.2 Multithreaded Scenarios
Results for parallel transfers and multiple devices, including throughput scaling behaviour and CPU impact per number of threads.

### 7.2 Cyber-Physical Demos: Camera and Computer Vision

#### 7.2.1 Scenario and Metrics
Definition of the camera/CV pipeline and the metrics used (end-to-end latency, fps, CPU/memory).

#### 7.2.2 Results
Results of the camera and CV experiments in the different configurations (native, Docker, Wasm backends).

#### 7.2.3 Analysis
Interpretation of results with respect to real-time requirements in cyber-physical systems.

### 7.3 Resource Usage: CPU and Memory

#### 7.3.1 Measurement Setup
Description of how CPU and memory usage is measured, logged and processed.

#### 7.3.2 Results
Comparison of resource usage between native, Docker and Wasm, and between single- and multithreaded runs.

### 7.4 Security and Isolation Analysis

#### 7.4.1 Threat Model
Formal description of assumptions about attackers, threat scenarios and trust boundaries in IoT/CPS environments.

#### 7.4.2 Comparison with Baselines
Qualitative comparison of the capability model with native processes and Docker containers in terms of isolation and attacks on USB access.

#### 7.4.3 Scenario-Based Discussion
Concrete misuse scenarios (e.g. malicious USB device, compromised guest module) and how the framework protects against them or where vulnerabilities remain.

### 7.5 Summary Evaluation
Summary of the key quantitative and qualitative findings from the evaluation, linked to the evaluation goals from 6.1.

---

## 8 Discussion

### 8.1 Interpretation of Results
Overarching interpretation of the results from chapter 7 in relation to the original problem statement and research questions.

### 8.2 Implications for IoT and CPS Deployments
Discussion of what the findings mean for real IoT and cyber-physical deployments, with attention to typical use cases and limitations.

### 8.3 Trade-offs and Design Choices
Analysis of the key trade-offs (security vs performance, complexity vs flexibility) and critical reflection on the design choices made.

### 8.4 Limitations of the Work
Overview of the main limitations of the current implementation, evaluation and generalisability.

---

## 9 Conclusion and Future Work

### 9.1 Summary of Contributions
Concise summary of the core contributions of the thesis (architecture, implementation, evaluation, insights).

### 9.2 Main Conclusions
Short, clear formulation of the principal substantive conclusions in relation to the problem statement.

### 9.3 Proposals for Future Work
Concrete ideas for further development, additional experiments and possible impact on standardisation and industrial applications.

---

## 10 Societal Reflection

### 10.1 Impact on Security and Privacy
Reflection on how this type of technology affects security and privacy in IoT and CPS environments, including supply-chain and driver ecosystem concerns.

### 10.2 Ethical and Societal Considerations
Discussion of risks, responsibilities and broader societal context (e.g. dependency on closed-source runtimes, misuse of remote hardware access).

---

## 11 References
Standardised list of all sources used (articles, documentation, whitepapers, blogs, repositories), following the programme guidelines.

---

## 12 Appendices

### 12.1 Extended Benchmark Tables and Graphs
Detailed figures, additional graphs and tables summarised in the evaluation chapters.

### 12.2 Configuration Files and Scripts
Key configuration and script files for experiments, build environment and deployment.

### 12.3 WIT Definitions and Interface Fragments
Selected WIT fragments and other interface descriptions too extensive for the main text.

### 12.4 Additional Technical Details
Other technical details (diagrams, log fragments, device and test matrix) supporting reproducibility and further study.
