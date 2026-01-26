#Activate venv
source /home/rasp-navigator/pio-venv/bin/activate

## ESP32 subsystem

This folder is a PlatformIO project for the Adafruit ESP32-S3 Feather that controls
the 12V white LED strip (via proximity sensor) and reads conductive rubber +
fabric inputs. Sensor data is streamed over USB serial to the Raspberry Pi backend.

### Structure
- `platformio.ini` PlatformIO project config
- `src/main.cpp` firmware source
- `docs/` wiring notes, pin map, and comms overview

### Quick start (PlatformIO)

1. Open this folder in VS Code with the PlatformIO extension.
2. Upload to the Feather:

```
pio run -t upload
```

Monitor serial output:
### Serial link

The firmware prints one JSON packet per line over USB serial. The Pi reads the
serial port (for example `/dev/ttyACM0`) and forwards packets into the backend
sensor pipeline.

```
pio device monitor
```

### Quick hardware notes
- The LED strip is 12V and must be driven through a MOSFET (low-side switch).
- ESP32 PWM is 3.3V; share ground between the 12V supply and ESP32.
- Proximity sensor should output 0-3.3V for ADC input (use a divider if needed).

### Default pin mapping (Adafruit ESP32-S3 Feather)

- `D5` (GPIO5) -> LED PWM (MOSFET gate)
- `A0` (GPIO1) -> proximity sensor (ADC input)
- `A1` (GPIO2) -> conductive rubber (ADC input)
- `A2` (GPIO3) -> conductive fabric (ADC input)

Reference: Adafruit ESP32-S3 Feather pinout guide:
https://learn.adafruit.com/adafruit-esp32-s3-feather/pinouts
