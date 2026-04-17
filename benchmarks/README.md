# WASI-USB Benchmarks

Deze suite evalueert de overhead van USB-toegang in WebAssembly (via de
WASI-USB component-model host) tegenover native uitvoering.

## Benchmarks

| Mode | Meet | Device | Sizes / Params | USB |
|------|------|--------|----------------|-----|
| `--latency` | Round-trip RTT bij kleine bulk-transfers | Pico 2 loopback CDC (`cafe:4002`) | 64, 128, 256, 512, 1024 B × 10 000 iteraties | USB 2.0 FS |
| `--throughput` | Sustained MB/s via MSC read/write | SanDisk USB 3.0 stick (`0781:5581`) | 8, 32, 128, 256, 512 MB × 10 runs | USB 3.0 SS |
| `--init` | Cold-start: init + enumerate + open + claim | Beide devices, 200 iteraties | per-fase timing | 2.0 FS + 3.0 SS |
| `--streams` | Validatie van `alloc_streams` + bulk-stream transfer | SanDisk USB 3.0 stick | `num_streams=16`, payload 1024 B | USB 3.0 SS |
| `--yolo` | Webcam→YOLO end-to-end + host CPU/RSS | Logitech Brio 100 | 30 s window | USB 2.0 HS |

Alle benchmarks loggen óók resource-usage (%CPU + RSS) van de host via een
achtergrond-poller → `results/resources_*.csv`.

## Varianten

Elke benchmark (behalve `--streams`, die WASI-only is) wordt gedraaid voor:

- `libusb_native` – native C met vanilla libusb
- `libusb_wasi`   – C component via `wasm32-wasip2`
- `rusb_native`   – native Rust met rusb
- `rusb_wasi`     – Rust component via `wasm32-wasip2`

Zo isoleer je per laag (native vs. WASM, C vs. Rust) waar de overhead
vandaan komt.

## Waarom deze mix

- **Latency op USB 2.0 FS** — kleine transfers maximaliseren het relatieve
  effect van één host-call per transfer, waardoor de WASM→host grens zichtbaar
  wordt.
- **Throughput op USB 3.0 SS** — grote transfers testen of de host-async
  pijplijn de bus-bandbreedte (~400 MB/s) kan vullen.
- **Init-tijd** — aparte fase-opsplitsing (init/enumerate/open/claim) laat
  zien welke libusb-call de WASM-grens het hardst raakt.
- **Streams-test** — valideert de USB 3.0 Bulk-Streams-ondersteuning die
  net is toegevoegd aan de `usb-wasm` host. De test rapporteert expliciet
  succes / `NOT_SUPPORTED` — niet elk device ondersteunt streams, maar de
  test bewijst dat de host-grens wel bereikt wordt.

## Directory-overzicht

- `c/` – native + WASI (libusb) workloads
- `rust/` – native + WASI (rusb) workloads
- `build_all.sh` – bouwt alle varianten in één keer
- `run_benchmarks.sh` – draait de gekozen modes en schrijft CSV's
- `plot.py` – genereert de figuren voor de thesis (boxplot + KDE, per-fase)

## Gebruik

```bash
./build_all.sh                              # eenmalig
sudo ./run_benchmarks.sh --all              # ~45 minuten
python3 plot.py                             # genereert results/plot_*.png
```

Of gericht:
```bash
sudo ./run_benchmarks.sh --latency
sudo ./run_benchmarks.sh --throughput
sudo ./run_benchmarks.sh --init
sudo ./run_benchmarks.sh --streams
```

## Resultaten

CSV's komen in `results/`:
- `rtt_results_latency_<variant>_<size>.csv`
- `throughput_results_<variant>_<MB>MB.csv`
- `init_results_<variant>_<device_label>.csv`
- `resources_<bench>_<variant>_<device>_<size>.csv` – timestamp, %CPU, RSS
- `streams_test_<device_label>.log`
- `yolo_latency.csv`, `yolo_resources.csv`
