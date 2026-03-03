# Compilatie van libusb- en rusb-workloads naar WebAssembly

## Overzicht

Om USB-functionaliteit aan te bieden binnen een WebAssembly-omgeving, dient de volledige keten — van applicatiecode tot systeemaanroepen — aangepast te worden aan het WASI-componentmodel. De architectuur ziet er als volgt uit:

```
Applicatiecode → rusb → libusb-wasi (guest) → WASI-USB interface → host-implementatie → syscalls
```

Een workload roept `rusb`-functies aan (bijvoorbeeld `DeviceList::new()`). `rusb` vertaalt deze naar `libusb` C-functies via FFI. In plaats van de standaard `libusb`-bibliotheek — die rechtstreeks met het besturingssysteem communiceert — wordt gelinkt tegen `libusb-wasi`: een aangepaste versie die WASI-USB interfaceaanroepen genereert. Deze aanroepen worden door de host-runtime onderschept en vertaald naar daadwerkelijke USB-systeemaanroepen.

---

## libusb-wasi: de guest-implementatie

Aan `libusb-wasi` zijn in het kader van dit werk geen codewijzigingen aangebracht. Het betreft de implementatie van Leroy, waarvan hieronder de werking beschreven wordt.

### WASI-backend

Standaard beschikt `libusb` over platform-specifieke backends voor Linux (`linux_usbfs`), macOS (`darwin`), Windows (`windows`), enzovoort. In `libusb-wasi` is een nieuwe backend toegevoegd: `wasi_usb.c`. Deze backend implementeert dezelfde interne `libusb`-interface, maar vervangt OS-specifieke systeemaanroepen door functies gedefinieerd in de WASI-USB WIT-interface.

### cguest-bindings

De brug tussen `wasi_usb.c` en de WASI-USB interface wordt gevormd door de zogenaamde *cguest-bindings*. Deze worden gegenereerd door `wit-bindgen` op basis van de WIT-definitie en bestaan uit twee objectbestanden:

| Bestand | Inhoud |
|---------|--------|
| `cguest.o` | Gegenereerde C-code die de WASI-USB functies aanroept |
| `cguest_component_type.o` | Metadata: een `component-type:cguest` custom section die de volledige WIT-world beschrijft |

### Build-product

Het eindresultaat is een statisch archief (`libusb-wasi.a`) dat alle objectbestanden combineert:

```
libusb-wasi.a
├── core.o              — libusb-kern (device management, event loop)
├── descriptor.o        — USB-descriptor parsing
├── hotplug.o           — Hotplug-ondersteuning
├── io.o                — I/O-operaties
├── strerror.o          — Foutmeldingen
├── sync.o              — Synchrone transfers
├── wasi_usb.o          — WASI-backend (vervangt OS-specifieke backends)
└── cguest.o            — Gegenereerde WASI-USB bindings
```

Dit archief wordt samengesteld door de standaard build-output van `libusb` te combineren met het gegenereerde `cguest_component_type.o`:

```sh
cp libusb/.libs/libusb-1.0.a libusb-wasi.a
ar r libusb-wasi.a /path/to/cguest_component_type.o
```

### Beperking

De huidige implementatie ondersteunt uitsluitend synchrone transfers. Asynchrone transfers vereisen threading-ondersteuning, die op het moment van schrijven niet gestandaardiseerd is binnen WASI/Wasmtime.

### Reactor-model

WASI-programma's maken gebruik van het reactor-model in plaats van het command-model. Dit houdt in dat er geen `main()`-functie aanwezig is, maar een geëxporteerde functie met de signatuur:

```c
bool exports_wasi_cli_run_run(void);
```

Bij compilatie wordt de vlag `-mexec-model=reactor` meegegeven aan de compiler.

---

## rusb-wasi: cross-compilatie van Rust naar WebAssembly

`rusb` is een Rust-wrapper rond `libusb`. De crate maakt gebruik van `libusb1-sys` als FFI-bindingcrate om de C-functies van `libusb` beschikbaar te maken in Rust. Om `rusb` te compileren naar WebAssembly — gelinkt tegen `libusb-wasi` — zijn geen wijzigingen aan de broncode van `rusb` of `libusb1-sys` nodig. De aanpassingen bevinden zich uitsluitend in de *build-configuratie*.

### Probleem

`libusb1-sys` gebruikt `pkg-config` om de systeembibliotheek `libusb` te lokaliseren. Bij cross-compilatie naar WebAssembly dient `pkg-config` omgeleid te worden naar de WASI-gecompileerde `libusb-wasi.a` in plaats van de host-systeembibliotheek.

### Oplossing: pkg-config sysroot

Conform de [cross-compilatiedocumentatie van rusb](https://github.com/a1ien/rusb#cross-compiling) wordt een sysroot-structuur aangemaakt die de WASI-build van `libusb` bevat:

```
wasi-sysroot/
└── usr/
    ├── lib/
    │   ├── libusb-1.0.a             → symlink naar libusb-wasi/libusb-wasi.a
    │   ├── cguest_component_type.o     (component-type metadata)
    │   └── pkgconfig/
    │       └── libusb-1.0.pc           (pkg-config configuratie)
    └── include/
        └── libusb-1.0/
            └── libusb.h             → symlink naar libusb-wasi/libusb/libusb.h
```

De `pkg-config`-omgevingsvariabelen worden ingesteld volgens het patroon beschreven in de Autotools Mythbuster-gids, aangepast voor Rust:

```sh
export PKG_CONFIG_DIR=
export PKG_CONFIG_LIBDIR=${SYSROOT}/usr/lib/pkgconfig
export PKG_CONFIG_SYSROOT_DIR=${SYSROOT}
export PKG_CONFIG_ALLOW_CROSS=1
export LIBUSB_STATIC=1
```

Wanneer het build-script van `libusb1-sys` vervolgens `pkg-config` aanroept, worden de include- en library-paden naar de WASI sysroot gericht. Het build-systeem linkt daardoor tegen `libusb-wasi.a` zonder zich bewust te zijn van het verschil met een native installatie.

### Component-type metadata

Bij het gebruik van het `wasm32-wasip2` compilatiedoel maakt Rust gebruik van `wasm-component-ld` als linker. Deze tool voert twee stappen uit:

1. Alle objectbestanden worden gelinkt tot een core WebAssembly-module.
2. De module wordt automatisch omgezet naar een WASI-component.

Stap 2 faalt indien de module imports bevat voor interfaces die `wasm-component-ld` niet kent — in dit geval `component:usb/transfers@0.2.1`, de WASI-USB interface. De oplossing bestaat uit het meelinken van `cguest_component_type.o`, dat een custom section `component-type:cguest` bevat met een beschrijving van de volledige WIT-world. Dit wordt gerealiseerd via een `build.rs`-script:

```rust
use std::path::PathBuf;

fn main() {
    let sysroot = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("wasi-sysroot/usr/lib");
    println!("cargo:rustc-link-arg={}",
        sysroot.join("cguest_component_type.o").display());
}
```

Door dit objectbestand op te nemen in het linkproces beschikt `wasm-component-ld` over de benodigde informatie om de custom WASI-USB imports correct te resolven en de componentisatie automatisch uit te voeren.

### Workload-structuur

Het workload-project wordt geconfigureerd als `cdylib` (C-compatible dynamic library) om het reactor-model te ondersteunen:

```toml
[lib]
crate-type = ["cdylib"]

[dependencies]
rusb = { path = "../rusb-wasi" }
```

Het vereiste ingangspunt is:

```rust
#[unsafe(no_mangle)]
pub extern "C" fn exports_wasi_cli_run_run() -> bool {
    // Workload-logica
    true
}
```

Hierbij zorgt `#[unsafe(no_mangle)]` ervoor dat de functienaam ongewijzigd blijft in het gecompileerde binaire bestand, en `extern "C"` garandeert het gebruik van de C-aanroepconventie, noodzakelijk voor WASI-interoperabiliteit.

### Compilatie

Het volledige compilatieproces wordt uitgevoerd met een enkel commando:

```sh
cargo build --target wasm32-wasip2 --release
```

Dit produceert direct een uitvoerbare WASI-component. Er zijn geen aanvullende stappen met `wasm-tools` nodig — `wasm-component-ld` voert de componentisatie automatisch uit op basis van de `component-type:cguest` metadata.

---

## Samenvatting

| Aspect | libusb-wasi | rusb-wasi |
|--------|-------------|-----------|
| Auteur | Leroy | Fork van a1ien/rusb |
| Codewijzigingen | Niet van toepassing (bestaand werk) | Één regel in `Cargo.toml` (workspace-configuratie) |
| Kernprincipe | Nieuwe WASI-backend voor libusb | Cross-compilatieconfiguratie via pkg-config |
| Build-product | `libusb-wasi.a` (statisch archief) | `.wasm`-component (direct uitvoerbaar) |
| Sleutelbestand | `wasi_usb.c` (WASI-backend) | `build.rs` (linkt `cguest_component_type.o`) |
| Compilatiedoel | `wasm32-wasip2` (via WASI SDK) | `wasm32-wasip2` (via Cargo en pkg-config) |

---

## Voorbeelden

Naast de `read_device` workload (die probeert te lezen van een Mass Storage device), zijn er ook `lsusb`-voorbeelden beschikbaar. Deze tonen de volledige hiërarchie van verbonden USB-apparaten (Device -> Config -> Interface -> Endpoint) zonder permissieproblemen te veroorzaken.

### Rust (`lsusb`)

De code bevindt zich in `rusb-wasi/examples/wasi-workload/examples/lsusb.rs`.

**Compilatie:**
```bash
# Stel eerst de PKG_CONFIG variabelen in zoals hierboven beschreven
cargo build --example lsusb --target wasm32-wasip2 --release
```

**Uitvoering:**
```bash
./wasi-usb-host --component-path rusb-wasi/examples/wasi-workload/target/wasm32-wasip2/release/examples/lsusb.wasm
```

### C (`lsusb`)

De code bevindt zich in `libusb-wasi/examples/lsusb.c`.

**Compilatie:**
Gebruik het `build.sh` script in `libusb-wasi/examples`:
```bash
cd libusb-wasi/examples
./build.sh
```
Dit genereert `lsusb.component.wasm`.

**Uitvoering:**
```bash
./wasi-usb-host --component-path libusb-wasi/examples/lsusb.component.wasm
```
