# Structuur van de masterproef

## 1 Inleiding

### 1.1 Context
Korte situering van **WebAssembly** in de context van IoT en cyber‑physical systemen, met nadruk op waarom hardwaretoegang (USB, I2C, GPIO) en container security hier een probleem vormen.

### 1.2 Motivatie en doelstelling
Argumentatie waarom veilige en portable USB‑toegang in WebAssembly relevant is voor IoT/CPS, en formulering van de concrete doelstelling van de masterproef (ontwerp, implementatie en evaluatie van een USB‑raamwerk voor Wasm).

### 1.3 Scope van de masterproef
Afbakening van wat deze thesis wel en niet behandelt: focus op USB in WebAssembly (met WASI Preview 3 en WIT), beperkte aandacht voor andere bussen (I2C/GPIO) en geen algemene performance‑studie van containers versus Wasm buiten het USB‑domein.

### 1.4 Structuur van de thesis
Korte beschrijving van de inhoud van elk hoofdstuk, zodat de lezer weet waar context, probleemstelling, architectuur, implementatie, evaluatie en conclusies terug te vinden zijn.

> Opmerking: houd de inleiding zo beknopt mogelijk; enkel de minimale context om probleemstelling en doelstellingen te begrijpen. Verdiepende achtergrond gaat naar hoofdstuk 2.

---

## 2 Achtergrond en gerelateerd werk

### 2.1 Cyber‑physical systemen en IoT
Definitie en typische eigenschappen van CPS en IoT‑toepassingen, met focus op timingvereisten, betrouwbaarheid en veiligheid in real‑time omgevingen.

### 2.2 Containertechnologie in IoT
Overzicht van hoe containers vandaag gebruikt worden in embedded/IoT‑context, inclusief voordelen en beperkingen op vlak van performantie, security, footprint en hardwaretoegang.

### 2.3 WebAssembly en WASI (Preview 3)
Kernconcepten van WebAssembly, sandboxing en WASI, inclusief het component model en de relevante aspecten van WASI Preview 3 voor systeem‑ en hardware‑interfaces.

### 2.4 USB, libusb, rusb en WASI‑USB
Basisconcepten rond USB (host, endpoints, transfers, bulk/interrupt/isochronous), en een overzicht van libusb, rusb en het bestaande WASI‑USB‑werk waarop deze thesis verder bouwt.

### 2.5 WebAssembly voor IoT en hardwaretoegang
Bespreking van bestaande literatuur en projecten die WebAssembly inzetten als alternatief of aanvulling op klassieke containers in IoT‑scenario’s, met nadruk op hardwarecommunicatie (USB/I2C/GPIO) en security‑isolatie.

### 2.6 Synthese
Samenvatting van de belangrijkste inzichten uit dit hoofdstuk, met focus op de huidige problemen bij sensor‑ en USB‑communicatie in containers, en hoe dit de probleemstelling en ontwerpkeuzes in de volgende hoofdstukken motiveert.

---

## 3 Probleemstelling

### 3.1 Bestaande situatie
Beschrijving van hoe IoT‑software vandaag gebouwd en uitgerold wordt (native C/C++, containers, vendor‑specifieke tooling) en welke problemen opduiken bij hardwaretoegang, onderhoudbaarheid en portabiliteit.

### 3.2 Tekortkomingen in bestaande oplossingen
Analyse van concrete hiaten: beperkte portabiliteit over heterogene IoT‑platformen, gebrekkige security‑isolatie rond USB‑drivers, resourcegebruik en operationele complexiteit.

### 3.3 Nood aan een nieuw raamwerk
Motivatie voor een lichtgewicht, veilig en portable raamwerk voor USB‑hardwaretoegang gebaseerd op WebAssembly en WASI, passend in het IoT/CPS‑landschap.

### 3.4 Doel en positionering van het voorgestelde raamwerk
Duidelijke formulering van de rol van het raamwerk: USB‑toegang voor Wasm‑modules met capability‑gebaseerde isolatie, en positionering ten opzichte van bestaande oplossingen zoals containers en het eerdere WASI‑USB‑werk.

> Opmerking: focus hier op het USB‑in‑Wasm probleem. Verwijs slechts heel kort naar waarom Wasm relevant is; op dit punt moet de lezer dat al begrijpen uit hoofdstuk 2.

---

## 4 Systeemarchitectuur

### 4.1 Overzicht van het raamwerk
High‑level overzicht van de architectuur: host‑runtime, WebAssembly‑modules (guests), USB‑backends (libusb, rusb) en het capability‑model.

### 4.2 Security‑ en capability‑model
Beschrijving van hoe capabilities worden toegekend, welke toegangsrechten modules krijgen, hoe autorisatie en isolatie werken, en hoe dit past in een IoT‑dreigingsmodel.

### 4.3 WIT‑interfaces en WASI Preview 3
Beschrijving van de structuur van de WIT‑interfaces (USB‑API, capability‑interfaces, configuratie), en de gemaakte ontwerpkeuzes om compatibel te blijven met WASI Preview 3 en bestaande WASI‑USB‑voorstellen.

### 4.4 Host‑architectuur
Architectuur van de host‑runtime: abstractielaag naar het OS, integratie met libusb/rusb, configuratie‑ en loggingfaciliteiten, plugging van backends en capability‑filters.

### 4.5 Multithreading‑ontwerp
Conceptueel multithreading‑model binnen het raamwerk: thread‑model, concurrency‑strategie (bijv. per‑device threads, thread‑pool), en verwachte impact op latency, throughput en CPU‑gebruik.

### 4.6 Guest‑architectuur en use‑cases
Typen guest‑modules (proof‑of‑concepts, benchmarks, camera/CV‑pipeline) en hoe zij communiceren met de host‑runtime via de WIT‑interfaces en het capability‑model.

### 4.7 Samenvattende architectuurbeschouwing
Korte reflectie over hoe de gekozen architectuur de eerder geschetste problemen rond USB‑toegang, security en portabiliteit aanpakt.

---

## 5 Implementatie

### 5.1 Project‑ en code‑structuur
Overzicht van repositories, mappenstructuur, build‑scripts, gebruikte programmeertalen en tooling (bijv. cargo, CMake, containerbestanden).

### 5.2 Implementatie van WIT‑interfaces
Concretere uitwerking van de in hoofdstuk 4 beschreven WIT‑interfaces: definitie van de USB‑API, capability‑interfaces en integratie met de bestaande WASI‑USB‑definities en WASI Preview 3 tooling.

### 5.3 Integratie van libusb‑backend
Implementatie van de libusb‑backend in de host‑runtime, met verwijzing naar het bestaande werk, aangebrachte aanpassingen, opschoning en extra functionaliteit (logging, error‑mapping, configuratie).

### 5.4 Integratie van rusb‑backend
Beschrijving van de rusb‑backend, architecturale verschillen ten opzichte van libusb binnen hetzelfde raamwerk, en eventuele specifieke problemen en oplossingen in de implementatie.

### 5.5 Host‑runtime implementatie
Belangrijkste modules van de host‑runtime: capability‑filters, mapping van WIT‑calls naar backend‑calls, configuratie‑handling, logging, foutafhandeling en integratie met de gekozen Wasm‑runtime.

### 5.6 Multithreading in de implementatie
Concrete vertaling van het multithreading‑ontwerp naar code: gebruikte concurrency‑primitieven, thread‑pools, synchronisatie‑mechanismen en eventuele platform‑specifieke aandachtspunten.

---

## 6 Use‑cases en experimentele opzet

### 6.1 Evaluatiedoelen
Definitie van wat de evaluatie moet aantonen: performantie‑impact, resourcegebruik, geschiktheid voor cyber‑physical workloads en relevante security‑eigenschappen.

### 6.2 Proof‑of‑concept guest‑applicaties
Beschrijving van de proof‑of‑concepts (pacman, enumerate‑usb, Xbox‑controller, …) en hun rol in het testen van functionaliteit en gebruikservaring.

### 6.3 Camera‑ en Computer Vision‑pipeline
Beschrijving van de camera/CV‑demo als representatieve cyber‑physical workload: pipeline, dataflow en koppeling aan het USB‑raamwerk.

### 6.4 Benchmark‑ en stresstesttools
Beschrijving van de USB 3.0 stresstestframeworks, microbenchmarks en ondersteunende scripts die gebruikt worden voor performantie‑ en stresstesten.

### 6.5 Experimentele opzet

#### 6.5.1 Hardwareconfiguratie
Beschrijving en tabel van de gebruikte machines, USB‑apparaten, camera’s en overige relevante hardware.

#### 6.5.2 Softwareomgeving
Overzicht van OS‑ en kernelversies, Wasm‑runtime, libusb/rusb‑versies, Docker‑versies, compileropties en configuratie van de baselines.

#### 6.5.3 Workloads en scenario’s
Definitie van de workloads (PoC’s, benchmarks, camera/CV‑scenario’s) in native, Docker en Wasm‑configuraties.

---

## 7 Evaluatie

### 7.1 Performance: latency en throughput

#### 7.1.1 Single‑threaded baseline
Metingen van bulk‑latency en sequential throughput voor USB‑I/O, met vergelijking tussen native, Docker en Wasm (libusb en rusb).

#### 7.1.2 Multithreaded scenario’s
Resultaten voor parallelle transfers en meerdere apparaten, inclusief throughput‑schaalgedrag en CPU‑impact per aantal threads.

### 7.2 Cyber‑physical demo’s: camera en Computer Vision

#### 7.2.1 Scenario en metrieken
Definitie van de camera/CV‑pipeline en de gebruikte metrieken (end‑to‑end latency, fps, CPU/memory).

#### 7.2.2 Resultaten
Resultaten van de camera‑ en CV‑experimenten in de verschillende configuraties (native, Docker, Wasm‑backends).

#### 7.2.3 Analyse
Interpretatie van de resultaten met betrekking tot real‑time vereisten in cyber‑physical systemen.

### 7.3 Resourcegebruik: CPU en geheugen

#### 7.3.1 Meetopzet
Beschrijving van hoe CPU‑ en geheugenverbruik gemeten, gelogd en verwerkt worden.

#### 7.3.2 Resultaten
Vergelijking van resourcegebruik tussen native, Docker en Wasm, en tussen single‑ en multithreaded runs.

### 7.4 Security‑ en isolatie‑analyse

#### 7.4.1 Threat model
Formele omschrijving van de aannames over aanvallers, dreigingsscenario’s en trust boundaries in IoT/CPS‑omgevingen.

#### 7.4.2 Vergelijking met baselines
Kwalitatieve vergelijking van het capability‑model met native processen en Docker‑containers op vlak van isolatie en aanvallen op USB‑toegang.

#### 7.4.3 Scenario‑gebaseerde bespreking
Concrete misbruikscenario’s (bijv. kwaadwillige USB‑device, gecompromitteerde guest‑module) en hoe het raamwerk daartegen beschermt of waar nog zwaktes zitten.

### 7.5 Samenvattende evaluatie
Samenvatting van de belangrijkste kwantitatieve en kwalitatieve bevindingen uit de evaluatie, gekoppeld aan de evaluatiedoelen uit 6.1.

---

## 8 Discussie

### 8.1 Interpretatie van de resultaten
Overkoepelende interpretatie van de resultaten uit hoofdstuk 7 in functie van de oorspronkelijke probleemstelling en onderzoeksvragen.

### 8.2 Implicaties voor IoT‑ en CPS‑deployments
Bespreking van wat de bevindingen betekenen voor echte IoT‑ en cyber‑physical deployments, met aandacht voor typische use‑cases en beperkingen.

### 8.3 Trade‑offs en designkeuzes
Analyse van de belangrijkste trade‑offs (security versus performantie, complexiteit versus flexibiliteit) en kritische reflectie op de gemaakte ontwerpkeuzes.

### 8.4 Beperkingen van het werk
Overzicht van de belangrijkste beperkingen van de huidige implementatie, evaluatie en generaliseerbaarheid.

---

## 9 Conclusie en toekomstig werk

### 9.1 Samenvatting van de bijdragen
Bondige samenvatting van de kernbijdragen van de masterproef (architectuur, implementatie, evaluatie, inzichten).

### 9.2 Belangrijkste conclusies
Korte, duidelijke formulering van de voornaamste inhoudelijke conclusies in relatie tot de probleemstelling.

### 9.3 Voorstellen voor toekomstig werk
Concrete ideeën voor verdere ontwikkeling, bijkomende experimenten en mogelijke impact op standaardisatie en industriële toepassingen.

---

## 10 Maatschappelijke reflectie

### 10.1 Impact op security en privacy
Reflectie over hoe dit type technologie security en privacy in IoT‑ en CPS‑omgevingen beïnvloedt, inclusief supply‑chain en driver‑ecosysteem.

### 10.2 Ethische en maatschappelijke aandachtspunten
Bespreking van risico’s, verantwoordelijkheden en bredere maatschappelijke context (bijv. afhankelijkheid van closed‑source runtimes, misbruik van remote hardware‑toegang).

---

## 11 Referenties
Gestandaardiseerde lijst van alle gebruikte bronnen (artikels, documentatie, whitepapers, blogs, repositories), volgens de richtlijnen van de opleiding.

---

## 12 Appendices

### 12.1 Uitgebreide benchmarktabellen en grafieken
Gedetailleerde cijfers, extra grafieken en tabellen die in de evaluatiehoofdstukken samengevat zijn.

### 12.2 Configuratiebestanden en scripts
Belangrijke configuratie‑ en scriptbestanden voor experimenten, build‑omgeving en deployment.

### 12.3 WIT‑definities en interfacefragmenten
Geselecteerde WIT‑fragmenten en andere interfacebeschrijvingen die te uitgebreid zijn voor de hoofdtekst.

### 12.4 Extra technische details
Overige technische details (schema’s, logfragmenten, device‑ en testmatrix) die de reproduceerbaarheid en verdere studie ondersteunen.
