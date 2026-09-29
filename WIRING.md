# Barnacle Cleaning Robot — Full Wiring Reference

**Last updated:** for the pitch session, June 2026.
Match every connection below to the dev-board silkscreen labels and the
printed pin labels on each module. If a label disagrees with this doc,
trust the doc — the modules vary between manufacturers.

---

## System diagram (boards and where they live)

```
              ┌──────────────────────────────────────┐
              │  TOPSIDE (at the laptop)             │
              │                                      │
   Laptop ────┼── USB ── ESP32_1 ── MAX485 #1 ─┐    │
              │                                  │    │
              │      ESP32-S3 (camera) ── USB ──┼── Laptop (second USB)
              └──────────────────────────────────┼───┘
                                                 │
                                       tether    │
                                       (A, B pair, 24V power)
                                                 │
              ┌──────────────────────────────────┼───┐
              │  ONBOARD (inside the ROV)        │   │
              │                                  │   │
              │  MAX485 #2 ── ESP32_2 ── I²C ── ESP32_3 ── H-bridge ── Drum motor
              │                  │                                              │
              │                  ├── TB6600 #1 ── Front-Left stepper            │
              │                  ├── TB6600 #2 ── Rear-Left stepper             │
              │                  ├── TB6600 #3 ── Front-Right stepper           │
              │                  └── TB6600 #4 ── Rear-Right stepper            │
              └──────────────────────────────────────────────────────────────────┘
```

---

## 1. ESP32_1 — Topside Bridge

Sits at the surface. USB to laptop on one side, MAX485 to tether on the other.

### Wiring

| Wire from ESP32_1 (silkscreen)  | Wire to                                |
| ------------------------------- | -------------------------------------- |
| `TX2` (= GPIO17)                | MAX485 #1 pin **"DI"**                 |
| `RX2` (= GPIO16)                | top of voltage divider (see below)     |
| `D22` (= GPIO22)                | MAX485 #1 pins **"DE"** AND **"RE"** (tie both module pins together first, then one wire to D22) |
| `5V`                            | MAX485 #1 pin **"VCC"**                |
| `GND`                           | MAX485 #1 pin **"GND"**                |
| `GND`                           | bottom of voltage divider              |
| (USB cable)                     | laptop USB                             |

### Voltage divider on the RO line — 3 × 4.7 kΩ resistors

```
   MAX485 #1 "RO"  ──[ R1 = 4.7kΩ ]──┬── ESP32_1 RX2 (GPIO16)
                                      │
                                    [ R2 = 4.7kΩ ]
                                      │
                                    [ R3 = 4.7kΩ ]
                                      │
                                     GND
```

R1 alone on top, R2 and R3 in series on the bottom. Output at the junction = 3.33 V. Do not skip this divider — MAX485 RO is 5 V and the ESP32 GPIO is not 5 V tolerant.

### Tether (A and B)

| MAX485 #1 pin | Tether conductor                      |
| ------------- | ------------------------------------- |
| `"A"`         | A line going down to MAX485 #2 `"A"`  |
| `"B"`         | B line going down to MAX485 #2 `"B"`  |

---

## 2. ESP32_2 — Onboard Stepper Controller

Sits inside the ROV. Receives RS485 commands, drives all four wheel steppers, talks I²C to ESP32_3.

### MAX485 #2 wiring (the onboard transceiver)

| Wire from ESP32_2 (silkscreen) | Wire to                                |
| ------------------------------ | -------------------------------------- |
| `TX2` (= GPIO17)               | MAX485 #2 pin **"DI"**                 |
| `RX2` (= GPIO16)               | top of voltage divider (see below)     |
| `D4`  (= GPIO4)                | MAX485 #2 pins **"DE"** AND **"RE"** (tie both, one wire to D4) |
| `5V`                           | MAX485 #2 pin **"VCC"**                |
| `GND`                          | MAX485 #2 pin **"GND"**                |
| `GND`                          | bottom of voltage divider              |

### Voltage divider on the RO line — 3 × 4.7 kΩ resistors

Same layout as the topside divider, just on this board's MAX485:

```
   MAX485 #2 "RO"  ──[ R1 = 4.7kΩ ]──┬── ESP32_2 RX2 (GPIO16)
                                      │
                                    [ R2 = 4.7kΩ ]
                                      │
                                    [ R3 = 4.7kΩ ]
                                      │
                                     GND
```

### Tether (A and B)

| MAX485 #2 pin | Tether conductor                      |
| ------------- | ------------------------------------- |
| `"A"`         | A line going up to MAX485 #1 `"A"`    |
| `"B"`         | B line going up to MAX485 #1 `"B"`    |

### I²C bus to ESP32_3

| Wire from ESP32_2 (silkscreen) | Wire to ESP32_3 (silkscreen)           |
| ------------------------------ | -------------------------------------- |
| `D21` (= GPIO21)               | `D21` (= GPIO21)  — SDA                |
| `D22` (= GPIO22)               | `D22` (= GPIO22)  — SCL                |
| `GND`                          | `GND`  — must share ground             |

#### External I²C pull-up resistors (2 × 4.7 kΩ to 3.3 V)

The ESP32's internal pull-ups are weak; add external ones for reliability:

```
   ESP32_2 "3V3" ──┬──[ 4.7kΩ ]── SDA line (both D21s)
                   │
                   └──[ 4.7kΩ ]── SCL line (both D22s)
```

⚠️ Pull-ups MUST go to **3.3 V**, not 5 V. 5 V would damage the ESP32 GPIOs.

### Four TB6600 stepper drivers

Each TB6600 has signal-side terminals: `PUL+`, `PUL-`, `DIR+`, `DIR-`, `ENA+`, `ENA-`.

For **all four** drivers:
- `PUL-`, `DIR-`, `ENA-` and `ENA+` → leave disconnected, or tie all `-` pins to ESP32 GND.
  (ENA pins unconnected = driver enabled by default. PUL- / DIR- to GND for common-cathode wiring.)
- Recommended: tie `PUL-` and `DIR-` of every driver to **ESP32_2 GND**.

**Per-driver wiring (signal side):**

| Driver       | Wheel position | ESP32_2 → TB6600 PUL+ | ESP32_2 → TB6600 DIR+ |
| ------------ | -------------- | --------------------- | --------------------- |
| TB6600 **#1** | Front-Left     | `D25` (= GPIO25)       | `D26` (= GPIO26)       |
| TB6600 **#2** | Rear-Left      | `D27` (= GPIO27)       | `D14` (= GPIO14)       |
| TB6600 **#3** | Front-Right    | `D19` (= GPIO19)       | `D18` (= GPIO18)       |
| TB6600 **#4** | Rear-Right     | `D5`  (= GPIO5)        | `D33` (= GPIO33)       |

**Motor-side terminals on each TB6600:**

| TB6600 terminal | Connect to                                      |
| --------------- | ----------------------------------------------- |
| `VCC` / `V+`    | 24 V from tether (motor power)                  |
| `GND` / `V-`    | 24 V supply ground                              |
| `A+`, `A-`      | One coil of the stepper motor                   |
| `B+`, `B-`      | Other coil of the stepper motor                 |

> **DIP switches** on every TB6600: set all four drivers to identical positions for microstepping (1/8 recommended) and current limit (match your motor's rated current — usually 2.0 A or 2.5 A).

### ESP32_2 power

| ESP32_2 pin | Connect to                              |
| ----------- | --------------------------------------- |
| `VIN`       | breadboard 5 V rail (from buck or battery) |
| `GND`       | breadboard GND rail                     |

---

## 3. ESP32_3 — Onboard Drum Controller

Sits inside the ROV. I²C slave. Drives the drum motor through the H-bridge.

### I²C bus to ESP32_2

| Wire from ESP32_3 (silkscreen) | Wire to ESP32_2 (silkscreen)           |
| ------------------------------ | -------------------------------------- |
| `D21` (= GPIO21)               | `D21` (= GPIO21)  — SDA                |
| `D22` (= GPIO22)               | `D22` (= GPIO22)  — SCL                |
| `GND`                          | `GND`  — must share ground             |

### H-bridge module (2-input type — IN1, IN2, GND)

| Wire from ESP32_3 (silkscreen) | Wire to                                |
| ------------------------------ | -------------------------------------- |
| `D25` (= GPIO25)               | H-bridge pin **"IN1"**                 |
| `D26` (= GPIO26)               | H-bridge pin **"IN2"**                 |
| `GND`                          | H-bridge pin **"GND"**                 |

**Motor-power side of the H-bridge:**

| H-bridge terminal | Connect to                                |
| ----------------- | ----------------------------------------- |
| `V_MOT` / `VCC`   | 24 V from tether (motor power)            |
| `GND`             | 24 V supply ground                        |
| `OUT1` / `M+`     | Drum motor terminal 1                     |
| `OUT2` / `M-`     | Drum motor terminal 2                     |

> If the drum spins backward after the build: open `OnboardDC_ESP3.ino` and flip `DRUM_DIR_FORWARD` from `true` to `false` (or vice versa), reflash. No rewiring needed.

### ESP32_3 power

| ESP32_3 pin | Connect to                              |
| ----------- | --------------------------------------- |
| `VIN`       | breadboard 5 V rail                     |
| `GND`       | breadboard GND rail                     |

---

## 4. ESP32-S3 — Camera Module

| Connection      | Goes to                                    |
| --------------- | ------------------------------------------ |
| USB-C cable     | Second USB port on the laptop              |
| OV5640 camera   | Already on the board's camera FPC connector — don't disconnect |

No other wiring. Power is supplied through the USB cable. Do not connect the ESP32-S3 to the breadboard's 5 V rail — its USB provides its own power.

---

## 5. Breadboard power distribution (onboard)

The buck converter (or replacement battery) feeds the breadboard rails, and the rails feed every onboard module:

| From buck / battery  | To breadboard rail |
| -------------------- | ------------------ |
| `+` (5 V output)     | red `+` rail       |
| `–` (GND)            | blue `–` rail      |

| From red `+` rail (5 V) | To                            |
| ----------------------- | ----------------------------- |
| jumper                  | ESP32_2 `VIN`                 |
| jumper                  | ESP32_3 `VIN`                 |
| jumper                  | MAX485 #2 `VCC`               |

| From blue `–` rail (GND) | To                            |
| ------------------------ | ----------------------------- |
| jumper                   | ESP32_2 `GND`                 |
| jumper                   | ESP32_3 `GND`                 |
| jumper                   | MAX485 #2 `GND`               |
| jumper                   | bottom of voltage divider     |
| jumper                   | every TB6600 `PUL-` and `DIR-` (recommended) |

> The 24 V motor supply rail is **separate** from this 5 V logic rail. 24 V goes only to the four TB6600 motor inputs and the H-bridge `V_MOT`. Never connect 24 V to any ESP32 VIN or any MAX485 VCC. They will die.

---

## 6. Sanity checks before powering up

Run these with the multimeter, power **off**:

1. **5 V rail to GND rail** — should read kΩ range, not 30 Ω. If 30 Ω, you have a short.
2. **Each ESP32 VIN to GND** (board off the breadboard) — should read 5 kΩ+. Less than 100 Ω = dead board.
3. **Each MAX485 VCC to GND** (off the breadboard) — should read kΩ+. Less than 100 Ω = dead.
4. **Polarity check on every red wire** — trace it visually from the buck `+` to its endpoint. No red wire should ever end at a GND pin.

Then with power **on** but nothing yet running:

5. **5 V rail voltage** — should read 4.95–5.05 V steady.
6. **Touch each ESP32, each MAX485, the H-bridge with a finger** — all should be cool or barely warm. Anything hot = damaged, power off immediately and find which one.

---

## 7. Quick troubleshooting

| Symptom                                       | Likely cause                                       | Where to look                |
| --------------------------------------------- | -------------------------------------------------- | ---------------------------- |
| ESP32 gets hot at idle                        | Damaged board (likely from previous overvoltage)   | Replace that ESP32           |
| Drum spins wrong direction                    | H-bridge IN1/IN2 swap needed                       | Flip `DRUM_DIR_FORWARD` in `OnboardDC_ESP3.ino` |
| Wheels spin wrong direction                   | DIR-flag mapping needs flipping                    | `invertDir` flags in `OnboardSteppers_ESP2.ino` |
| GUI says "i2c=FAIL" repeatedly                | SDA/SCL not connected, or grounds not tied         | Both `D21`s connected? Both `D22`s connected? Both grounds tied? |
| GUI never sees telemetry from ESP32_2         | RS485 wiring or DE/RE control                      | DI/RO not swapped on either MAX485? Voltage divider in place? D4 (onboard) and D22 (topside) actually driving DE/RE? |
| Motors stall at 100 % throttle                | Speed cap too high for current motor torque        | Lower `MAX_SPS` in `OnboardSteppers_ESP2.ino` (currently 1600) |
| Wire on 5 V rail burns                        | Short downstream — buck converter dead, ESP32 dead, polarity reversed | Multimeter rail-to-GND, isolate by pulling parts one at a time |
