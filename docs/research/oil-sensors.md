<!-- Research notes (R8), 23.09.2026; verbatim with personal contacts removed. -->
# Oil & Fluid Sensors for Russian Telematics: Research Findings

**Date:** 2026-09-23 | **Topic:** Fuel/oil level + condition sensors integration with Galileosky/Navtelecom trackers

---

## 1. СУЖ M12 Level Sensor (SKB Induktciya)

**Source:** https://penza.ank-ndt.ru/catalog/kip/ (SKB Indukciya, СУЖ M12-12B-K.SUG-01)

- **Principle:** Thermistor (позистор) level switch, NOT a continuous resistive sender.
  - Heated thermistor; when liquid touches it, it cools, resistance drops, current changes.
  - **NOT suitable for analog voltage divider measurement.**
  - Output is a **discrete on/off current signal**, not a resistive level sender (0–240Ω range).

- **Output type:** Current-based discrete logic, not a continuously variable resistance output.
  - Nominal resistance 24°C: **120–200 Ω** (mentioned as "RT 120 Ом и выше")
  - This spec describes the thermistor's resistance *change range*, not the sender linearity.

- **Supply:** 12–18 V nominal, max 24 V; current ~35 mA air, ~45+ mA in liquid. *Discrete voltage available, not for ADC.*

- **Temperature range:** –40 to +100°C. 

- **Thread:** M12; stainless steel body/stem.

- **Liquids:** Oil, coolant, fuel (general purpose).

- **Availability:** Russia, available in stock (АНК supplier, 2–7 day delivery). **Price:** "по запросу" (quote upon request).

**Confidence:** HIGH (direct Russian supplier specs).

---

## 2. Poseidon Systems Trident Oil Health Sensors

### QW3100 (with water sensor) & QM3100 (oil condition only)

**Sources:**
- https://www.poseidonsys.com/products-and-services/products/oil-quality-sensors/trident-qw3100/
- https://servintel.com/wp-content/uploads/2023/12/QWQM3100-Marketing-Sheet-0721.pdf

### Measured Quantities:
- **Oil condition:** Impedance spectrum (multi-frequency EIS analysis) → **additive health, oil breakdown, contamination presence** (discrete output, not a continuous parameter).
- **Water (QW3100 only):** Integrated water-in-oil sensor → dissolved water content **(direct measurement, ppm or water activity aw).**
- **Temperature:** Built-in.
- **Particle counts:** NOT listed (unlike Chinese OMS-300).
- **Viscosity, density:** Mentioned as "condition indicators" but derived from EIS, not direct measurement.

### Communication:
- **CAN J1939:** Yes, compatible. **SPNs/PGNs:** Not specified in available docs.
- **RS-485 Modbus RTU:** Yes, compatible.
- **Analog 4–20 mA:** No explicit mention.

### Supply & Physical:
- 10–30 VDC, 1.5 W max.
- Port: 1/2" SAE ORB or G 1/2" BSPP thread.
- IP67 ingress.
- **Temp range:** –40 to +150°C (302°F).

### Availability & Sanctions Status (2026):
- **US company** (Poseidon Systems, Victor, NY 14564, USA).
- No explicit mention of Russia availability or sanctions restrictions found.
- Contact: +1 (585) 239-6025, [e-mail удалён]
- **Confidence:** MODERATE—no explicit Russia-market denial, but US company ≈ likely under export/OFAC restrictions. No distributor for RF found in search. **Status UNKNOWN for 2026.**

**Confidence:** HIGH on specs; MODERATE on Russia availability (likely blocked, not confirmed).

---

## 3. Rochester Sensors T-LL415

**Source:** https://rochestersensors.com/product/t-ll415/

- **Type:** Capacitive liquid level sensor (NOT resistive sender), continuous 0–100% output.
- **Output:** **J1939 CAN** only. **NOT resistive ohms, NOT 4–20 mA.**
  - Oil level: 0–100% (±5% accuracy).
  - Temperature: –40 to +140°C (±3% accuracy).

- **Supply:** 9–36 VDC. <30 mA.

- **Mounting:** Vertical top mount only; thread options: 1/2" BSPT, 1/2" BSPP, 3/4" UNF, 1/2" NPTF, M16, M18, M20.

- **Liquids:** Engine, transmission, hydraulic oils (standard fluids).

- **Materials:** 316 stainless steel header/stem, PTFE-sheathed electrode, fluorosilicone (FVMQ) seals.

- **Accuracy:** ±5% level, ±3% temperature. Start-up delay: 500 ms.

- **IP rating:** IP68 liquid side, IP67 connector side.

- **Availability:** UK manufacturer (Rochester Sensors, Warwick). **Price:** Not listed. No Russia distributor found.

- **CAN J1939 interface:** Yes, but **no specific PGNs/SPNs documented in available materials.**

**Confidence:** HIGH on specs; UNKNOWN on Russia availability and CAN parameter details.

---

## 4. Russian Oil Quality/Water-in-Oil Sensors

### Omnicomm (Russia)

**Source:** https://www.omnicomm.ru/; LLS Neo passport PDF

- **Omnicomm LLS Neo** (fuel level sensor with temperature, not oil *condition*):
  - RS-485 interface: **Omnicomm LLS protocol or Modbus RTU.** Configurable baud rate up to 115,200 bps.
  - Measures: **Fuel/liquid level + temperature** only. NOT designed for oil quality/water activity.
  - **Availability:** Made in Russia, readily available.

- **Oil quality/water sensors from Omnicomm:** Not found in search results; company focuses on fuel level (LLS) and fuel efficiency. No dedicated "oil condition" product identified.

### Chinese Sensors (With Modbus RTU, sold in Russia via aliexpress/alibaba):

1. **Kongter OMS-300** (integrated oil monitor):
   https://kongter.com/products/oms-300-series-integrated-oil-online-monitoring-sensor/
   - **Measures:** Wear debris (ferromagnetic ≥40µm, non-ferromagnetic ≥150µm), viscosity, density, trace moisture, **water activity (aw), dielectric constant, water ppm, temperature.**
   - **Communication:** RS-485 Modbus RTU, **2.5 kV isolated.**
   - **Supply:** Standard industrial 24 VDC.
   - **Availability:** China manufacturer; sold globally including via Russian resellers.
   - **Confidence:** HIGH (detailed specs, widely available).

2. **Tianyi Sensor Q-1624** (dielectric constant / oil aging sensor):
   https://www.tianyisensor.com/Oil-Quality-Sensor/Oil-dielectric-constant-sensor.html
   - **Measures:** Oil dielectric constant (aging/contamination indicator via EIS), multi-parameter analysis.
   - **Communication:** CAN J1939, RS-485 Modbus RTU.
   - **Supply:** All oils supported.
   - **Availability:** China; contact [e-mail удалён] for RF availability.
   - **Confidence:** MODERATE (marketing-heavy, limited technical detail).

3. **MOP301 Water-in-Oil Probe** (Chinese, Modbus RTU):
   https://www.zf116.com/products/show_617.html
   - **Measures:** Water activity (aw 0–1 range, ±0.02 accuracy), temperature, water ppm (calculated).
   - **Communication:** RS-485 **Modbus RTU**, customizable registers.
   - **Supply:** 8–35 VDC.
   - **Temperature:** –40 to +120°C.
   - **Mounting:** ISO or NPT threads; optional ball valve for hot-swap (up to 20 bar).
   - **Availability:** China manufacturer (Shenzhen); unknown RF distributor.
   - **Confidence:** HIGH (detailed specs, real product).

---

## 5. Resistive Level Sender Integration with Tracker Analog Inputs

### Galileosky 7.x Analog Input Configuration:

**Source:** https://base.galileosky.com + https://store.galileosky.ru/

- **Input range:** 0–33 V, 16-bit ADC (0–4095 digital codes).
- **Pull-up resistor:** Mentioned as "настраиваемая индивидуальная подтяжка к +2,7В" (**configurable individual pull-up to +2.7V**).
- **Standard setup for resistive fuel level senders:**
  - Internal pull-up or external voltage divider required.
  - **Voltage divider example (from non-Galileosky source):** For 33–240Ω fuel sender with 12V supply, 200Ω series resistor yields voltage drop 1.7V (empty) to 6.5V (full) across the sender. **This method is standard but tracker-specific configuration required.**

- **Tag mapping:** Analog inputs mapped to **Tags 0x50–0x57** (and extended 0x78–0x7D).
  - Data type: "ain" = voltage on analog input (volts), indexed.
  - These tags are **transmitted in Galileosky native protocol** to EGTS and server.

- **Wialon IPS protocol parameters:** Analog inputs typically appear as **adc1, adc2, ...adcN** (indexed ADC values) in Wialon; linked to Galileosky Tags via configurator mapping.

- **RS-485 Modbus RTU support:** Galileosky 7.x **can read Modbus devices** via RS-485 using **custom algorithm** (not native firmware feature).
  - URL: https://store.galileosky.ru/en/datchiki/dut/algoritm-obmena-s-rs485
  - Algorithm must be loaded and configured; up to **32 different Modbus parameters** can be extracted per Navtelecom wiki (similar architecture).
  - Extracted values then appear as **user-defined tags** in protocol output.

**Confidence:** HIGH (official docs); note that native Modbus reading requires algorithm/custom firmware, not automatic.

---

## 6. Navtelecom SIGNAL/SMART RS-485 Modbus RTU Support

**Source:** https://wiki.navtelecom.ru/en/home/devices/settings/rs/modbus

- **Modbus Master mode:** Terminal reads Modbus devices (slave mode).
- **Supported functions:** 0x01 (Read Coils), 0x02 (Read Discrete Inputs), 0x03 (Read Holding Registers), 0x04 (Read Input Registers).
- **Data types:** 1–2 byte (bit, int, uint) and 4–8 byte (int, uint, float IEEE 754).
- **Output:** Up to 32 parameters extracted from Modbus registers.
- **Configuration:** Requires Register Map (slave device specifications); baud rate, parity, stop bits configurable.
- **Protocol transmission:** Configured via Navtelecom configurator's **Protocol Settings** tab; extracted Modbus parameters appear in EGTS and Wialon as **user parameters**.

**Confidence:** HIGH (official wiki).

---

## 7. EGTS Protocol Analog Sensor Support

**Source:** https://wialon.com/en/gps-hardware/soft/egts

- **Analog sensor parameter:** EGTS_SR_ABS_AN_SENS_DATA record type contains **adc#** (indexed ADC values).
- **Wialon mapping:** Appears as `adc1`, `adc2`, ... in Wialon's parameter list.
- **Data transmission:** Tracker (EGTS device) reads ADC inputs and transmits them to server.
- **Modbus integration:** EGTS-capable trackers (e.g., Navtelecom) extract Modbus registers and transmit as user parameters in EGTS records.

**Confidence:** HIGH (official protocol docs).

---

## **Summary Table: Integration Viability**

| Sensor | Interface | Tracker Support | Output to EGTS/Wialon | Notes |
|--------|-----------|-----------------|----------------------|-------|
| **СУЖ M12** | Discrete current | ADC (voltage) via divider | ain / adc# | Thermistor switch, NOT true analog sender; requires interpretation |
| **Poseidon QW3100/QM3100** | CAN J1939, RS485 Modbus RTU | CAN (J1939), RS485 (algo) | CAN tags or user Modbus params | US company; Russia availability UNKNOWN; water + oil condition |
| **Rochester T-LL415** | CAN J1939 only | CAN (native) | CAN tags only | No RS485; capacitive; UNKNOWN PGN/SPN mapping; UK supplier |
| **Kongter OMS-300** | RS485 Modbus RTU | Yes (algorithm) | User Modbus params | China; wear particles + water activity; real-time capable |
| **Tianyi Q-1624** | CAN J1939, RS485 Modbus | Yes (native/algo) | CAN or user params | China; oil dielectric (aging); contact for RF availability |
| **MOP301** | RS485 Modbus RTU | Yes (algorithm) | User Modbus params | China; water activity + ppm; no particle analysis |

---

## **Critical Unknowns**

1. **Poseidon QW3100 Russia availability:** No distributor or sanction status confirmation found. Recommend direct contact or alternative.
2. **Rochester T-LL415 CAN J1939 PGNs/SPNs:** Not published; would need datasheet or vendor contact for exact message structure and Wialon mapping.
3. **Chinese sensor Russia supply chain:** Konter, Tianyi, MOP301 widely available on CN reseller platforms; confirmation of RF import legality and customs status not researched.
4. **Pull-up resistor values for resistive senders on Galileosky/Navtelecom:** Official documentation mentions configurability but not default or recommended values. Likely 10–20 kΩ (standard practice) but unconfirmed.
5. **СУЖ M12 continuous analog measurement:** Since it's a discrete thermistor switch, continuous liquid level cannot be derived from a single voltage reading; alternative: multiple fixed-level switches or upgrade to a true resistive float sender.

---

## Still unknown:
- Poseidon sensor sanctions/export status for Russia (2026).
- Rochester T-LL415 CAN PGN mappings for oil level & temperature.
- Exact pull-up resistor specifications in Galileosky/Navtelecom manuals (only configurability mentioned).
- Chinese sensor distributor legitimacy and Russian import legal status.
