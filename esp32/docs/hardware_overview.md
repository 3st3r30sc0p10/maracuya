## Hardware overview

### Components
- ESP32 dev board
- Ultra Flexible White LED Strip, 12V, 10W/m
- Logic-level N-channel MOSFET (for PWM dimming)
- Proximity sensor (analog output)
- Conductive fabric (future input)
- Conductive rubber stretch sensor (future input)

### Wiring summary
- LED strip +12V to 12V supply
- LED strip GND to MOSFET drain
- MOSFET source to ground
- MOSFET gate to ESP32 PWM pin with a 100-220 ohm resistor
- ESP32 GND tied to 12V supply ground (common ground)
- Proximity sensor output to ESP32 ADC pin (0-3.3V range)
