// ESP32_1 (topside) — USB <-> RS485 bridge, now on separate UARTs.
//
// PHYSICAL WIRING — connect like this:
//
//   ESP32 pin (silkscreen)  →  MAX485 pin (label printed on module)
//   ───────────────────────────────────────────────────────────────
//   TX2  (= GPIO17)         →  "DI"  (data going into the transceiver)
//   RX2  (= GPIO16)         ←  "RO"  (received data — THROUGH voltage divider!)
//   D22  (= GPIO22)         →  "DE"  AND  "RE"  (tie both pins together, one wire from D22)
//   5V                      →  "VCC"
//   GND                     →  "GND"
//
//   MAX485 "A"  ──►  tether conductor going down to onboard MAX485 "A"
//   MAX485 "B"  ──►  tether conductor going down to onboard MAX485 "B"
//
//   USB cable to laptop uses UART0 internally (TX0 = GPIO1, RX0 = GPIO3).
//   These pins are not exposed for wiring — the USB-to-UART chip on the dev
//   board handles them. Just plug in the USB-C / micro-USB cable.
//
// NOTE — voltage divider on RO line:
//   MAX485 RO outputs 5V logic which would damage the ESP32's 3.3V GPIO16.
//   Install 3x 4.7kΩ resistors as a divider:
//     RO ──[4.7k]──┬── GPIO16
//                  │
//                 [4.7k]
//                  │
//                 [4.7k]
//                  │
//                 GND
//   Output at the divider node = 3.33V (safe for the ESP32).
//
// Bridge logic is half-duplex (MAX485 is half-duplex):
//   - Idle in receive mode (DE/RE LOW). Anything from the tether goes up to the laptop.
//   - When the laptop sends bytes, flip to TX, write them out, flush, flip back to RX.

// ESP32 dev-board pin (silkscreen) → MAX485 module pin
static const int PIN_RS485_TX    = 17;  // dev-board "TX2"  → MAX485 "DI"
static const int PIN_RS485_RX    = 16;  // dev-board "RX2"  → MAX485 "RO" (through voltage divider!)
static const int PIN_RS485_DE_RE = 22;  // dev-board "D22"  → MAX485 "DE" AND "RE" (tied together)

static const uint32_t BAUD = 115200;

inline void rs485SetTx(bool tx) {
  digitalWrite(PIN_RS485_DE_RE, tx ? HIGH : LOW);
}

void setup() {
  pinMode(PIN_RS485_DE_RE, OUTPUT);
  rs485SetTx(false);

  Serial.begin(115200);                                            // USB <-> laptop
  Serial2.begin(115200, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);   // RS485
}

void loop() {
  // Laptop -> tether
  if (Serial.available()) {
    rs485SetTx(true);
    while (Serial.available()) {
      Serial2.write((uint8_t)Serial.read());
    }
    Serial2.flush();
    delayMicroseconds(50);
    rs485SetTx(false);
  }
  // Tether -> laptop (telemetry / debug from ESP32_2)
  while (Serial2.available()) {
    Serial.write((uint8_t)Serial2.read());
  }
}
