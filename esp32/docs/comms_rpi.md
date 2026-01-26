## ESP32 to Raspberry Pi comms

Planned link: Wi-Fi or UART (final choice TBD).

Data to transmit:
- Proximity value (filtered)
- Stretch sensor value (filtered)
- Fabric touch or pressure value (filtered)
- LED brightness level (for telemetry)

## UART (recommended when USB is unstable)

### Wiring (Pi 5 ↔ ESP32-S3 Feather)
- Pi GPIO14 (TXD, pin 8) -> Feather RX (GPIO38)
- Pi GPIO15 (RXD, pin 10) -> Feather TX (GPIO39)
- Pi GND (pin 6) -> Feather GND

### Pi setup
- Disable serial login shell, keep UART enabled:
  `sudo raspi-config` -> Interface Options -> Serial Port
  - Login shell over serial: **No**
  - Serial port hardware: **Yes**

### Notes
- UART is 3.3V logic; no level shifting needed.
- Firmware prints JSON lines to `Serial0` (UART0 on GPIO43/44) at 115200 baud.
