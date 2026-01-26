## Pin map

These defaults can be changed in the firmware.

### Left column (top → bottom)
- BAT
- EN
- USB
- 13
- 12
- 11
- 10
- 9
- 6
- 5
- SCL
- SDA

### Right column (top → bottom)
- RST
- 3V
- 3V
- GND
- A0
- A1
- A2
- A3
- A4
- A5
- SCK
- MD
- RX
- TX
- DB

### Firmware pin usage
- LED PWM output: `A5` → GPIO8
- Proximity sensor ADC input: `A0` → GPIO18
- Conductive rubber input: `A1` → GPIO17
- Conductive fabric input: `A2` → GPIO16
- Ultrasonic TRIG: `A10` → GPIO9
- Ultrasonic ECHO: `A11` → GPIO10 (level-shifted)
- UART TX: `TX` → GPIO39
- UART RX: `RX` → GPIO38