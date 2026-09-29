// Build the Hardware Electronic Setup Report as a .docx
// Mirrors the style of Software_Development_Report.pdf.

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Header, Footer, AlignmentType,
  HeadingLevel, LevelFormat, PageNumber, PageBreak, TabStopType, TabStopPosition,
} = require("docx");

// ──────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────

const TITLE_FONT = "Times New Roman";

// Body paragraph — justified, Times New Roman 12pt, 1.15 line spacing.
function P(text, opts = {}) {
  return new Paragraph({
    spacing: { line: 276, after: 160 },
    alignment: AlignmentType.JUSTIFIED,
    children: [new TextRun({ text, font: TITLE_FONT, size: 24, ...opts })],
  });
}

// A paragraph composed of mixed runs (for inline bold etc.)
function PR(runs, align = AlignmentType.JUSTIFIED) {
  return new Paragraph({
    spacing: { line: 276, after: 160 },
    alignment: align,
    children: runs.map(r => new TextRun({ font: TITLE_FONT, size: 24, ...r })),
  });
}

function H1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200 },
    children: [new TextRun({ text, font: TITLE_FONT, size: 32, bold: true })],
  });
}

function H2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 160 },
    children: [new TextRun({ text, font: TITLE_FONT, size: 28, bold: true })],
  });
}

function H3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 220, after: 140 },
    children: [new TextRun({ text, font: TITLE_FONT, size: 26, bold: true, italics: true })],
  });
}

function Bullet(runs) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { line: 276, after: 80 },
    alignment: AlignmentType.JUSTIFIED,
    children: runs.map(r => typeof r === "string"
      ? new TextRun({ text: r, font: TITLE_FONT, size: 24 })
      : new TextRun({ font: TITLE_FONT, size: 24, ...r })),
  });
}

function Spacer() {
  return new Paragraph({ children: [new TextRun({ text: "" })] });
}

// ──────────────────────────────────────────────────────────────────────────
// Title page
// ──────────────────────────────────────────────────────────────────────────

function titlePage() {
  const blank = () => new Paragraph({ children: [new TextRun({ text: "" })] });
  return [
    blank(), blank(), blank(), blank(), blank(),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 360 },
      children: [new TextRun({ text: "HARDWARE & ELECTRONICS REPORT", font: TITLE_FONT, size: 48, bold: true })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 240 },
      children: [new TextRun({ text: "Barnacle Cleaning Robot", font: TITLE_FONT, size: 36, bold: true })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 480 },
      children: [new TextRun({ text: "Power, RS485 Tether, Motor Drive, and Onboard Wiring", font: TITLE_FONT, size: 28 })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 120 },
      children: [new TextRun({ text: "Integrated Design Project (IDP)", font: TITLE_FONT, size: 24 })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 120 },
      children: [new TextRun({ text: "University of Malaya", font: TITLE_FONT, size: 24 })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 240 },
      children: [new TextRun({ text: "Year 3 Semester 2, 2025/2026", font: TITLE_FONT, size: 24 })],
    }),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

// ──────────────────────────────────────────────────────────────────────────
// Body
// ──────────────────────────────────────────────────────────────────────────

const body = [
  // 1. INTRODUCTION
  H1("1. Introduction"),
  P("This report documents the hardware and electronics setup developed for the Barnacle Cleaning Robot, an underwater remotely operated vehicle (ROV) designed to detect and remove barnacle fouling from submerged structures. While a separate Software Development Report covers the firmware, GUI, and AI subsystems, the present report focuses on the physical layer that those subsystems run on: the power distribution network, the RS485 tether communication hardware, the stepper and DC motor drive circuits, the inter-board I²C bus, the camera module, and the prototyping environment in which the entire system was integrated and validated."),
  P("The electronic architecture was designed around four ESP32 microcontrollers, a half-duplex RS485 tether link, four TB6600-driven stepper motors for skid-steer locomotion, a brushed DC drum motor driven through an IBT-4 H-bridge, and an OV5640 camera sensor on an ESP32-S3 board. A topside 24 V supply is stepped down by a buck converter to a regulated 5 V rail that feeds every onboard board and driver, with each ESP32 generating its own 3.3 V logic rail through its on-module LDO. The supporting passive network — decoupling capacitors, level-shifting resistors, and the breadboard interconnect — is comparatively small, but its correctness has been critical to system reliability, as is discussed throughout this report."),
  P("The hardware development followed an iterative, test-driven approach. Early bench tests on a breadboard prototype exposed several real-world issues that were not visible in the schematic: a destroyed ESP32 GPIO from 5 V RS485 logic, an initially misconfigured MAX485 direction-control pin, motor-direction inversions between mirror-image stepper mounts, and an unintended motor spin-up at GUI connect time caused by a controller-axis initialisation bug. Each of these is documented in Section 9 alongside the corrective action that was applied. A formal schematic, produced in EasyEDA and reproduced as Figure 1, captures the present hardware state and is referenced throughout."),
  Spacer(),

  // 2. SYSTEM OVERVIEW
  H1("2. System Architecture Overview (Electrical View)"),
  P("From an electrical perspective, the Barnacle Cleaning Robot is partitioned into a topside subsystem at the surface and an onboard subsystem enclosed within the underwater vehicle, connected by a single tether cable that carries both power and a half-duplex RS485 data pair. This partitioning isolates the high-current motor electronics from the operator's laptop and reduces the number of conductors that need to be routed through the watertight gland on the ROV body."),
  P("On the topside, the laptop drives a USB-to-RS485 adapter that handles half-duplex direction control automatically, and a separate USB cable powers and programs the topside ESP32_1. The 24 V supply for the robot is generated topside from a benchtop power supply, and only two conductors of the 24 V rail and the two conductors of the RS485 differential pair (A and B) are routed down the tether. This minimises voltage drop in the data line — the differential signalling on the twisted pair is largely immune to common-mode noise picked up by the long cable run — while keeping the high-current path entirely on the dedicated 24 V conductors."),
  P("Onboard, a buck converter steps the 24 V tether voltage down to a regulated 5 V rail that supplies every ESP32 development board, the MAX485 transceiver, the TB6600 stepper drivers' logic side, and the camera module. Each ESP32 module generates its own 3.3 V logic rail internally through its on-board LDO regulator, so the breadboard distributes only the 5 V rail and a common ground. The three onboard ESP32 boards — the stepper controller (ESP32_2), the DC motor controller (ESP32_3), and the camera (ESP32-S3) — share this 5 V rail and a common 0 V reference, ensuring that all logic-level signals between them refer to the same ground potential."),
  P("The functional roles of the four boards are summarised below. The roles are deliberately split across separate microcontrollers rather than consolidated onto a single more powerful processor, so that high-current switching noise from the drum H-bridge cannot disturb the stepper pulse train or the RS485 receive timing — a design choice driven by hardware risk rather than software convenience."),
  Bullet([
    { text: "ESP32_1 (Topside Bridge): ", bold: true },
    { text: "USB-to-RS485 bridge at the surface. Receives binary command frames from the laptop over USB (UART0) and forwards them down the tether through a 5 V-powered MAX485 transceiver on UART2." },
  ]),
  Bullet([
    { text: "ESP32_2 (Onboard Stepper Controller): ", bold: true },
    { text: "Receives RS485 frames through a second MAX485 inside the ROV, decodes drive commands, and generates step and direction signals for four TB6600 stepper drivers. Also acts as the I²C master, forwarding drum on/off state to ESP32_3." },
  ]),
  Bullet([
    { text: "ESP32_3 (Onboard DC Motor Controller): ", bold: true },
    { text: "I²C slave at address 0x10. Drives the JGB37-555 drum motor through an IBT-4 H-bridge using a PWM signal on the RPWM input, with LPWM held low and the enable line gated by software." },
  ]),
  Bullet([
    { text: "ESP32-S3 (Camera Module): ", bold: true },
    { text: "Hosts an OV5640 image sensor and uses its native USB CDC interface to stream JPEG-compressed frames directly to the laptop on a separate USB cable, bypassing the RS485 tether entirely." },
  ]),
  P("The two USB cables on the laptop side — one to ESP32_1 and one to the ESP32-S3 — are independent serial channels. Command and telemetry traffic flows over the first; the high-bandwidth video stream flows over the second. This separation prevents the camera's 921600-baud byte stream from saturating the relatively narrow 115200-baud RS485 control channel, which would otherwise introduce unacceptable latency in the drive commands."),
  Spacer(),

  // 3. POWER DISTRIBUTION
  H1("3. Power Distribution and Conditioning"),
  P("Power for the robot is generated topside from a 24 V bench supply and delivered through the tether. Onboard, the 24 V rail is stepped down to 5 V by a buck converter mounted on the main breadboard. The 5 V output was measured at 5.00 V to 5.02 V on a digital multimeter under both unloaded and loaded conditions, indicating that the converter's output regulation is well within the tolerance window of the downstream ESP32 modules (which accept 4.0 V to 5.5 V on VIN through their on-board AMS1117 LDO regulators). This stable 5 V rail was confirmed at each ESP32's VIN pin before any signal-level testing began, eliminating power-quality as a source of intermittent faults during commissioning."),
  P("Two decoupling capacitors — a 100 µF electrolytic and a 0.1 µF ceramic — are placed across the 5 V and ground rails of the main breadboard, close to the buck converter output. The large electrolytic acts as a local energy reservoir that absorbs transient current demands from the four stepper drivers as they switch microsteps simultaneously, while the small ceramic capacitor handles high-frequency noise that the electrolytic's parasitic inductance cannot. Without these capacitors, the inductive switching of the TB6600 stepper drivers and the IBT-4 H-bridge would inject voltage ripple back into the 5 V rail, potentially causing the ESP32 modules to reset under load or corrupting the RS485 receive logic. This decoupling pair was therefore considered a hard requirement rather than an optional refinement."),
  P("Each ESP32 development module generates its 3.3 V logic rail internally from the 5 V supplied on its VIN pin. This is a significant simplification because it means the breadboard does not need to route a separate 3.3 V supply, and all logic-level translation between modules can be assumed to be referenced to a common ground. The 3.3 V rail of each board is also exposed on its 3V3 header pin and used as the high reference for the receive-side voltage divider on the RS485 line, which is discussed in detail in Section 4.2."),
  P("The four TB6600 stepper drivers and the IBT-4 H-bridge each draw their motor power directly from the 24 V tether rail, not from the 5 V logic rail. The motor power and logic power are therefore galvanically separated by the optocouplers inside each TB6600 driver and by the input-side opto on the IBT-4. This separation prevents the high-current pulses associated with step-and-direction switching and PWM motor drive from propagating into the sensitive 5 V logic supply, and is one of the principal reasons that the buck converter is sized only for the logic-side load (approximately 1.2 A peak across all ESP32s, MAX485s, and driver logic inputs combined) rather than for the entire system."),
  Spacer(),

  // 4. RS485 SUBSYSTEM
  H1("4. RS485 Tether Communication Subsystem"),
  P("The RS485 link is the single command and telemetry channel between the topside controller and the underwater robot, and is therefore the most failure-sensitive piece of the entire electrical architecture. The subsystem comprises two MAX485 transceivers (one at each end of the tether), a 5 V-to-3.3 V resistive voltage divider on each receive-output line, a software-controlled direction pin on each ESP32, and a single twisted pair of conductors running through the tether for the differential A and B lines. Each of these elements is discussed in the following subsections."),

  H2("4.1 MAX485 Transceiver Selection and Topology"),
  P("The MAX485 was selected because it is the de facto standard half-duplex RS485 transceiver for low-cost embedded projects, it is widely available as a pre-soldered breakout module that exposes the chip's pins on a header, and it operates from a single 5 V supply. The 5 V supply rail simplifies the system because it matches the buck converter output and avoids the need for an additional 3.3 V LDO dedicated to the transceiver. The trade-off is that the transceiver's RO (Receive Output) pin swings to approximately 5 V when receiving a logic high — a level that exceeds the ESP32's 3.6 V absolute-maximum GPIO input rating and therefore requires explicit attenuation, which is addressed in Section 4.2."),
  P("Two MAX485 modules are used. The first sits topside between the USB-to-RS485 adapter and ESP32_1's UART2, providing the surface end of the differential pair. The second sits onboard inside the ROV enclosure between the tether and ESP32_2's UART2. The A and B differential signals are connected straight through the tether with the corresponding terminals tied (A topside to A onboard, B topside to B onboard); the half-duplex multi-drop topology of the bus permits any number of additional transceivers to be tapped onto the same pair in principle, although in the present configuration only two are used."),
  PR([
    { text: "The pin-level wiring at each MAX485 is as follows: ", },
    { text: "VCC ", bold: true }, { text: "to the 5 V breadboard rail; " },
    { text: "GND ", bold: true }, { text: "to the common ground rail; " },
    { text: "DI ", bold: true }, { text: "(Driver Input) to the ESP32's UART2 TX (GPIO17); " },
    { text: "RO ", bold: true }, { text: "(Receive Output) to the ESP32's UART2 RX (GPIO16) through the voltage divider described in the next subsection; " },
    { text: "DE and RE ", bold: true }, { text: "(Driver Enable and active-low Receiver Enable) tied together and driven by a single ESP32 GPIO (GPIO4 on the onboard board, GPIO22 on the topside board); and " },
    { text: "A and B ", bold: true }, { text: "to the corresponding tether conductors. " },
  ]),
  P("The tying of DE and RE is a standard half-duplex convention: driving the combined pin high enables the transmitter and disables the receiver (transmit mode), while driving it low disables the transmitter and enables the receiver (receive mode). At any moment exactly one transceiver on the bus is in transmit mode while every other transceiver is in receive mode, and the firmware on both ESP32s is responsible for asserting this discipline through the direction GPIO."),

  H2("4.2 Logic-Level Translation on the RO Line — Voltage Divider Design"),
  P("Because the MAX485 is powered from 5 V, its RO pin drives a logic high of approximately 5 V into whatever it is connected to, while the ESP32's GPIO input absolute-maximum rating is V_DD + 0.3 V (approximately 3.6 V). Connecting RO directly to the ESP32's UART2 RX pin therefore exceeds the input rating and, over time, causes cumulative damage to the GPIO's internal ESD protection diodes — a failure mode that destroyed the first iteration of the topside board (Section 9.1). A resistive voltage divider is the standard remedy, and the present design implements one between every MAX485 RO and the corresponding ESP32 RX."),
  P("The divider ratio is set to attenuate the 5 V swing down to approximately 3.33 V, which is comfortably within the ESP32's input window and is also recognised as a valid logic high by the UART receiver (the ESP32's V_IH threshold is approximately 0.75 × V_DD = 2.48 V). A two-resistor divider with R1 = 1 kΩ on the top and R2 = 2 kΩ on the bottom would give the desired ratio mathematically (V_out = 5 V × R2 / (R1 + R2) = 3.33 V); however, the laboratory inventory at the time of construction contained only 4.7 kΩ through-hole resistors. To preserve the 1:2 ratio with the resistors actually on hand, the divider was implemented using three 4.7 kΩ resistors: one resistor forms the top leg, and two resistors in series form the bottom leg, giving R_top = 4.7 kΩ and R_bottom = 9.4 kΩ. The output voltage is V_out = 5 V × 9.4 / (4.7 + 9.4) = 3.33 V, which is identical to the textbook 1 kΩ / 2 kΩ design."),
  P("The trade-off of the higher-resistance divider is a lower divider current: 5 V across 14.1 kΩ gives approximately 0.35 mA, compared to roughly 1.67 mA for the 1 kΩ / 2 kΩ version. The reduced current makes the divider node more susceptible to noise pickup and to the input capacitance of the ESP32 RX pin, which lengthens the rise and fall times of the signal at the receiver. At the 115200-baud rate used on the bus, the bit period is approximately 8.68 µs, and the measured RC time constant of the divider with the ESP32's typical 10 pF input capacitance is far below one percent of this, so the impact on edge timing is negligible. The divider was therefore retained in its 3 × 4.7 kΩ form rather than re-implemented with lower-value resistors."),
  P("The same divider is replicated at both the topside and onboard MAX485 receivers, because the same 5 V-to-3.3 V mismatch applies to both. On the breadboard, the three resistors of each divider are arranged across two rows so that the top resistor bridges the MAX485 RO pin to the ESP32 RX pin, the first bottom resistor bridges the RX node to an intermediate row, and the second bottom resistor bridges that intermediate row to a row that is jumpered to the common ground rail. The voltage divider has not yet been added to the formal EasyEDA schematic (Figure 1) and is to be incorporated in the next revision; its absence on the drawing is a documentation gap rather than a physical-build gap, and a future redrawing of the schematic should include all three 4.7 kΩ resistors at each receiver."),
  P("In the opposite signal direction — from the ESP32's TX (GPIO17, 3.3 V swing) into the MAX485's DI input — no voltage translation is needed. The MAX485's input switching threshold is specified at approximately 2.0 V, and a 3.3 V high-level drive comfortably exceeds this. The same reasoning applies to the DE/RE control line: the MAX485 reads a 3.3 V GPIO drive as a valid logic high. Voltage division was therefore applied only on the receive path, where the level mismatch is in the dangerous direction."),

  H2("4.3 DE/RE Direction Control"),
  P("The MAX485's DE (Driver Enable) and active-low RE (Receiver Enable) pins are physically tied together on the breadboard and driven by a single ESP32 GPIO. On the onboard board, this control line is connected to GPIO4 of ESP32_2; on the topside board, it is connected to GPIO22 of ESP32_1. The shared pin is asserted high to put the MAX485 into transmit mode (driver on, receiver off) for the brief interval during which the ESP32 is sending a frame, and is held low at all other times to keep the receiver enabled and listening on the bus."),
  P("This GPIO-controlled direction pin is the correct topology for a half-duplex Modbus-style bus and is also the topology required for the firmware's three-step transmit sequence (assert DE/RE high, write all frame bytes and call flush, wait 50 µs, de-assert DE/RE low). An earlier iteration of the wiring tied the DE/RE pin permanently to the 5 V rail on one of the boards as a temporary test fixture, which forced the transceiver into permanent transmit mode and prevented it from ever receiving telemetry. That misconfiguration was identified and corrected during bench testing; the final wiring routes DE/RE to a dedicated GPIO on each board, as documented above."),

  H2("4.4 Tether Termination and Biasing — Known Limitation"),
  P("A textbook RS485 implementation typically includes two passive networks beyond the transceivers themselves: a 120 Ω termination resistor across the A and B lines at each physical end of the bus to absorb signal reflections, and a fail-safe bias network — usually a pair of resistors in the kilo-ohm range pulling A toward V_CC and B toward ground at one node on the bus — that holds the differential voltage in a defined state when no transceiver is driving the line. Together, these networks substantially improve robustness against long-cable reflections and against the idle-state ambiguity that can occur between frames."),
  P("In the present hardware build, neither the 120 Ω termination resistors nor the 680 Ω bias network were available in the laboratory inventory at the time of construction, and they have therefore not yet been installed. The system has nonetheless been operated successfully at 115200 baud over the tether during bench testing, because at this data rate and over the short tether length used for laboratory work, the absence of termination does not produce visible bit errors — the idle differential voltage was measured at approximately 2 V on both A and B lines, which is sufficient for the receiver to remain in a defined state. For longer tether runs in actual deployment, however, the addition of a 120 Ω termination at each end of the bus and a single 680 Ω bias pair on one node is strongly recommended, and is listed as a planned hardware improvement. The schematic in Figure 1 should be updated to include these components once they are procured and installed."),
  Spacer(),

  // 5. STEPPER DRIVE
  H1("5. Stepper Motor Drive Subsystem"),
  P("Locomotion is provided by a skid-steer arrangement of four stepper motors arranged at the corners of the chassis: front-left (TB1), rear-left (TB2), front-right (TB3), and rear-right (TB4). Each motor is driven by an independent TB6600 stepper driver, and each driver is commanded by step (PUL) and direction (DIR) signals from ESP32_2. The choice of stepper motors over geared DC motors was made for the precise speed control and the absence of cumulative position error that a stepper provides at low and moderate speeds — important properties for inspection and cleaning manoeuvres where the operator expects the robot to creep predictably along a surface."),

  H2("5.1 TB6600 Driver Configuration"),
  P("The TB6600 is an opto-isolated, microstepping bipolar stepper driver capable of supplying up to approximately 4 A per phase from a 9 V to 42 V motor supply, which matches the 24 V tether rail well. Each driver receives its motor power directly from the 24 V rail and its logic-side signals from the ESP32 through the on-board optocouplers, providing electrical isolation between the high-current motor side and the low-voltage logic side. The optocouplers' input side is biased by a series resistor inside the TB6600 module so that a 3.3 V GPIO drive is sufficient to fully turn on the input LED — no external level shifting is required between the ESP32 and the driver."),
  P("Each driver has two banks of DIP switches: a three-position bank that selects the microstep resolution and a three-position bank that selects the per-phase current limit. All four drivers were set to identical positions for nominal symmetric operation: 1/8 microstepping (effectively 1600 steps per mechanical revolution for a 200-step-per-revolution motor) and a per-phase current limit matched to the rated motor current. The 1/8 microstepping setting was selected as a compromise between mechanical smoothness (higher microstep counts smooth out the discrete stepping motion and reduce audible noise) and the step rate that the ESP32 can sustain in software (higher microstep counts require proportionally faster step-pulse generation for a given mechanical speed)."),

  H2("5.2 Step and Direction Signal Path"),
  P("Twelve GPIOs on ESP32_2 are dedicated to the four stepper drivers: one PUL and one DIR per motor, plus an unused common ENA line that is left disconnected because the drivers' default state is enabled at power-up. The PUL signal is a software-generated rectangular wave whose frequency sets the motor speed; each rising edge advances the motor by one microstep. The DIR signal is a logic level that selects the rotation direction. The firmware-side details of the pulse generator are covered in the Software Development Report and are not repeated here."),
  P("The pin assignments are arranged for cleanliness on the breadboard: PUL pins on GPIOs 25, 27, 19, and 5; DIR pins on GPIOs 26, 14, 18, and 33. The DIR pin of the rear-right motor was relocated from GPIO17 to GPIO33 during commissioning to free GPIO17 for the RS485 UART2 TX function, after the original pin assignment was found to conflict with the bridge wiring. This relocation also eliminated the 5 V contention that had previously damaged the topside ESP32, because no MAX485 output line was ever routed to a pin shared with a motor-driver input thereafter."),

  H2("5.3 Mechanical-Direction Compensation"),
  P("Because the four wheel assemblies are physically mirror-imaged on the chassis, the same DIR logic level does not necessarily produce the same wheel-rotation direction at every corner. Two cases were identified during bench testing: (a) the rear-left motor was mounted in a flipped orientation relative to the front-left, so identical DIR signals gave opposite shaft rotation between front and rear on the same side; and (b) the entire right side of the chassis is the mirror image of the left side, so the convention that produces forward motion on the left produces reverse motion on the right under identical DIR signals."),
  P("Rather than correct these inversions by physically rewiring the motor coil leads — which would have required dismantling the chassis and which would re-introduce the risk on every future maintenance — the inversions are compensated entirely in firmware through a per-motor invert flag. Each of the four Side structs in the stepper firmware carries a boolean invertDir field that XORs with the commanded direction before the GPIO is written. The flag is set to true for the rear-left motor (compensating for the mounting flip) and for both right-side motors (compensating for the left-right mirror), and false for the front-left reference motor. This software-based approach makes future motor swaps trivial: if a replacement motor is installed in a different orientation, only the corresponding flag needs to be toggled."),
  Spacer(),

  // 6. DC DRUM MOTOR
  H1("6. DC Drum Motor Drive Subsystem"),
  P("The cleaning drum is driven by a JGB37-555 brushed DC gearmotor through an IBT-4 H-bridge module controlled by ESP32_3. The drum is required to rotate in a single direction during cleaning operations, so the H-bridge is operated as a single-quadrant chopper: one side of the bridge is held permanently low while the other side receives a variable PWM signal that sets the average voltage applied to the motor and therefore the rotation speed."),
  P("The IBT-4 module accepts two PWM inputs (RPWM and LPWM), an enable line, and provides the 24 V motor supply and ground connections directly from the tether rail. The RPWM input is connected to a PWM-capable GPIO on ESP32_3 and driven at 20 kHz from the LEDC peripheral; LPWM is tied permanently low because reverse drive is never needed. The enable lines (R_EN and L_EN) are also driven by GPIOs so that the bridge can be fully disabled in software whenever the drum is commanded off, eliminating any leakage current that would otherwise cause unintended motor creep."),
  P("The 20 kHz PWM frequency was chosen to be above the audible range so that the inevitable acoustic emission from the motor windings under PWM excitation does not produce a distracting whine during operation. Lower frequencies (in the 1 kHz to 10 kHz range) would have placed the carrier squarely within human hearing and would have generated an audible tone that varied with duty cycle. The 20 kHz frequency was high enough to be inaudible to all members of the operating team but low enough to remain within the linear switching region of the IBT-4's BTS7960 half-bridge devices, which would suffer significant switching losses at frequencies above approximately 25 kHz."),
  P("The drum motor's high inductive load and brushed-commutator switching are significant sources of electromagnetic interference, and the physical separation of ESP32_3 onto its own microcontroller (rather than running the drum H-bridge from ESP32_2 directly) is partly a defensive measure against this noise. The brief commutation arcs that occur as the brushes pass between commutator segments can inject high-frequency noise back into both the 24 V rail and the surrounding wiring, and isolating the drum drive electronics onto a separate board with its own dedicated I²C link to the rest of the system reduces the chance that this noise will disrupt the stepper pulse train or the RS485 receive logic."),
  Spacer(),

  // 7. I2C BUS
  H1("7. I²C Inter-Board Communication"),
  P("Communication between the stepper controller (ESP32_2) and the DC motor controller (ESP32_3) is provided by an I²C bus operating at 100 kHz, with ESP32_2 acting as the bus master and ESP32_3 as a slave at address 0x10. The bus carries a single payload type — a one-byte drum on/off command — and a periodic zero-length transmission used as a health probe to confirm that ESP32_3 is alive and responding. The low data rate and minimal addressing requirements made I²C an obvious choice over a second RS485 segment or an SPI link for this short, intra-enclosure connection."),
  P("The bus is physically implemented as two jumper wires on the breadboard, one for SDA (GPIO21 on both boards) and one for SCL (GPIO22 on both boards), with the common ground supplied by the shared 5 V rail's return path. ESP32 development modules include internal weak pull-up resistors on their I²C-capable GPIOs that are sufficient for short bus runs at 100 kHz, and the present implementation relies on those internal pull-ups rather than adding dedicated external resistors. For the centimetre-scale wire lengths inside the ROV enclosure this has proven to be reliable in bench testing; for longer runs or for higher bus frequencies, external 4.7 kΩ pull-ups on both SDA and SCL would be the standard practice and should be considered if the I²C reach is ever extended."),
  Spacer(),

  // 8. CAMERA
  H1("8. Camera Module Hardware"),
  P("The vision subsystem is built around an ESP32-S3 development board with PSRAM and an OV5640 image sensor connected through the board's dedicated parallel camera interface. The ESP32-S3 was selected over the more common ESP32-WROOM for two specific hardware reasons: it provides the PSRAM required to double-buffer JPEG frames at VGA resolution without exhausting internal SRAM, and it includes native USB CDC support that allows it to enumerate as a virtual COM port directly on the laptop without needing an external USB-to-UART bridge chip."),
  P("The native USB connection is critical for sustaining the 921600-baud frame data rate. A conventional ESP32-WROOM connects to the laptop through a CP2102 or CH340 USB-to-UART bridge that has a relatively small internal FIFO and is prone to dropping bytes under sustained high-baud operation; the ESP32-S3's native CDC interface bypasses this buffering bottleneck entirely and presents a clean USB serial endpoint that the operating system can sink at line rate without loss."),
  P("The OV5640 sensor is mounted on the camera connector of the ESP32-S3 module and is electrically connected through the board's existing FPC cable. No additional external hardware is required on the camera module beyond a single USB-C cable to the laptop. Power for the camera is supplied through the same USB cable that carries the data, and the sensor's internal voltage regulators are integrated into the ESP32-S3 camera module's PCB. This single-cable topology was a major simplification compared to a discrete OV5640 sensor plus a separate ESP32-WROOM and bridge chip, and it kept the watertight pass-through on the ROV enclosure to a minimum number of conductors."),
  Spacer(),

  // 9. KEY DIFFICULTIES
  H1("9. Key Hardware Difficulties and Solutions"),
  P("The hardware build, like the software development described in the companion report, encountered a number of practical issues during bench commissioning that were not visible from the schematic alone. The following subsections describe the most significant of these and the corrective actions that were taken in each case."),

  H2("9.1 ESP32 GPIO Damage from Direct 5 V RS485 Connection"),
  P("The original wiring of the topside board connected the MAX485's 5 V RO pin directly to the ESP32's UART0 RX pin (GPIO3). The ESP32's GPIOs are not 5 V-tolerant — the absolute maximum input voltage is V_DD + 0.3 V, approximately 3.6 V — and although the input pin survived the initial bring-up tests, prolonged operation gradually damaged the internal ESD-protection clamp diodes. The eventual symptom was that the topside ESP32 stopped enumerating on USB and the GPIO3 pin no longer responded to either input or output writes, indicating that the pin had failed."),
  P("The corrective action consisted of two related changes: (a) the RS485 was moved from UART0 to UART2 on both the topside and onboard boards, which freed UART0 for exclusive USB serial use and prevented any further contention with the MAX485 on the boards' programming interface; and (b) the resistive voltage divider described in Section 4.2 was added on the RO line of every MAX485 to attenuate the 5 V swing to approximately 3.3 V before it reaches the ESP32 input. With both changes in place, no further GPIO damage has been observed."),

  H2("9.2 Voltage Divider Built from Available Resistors"),
  P("The textbook RO-to-RX divider uses a 1 kΩ top resistor and a 2 kΩ bottom resistor to achieve a 1:2 ratio and a 3.33 V output. At the time of construction, however, neither 1 kΩ nor 2 kΩ resistors were available in the laboratory; only 4.7 kΩ resistors were on hand. The divider was therefore re-implemented with three 4.7 kΩ resistors arranged so that the top leg consists of one resistor and the bottom leg consists of two resistors in series, producing a top-to-bottom ratio of 4.7 kΩ to 9.4 kΩ — the same 1:2 ratio as the textbook design. The output voltage is therefore 5 V × 9.4 / 14.1 = 3.33 V, identical to the canonical design within the tolerance of the resistors themselves. This solution illustrates a useful general principle: any 1:N divider ratio can be synthesised from N+1 identical resistors when the required individual values are unavailable, at the cost of a higher total impedance."),

  H2("9.3 Initial Permanent-Transmit Wiring of DE/RE"),
  P("During the very first half-duplex bring-up, the DE and RE pins of one MAX485 module were tied directly to the 5 V rail as a temporary expedient to confirm that the transmit path was functioning at all. With DE high and RE inactive, the transceiver is in permanent transmit mode and can never receive — a state that is correct for a transmitter-only sanity check but that breaks the bidirectional protocol used by the production firmware. The misconfiguration manifested as a working forward command channel but a complete absence of telemetry from the onboard system, and was identified by comparing the wiring against the schematic during a calm post-test review. The correction simply moved the DE/RE control wire from the 5 V rail to a dedicated GPIO (GPIO4 on the onboard board, GPIO22 on the topside board) and updated the firmware to drive the GPIO low at idle and high only for the duration of a transmitted frame. After this change, telemetry from ESP32_2 was received reliably."),

  H2("9.4 Tether Termination and Biasing Postponed"),
  P("The standard RS485 best-practice components — a 120 Ω termination resistor at each end of the bus and a single bias network of two 680 Ω resistors at one node — were not installed in the present build because the components were not available in the laboratory inventory at the time of construction. Bench testing at 115200 baud over the short laboratory tether length did not reveal any communication errors attributable to the absence of these components: the idle differential voltage measured approximately 2 V on each line, the receiver remained synchronised to the start bit of every frame, and the CRC8 check on the protocol's frames passed for every received frame. The absence of termination is therefore tolerated in the current configuration but is acknowledged as a known limitation; for longer tether runs or higher data rates, both the termination and the bias network are recommended additions and should be included on the next revision of the schematic."),

  H2("9.5 Motor-Direction Compensation in Firmware"),
  P("As discussed in Section 5.3, the four stepper-motor wheel assemblies on the chassis are not all identically orientated, and identical DIR signals therefore do not produce identical wheel-rotation directions at every corner. Rather than rewire the motor coil leads at the affected motors — which would have required mechanical disassembly and would have left the firmware ignorant of the true wiring on every subsequent maintenance event — the inversions were absorbed into the firmware through per-motor invertDir flags. The flag is set to true on the rear-left motor (to compensate for a mounting orientation that is flipped relative to the front-left reference) and on both right-side motors (to compensate for the chassis-wide left-right mirror), and is XORed with the commanded direction before each DIR GPIO write. The decision to handle this in software has been validated by the fact that the flag mapping has not changed since it was first determined and the firmware has needed no further corrections in this area."),

  H2("9.6 Stepper Motor Speed Asymmetry Under Load"),
  P("During final integration testing, the four stepper motors were observed to spin at slightly different speeds when commanded identically, despite the DIP switches on all four TB6600 drivers being set to identical positions. Periodic stalling and irregular motion was also observed on some of the motors under mechanical load. The cause has not yet been definitively isolated, but the most likely contributors are: variation in the per-phase current limit set by the DIP switches due to component tolerance in the drivers themselves; differences in the mechanical load presented by each wheel assembly (wheel friction, coupling alignment); and possible step-loss at peak commanded rates due to motor resonance near the natural frequency of the wheel-and-chassis combination. Resolution of this issue is identified as outstanding work and is not within the scope of the present hardware report."),

  H2("9.7 Spurious Motor Spin-Up at GUI Connect Time"),
  P("An anomaly observed during commissioning was that all four wheel motors briefly spun up at approximately half speed at the moment the GUI opened the serial connection to ESP32_1, even though the operator had not touched the controller triggers. Investigation traced the issue to the Xbox controller's analog trigger axes returning a placeholder value of 0.0 from the SDL/pygame layer before the operating system had polled the device for the first time, rather than the physically-correct released value of -1.0. The trigger-to-percentage conversion in the GUI mapped this 0.0 placeholder to 50% commanded drive, which was duly transmitted to ESP32_2 over the RS485 link and acted upon. The fix was applied in software: the conversion function was modified to treat any axis reading of exactly 0.0 as the released state (returning 0), and the controller-detection sequence in the GUI now pumps SDL events for several iterations after joystick initialisation to ensure that real axis values are populated before the first trigger-to-percentage call. This anomaly is documented here despite its software resolution because the underlying mechanism is a hardware-software interaction at the controller layer."),
  Spacer(),

  // 10. SCHEMATIC
  H1("10. Schematic and Wiring Reference"),
  P("The complete electrical schematic for the Barnacle Cleaning Robot was produced in EasyEDA and is supplied alongside this report as SCH_Schematic1_2026-06-12.pdf. The schematic captures the topside subsystem, the onboard subsystem, the tether interconnect, the four stepper drivers, the IBT-4 H-bridge, the I²C inter-board link, and the camera module. Power rails are colour-coded (24 V coral, 5 V blue, signals teal, drivers purple, motors amber) and the principal data flows are annotated with their direction and protocol."),
  P("Two known omissions from the current schematic revision should be noted by anyone consulting the drawing in conjunction with the physical build. First, the resistive voltage divider on each MAX485 RO pin (three 4.7 kΩ resistors per divider) is implemented on the breadboard but has not yet been added to the schematic, as discussed in Section 4.2. Second, the 120 Ω termination resistors and 680 Ω bias network discussed in Section 4.4 are likewise not present, because the corresponding components have not yet been installed on the physical hardware. Both omissions are tracked as documentation work for the next revision of the schematic. All other elements shown on the schematic — pin assignments, power rails, motor drivers, the I²C connection, the camera USB cable, and the tether differential pair — correspond directly to the physical build."),
  Spacer(),

  // 11. CONCLUSION
  H1("11. Conclusion"),
  P("The hardware and electronics setup for the Barnacle Cleaning Robot was designed around four ESP32 microcontrollers, two MAX485 transceivers connected by a single twisted pair through the tether, four TB6600-driven stepper motors for skid-steer locomotion, a brushed DC drum motor driven through an IBT-4 H-bridge, and an OV5640 camera on a dedicated ESP32-S3 with native USB CDC support. The power distribution starts from a topside 24 V supply, steps down to a 5 V logic rail through an onboard buck converter, and is decoupled by a 100 µF / 0.1 µF capacitor pair on the main breadboard. Each ESP32 generates its own 3.3 V logic rail from the 5 V supply, and a resistive 3 × 4.7 kΩ voltage divider on each MAX485's RO pin attenuates the transceiver's 5 V receive output down to a safe 3.3 V level for the ESP32's UART input."),
  P("The principal hardware difficulties encountered during the build — the destruction of a GPIO by direct 5 V RS485 logic, the synthesis of the voltage divider from non-ideal resistor values, the initial misconfiguration of the MAX485 direction-control pin, the per-motor direction-inversion problem caused by chassis mirroring, and the controller-axis initialisation interaction that briefly drove the motors on GUI connect — were all identified and resolved during bench commissioning. The hardware is now in a working state that supports the full firmware and GUI feature set described in the companion Software Development Report. Two known limitations remain and are flagged for the next revision: the absence of RS485 termination and biasing on the tether, and a small unresolved speed asymmetry across the four stepper motors under load."),
  P("Taken together, the hardware build demonstrates that a fully functional underwater ROV electronics platform can be assembled from low-cost off-the-shelf modules — ESP32 development boards, MAX485 breakouts, TB6600 stepper drivers, an IBT-4 H-bridge, and a single-board camera — provided that the interfaces between these modules are treated with the same care as the firmware running on top of them. The lessons learned in the course of this build — particularly around 5 V-to-3.3 V level translation, RS485 direction control, and the value of separating high-current motor logic from low-voltage signal logic — are expected to transfer directly to future iterations of this and similar underwater robotics projects."),
];

// ──────────────────────────────────────────────────────────────────────────
// Document
// ──────────────────────────────────────────────────────────────────────────

const doc = new Document({
  styles: {
    default: { document: { run: { font: TITLE_FONT, size: 24 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: TITLE_FONT },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: TITLE_FONT },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, italics: true, font: TITLE_FONT },
        paragraph: { spacing: { before: 220, after: 140 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }] },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          children: [new TextRun({
            text: "Barnacle Cleaning Robot — Hardware & Electronics Report",
            font: TITLE_FONT, size: 20, italics: true, color: "595959",
          })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Page ", font: TITLE_FONT, size: 20 }),
            new TextRun({ children: [PageNumber.CURRENT], font: TITLE_FONT, size: 20 }),
          ],
        })],
      }),
    },
    children: [...titlePage(), ...body],
  }],
});

Packer.toBuffer(doc).then(buf => {
  const outPath = path.join(__dirname, "Hardware_Electronics_Report.docx");
  fs.writeFileSync(outPath, buf);
  console.log("Wrote", outPath, "(" + buf.length + " bytes)");
});
