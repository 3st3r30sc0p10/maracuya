## Technical Report — ESP32‑S3 USB/UART Instability and Recovery

### Executive Summary
The ESP32‑S3 Feather repeatedly enumerated as UF2 bootloader or USB JTAG/serial, causing `/dev/ttyACM0` to appear and disappear. Root causes were incorrect pin mapping (raw GPIOs instead of Feather aliases) and USB CDC instability. We migrated telemetry to UART and validated the UART path. The system now operates reliably over UART with correct Feather pin mapping.

### Symptoms Observed
- `lsusb` oscillated between:
  - `239a:811b` (Adafruit Feather ESP32‑S3)
  - `239a:011b` (UF2 bootloader mass storage)
  - `303a:1001` (Espressif USB JTAG/serial)
- `/dev/ttyACM0` appeared/disappeared.
- Firmware ran in “safe mode” but failed in full mode.
- UART initially silent despite correct wiring.

### Root Causes
**Incorrect pin mapping**
- Firmware used raw GPIO numbers (1/2/3, 9/10, 5) assuming they matched A0/A1/A2 and D9/D10/D5 on the Feather.
- The Feather ESP32‑S3 variant mapping defines:
  - A0/A1/A2 → GPIO18/17/16
  - TX/RX → GPIO39/38
  - D5 → A5 → GPIO8
  - D9/D10 → A10/A11 → GPIO9/10
- Incorrect GPIOs can hit boot‑sensitive pins or internal functions, causing boot instability.

**USB CDC instability**
- Even when the app ran, USB CDC did not consistently enumerate.
- USB CDC behavior differs from UF2 bootloader, so “UF2 stable” does not guarantee CDC stability.

### Decisions Taken
- Isolate USB issues: bypass USB telemetry in favor of UART.
- Binary‑search peripheral init: add SAFE_MODE and toggle subsystems.
- Pin map audit: verify Feather mappings from `pins_arduino.h`.
- UART verification: add echo/heartbeat and verify Pi loopback.

### What We Changed (Key Fixes)
- Switched sensor pins to Feather aliases: A0/A1/A2.
- Switched ultrasonic pins to Feather aliases: A10/A11.
- Switched TX/RX to TX/RX macros (GPIO39/38).
- Moved telemetry to UART, disabling USB CDC.
- Added safe mode and UART echo test.
- Updated documentation (`pin_map.md`, `comms_rpi.md`) with correct mappings.
- Reference: Adafruit ESP32‑S3 Feather pinouts.

### Final Working Configuration
- Telemetry: UART (Pi GPIO14/15 → Feather RX/TX)
- Pins: A0/A1/A2, A10/A11, A5 (not raw GPIO numbers)
- USB CDC: disabled for stability
- UART tests: heartbeat and echo confirmed

### Step‑by‑Step Recovery Flow (Concise)
1) Verify Pi UART works  
   - Short Pi pins 8↔10  
   - Run loopback script → expect echo  
2) Verify Feather UART pins  
   - Use silkscreen TX/RX pins  
   - Use firmware heartbeat  
3) Disable USB CDC  
4) Correct pin mapping  
5) Re‑enable peripherals one by one  
   - ADC → Ultrasonic → PWM  
6) Observe stability after each step

### What a Technician Should Do (No Detours)
- Verify Pi UART loopback passes.
- Use Feather silkscreen TX/RX pins.
- Flash UART heartbeat firmware.
- Confirm UART traffic on `/dev/serial0`.
- Use Feather alias pins for ADC and D‑pins.
- Re‑enable peripherals one by one.

### Preventative Measures (Project Start)
- Always use board aliases (A0, A1, A2, TX, RX, A10, etc.).
- Check `pins_arduino.h` for the exact board variant.
- Add a “safe mode” boot path from day 1.
- Use UART for telemetry if USB stability is uncertain.
- Add a boot delay before peripheral init.
- Initialize outputs LOW before enabling PWM or external loads.

### Ensuring This Doesn’t Happen Again (This Project)
- Lock pin mapping in documentation and firmware constants.
- Keep a “safe‑mode” build path (compile‑time flag).
- Use UART as the primary debug transport.
- Add a `reset_reason` log to UART to detect brownouts.
- Reconnect sensors one by one with tests after every change.