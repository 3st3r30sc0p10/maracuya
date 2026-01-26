How to run the application:

- Run backend:
sudo systemctl start maracuya-backend
Manually:
cd /home/rasp-navigator/maracuya/maracuya
source /home/rasp-navigator/hailo-env/bin/activate
python -m backend.main

- Run the application in the raspberry pi browser:
DISPLAY=:0 chromium-browser --start-fullscreen http://localhost:8000

- Check backend status:
sudo systemctl status maracuya-backend

- View backend logs:
sudo journalctl -u maracuya-backend -f

---

## TROUBLESHOOTING

### 1. Hailo Device Disconnected / Driver Failure
**Symptoms:**
- `[HailoRT] [error] Failed to open device file /dev/hailo0`
- `[HailoRT] [error] HAILO_DRIVER_OPERATION_FAILED(36)`
- `dmesg | grep hailo` shows "Device disconnected while opening device"

**Solution:**
```bash
sudo reboot
```
The Hailo accelerator sometimes loses connection after long runs or errors. A full reboot is required to reset the PCIe device.

### 2. Port 8000 Already in Use
**Symptoms:**
- `ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8000): address already in use`

**Solution:**
```bash
# Kill any existing backend processes
pkill -f 'backend.main' || true
# Wait and restart
sleep 2
sudo systemctl restart maracuya-backend
```

### 3. Camera in Use by Another Process
**Symptoms:**
- `Pipeline handler in use by another process`
- `Camera __init__ sequence did not complete`

**Solution:**
```bash
# Kill any processes using the camera
pkill -f libcamera || true
pkill -f rpicam || true
sudo systemctl restart maracuya-backend
```

### 4. HEF Model File Not Found
**Symptoms:**
- `[HailoRT] [error] Error opening file /hailo/maracuya_yolo.hef`
- `HAILO_OPEN_FILE_FAILURE(13)`

**Solution:**
The model file path is configured in the systemd service. Check that the file exists:
```bash
ls -la /home/rasp-navigator/models/maracuya_yolo.hef
```
If missing, copy the model file to that location.

### 5. ESP32 Serial Connection Issues
**Symptoms:**
- No sensor data (rubber/fabric values stuck at 0)
- Serial port errors

**Solution:**
```bash
# Check ESP32 is connected
ls -la /dev/ttyACM0
# Test serial output
python3 -c "import serial; s=serial.Serial('/dev/serial0',115200,timeout=1); print(s.readline())"
```
If ESP32 is not responding, check wiring (TX→RX, RX→TX, GND→GND).

### 6. Backend Service Won't Start After Changes
**Solution:**
```bash
# Reload systemd after service file changes
sudo cp /home/rasp-navigator/maracuya/maracuya/scripts/maracuya-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart maracuya-backend
```

### 7. Browser Shows Black Screen / No Video
**Symptoms:**
- WebGL initialized but no video feed
- WebSocket connected but blank canvas

**Solution:**
1. Hard refresh browser: `Ctrl+Shift+R`
2. Check backend is running: `sudo systemctl status maracuya-backend`
3. Check for JavaScript errors: Open browser DevTools (F12) → Console

### 8. Full Reset Procedure
If nothing works, do a complete reset:
```bash
# Stop everything
sudo systemctl stop maracuya-backend
pkill -f chromium || true
pkill -f 'backend.main' || true

# Reboot
sudo reboot

# After reboot, wait 30 seconds, then:
sudo systemctl status maracuya-backend
DISPLAY=:0 chromium-browser --start-fullscreen http://localhost:8000
```

---

#upload files
cd /home/rasp-navigator/maracuya/maracuya/esp32 && /home/rasp-navigator/pio-venv/bin/pio run -t upload --upload-port /dev/ttyACM0

- Test sensors:
python3 - <<'PY'
import serial, time
ser = serial.Serial('/dev/serial0', 115200, timeout=1)
print('listening...')
start = time.time()
while time.time() - start < 5:
    line = ser.readline().decode(errors='replace').strip()
    if line:
        print(line)
PY

#Kill and Run Backend:
pkill -f 'backend.main' || true
cd /home/rasp-navigator/maracuya/maracuya
source /home/rasp-navigator/hailo-env/bin/activate
export MARACUYA_HEF=/home/rasp-navigator/models/maracuya_yolo.hef
SIM_CAMERA=0 SIM_SENSORS=0 SIM_INFERENCE=0 python -m backend.main

#Load UI in browser (MacOS):
http://192.168.1.131:8000

# Maracuya Tri-State Fruit Classifier

Real-time installation system for Raspberry Pi 5 + Hailo-8 that exposes the
epistemic tension between binary classification and liminal ambiguity.

## Repository Layout

- `backend/`: FastAPI backend, MJPEG stream, WebSocket updates
- `frontend/`: fullscreen UI with overlays and HUD
- `esp32/`: firmware scaffold for sensor input

## Raspberry Pi OS Setup

1. Install Raspberry Pi OS (64-bit) and complete basic setup.
2. Update packages:

```
sudo apt update && sudo apt upgrade -y
```

## Picamera2 (Raspberry Pi AI Camera)

Picamera2 is installed from apt on Raspberry Pi OS:

```
sudo apt install -y python3-picamera2
```

Verify the camera:

```
libcamera-hello -t 2000
```

## HailoRT

Install HailoRT for your Raspberry Pi 5 following the vendor guide:

- Install the HailoRT runtime
- Confirm `hailortcli` works

## Model (.hef)

Copy your compiled `.hef` to the Pi and set the path:

```
mkdir -p /home/pi/models
cp your_model.hef /home/pi/models/maracuya.hef
```

Optionally override via environment:

```
export MARACUYA_HEF=/path/to/your.hef
```

## Backend Setup

```
cd /home/pi/maracuya
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## Run (Dev)

```
./backend/scripts/run_backend.sh
```

Note: run via the script or `python -m backend.main` from the repo root. Running
`backend/main.py` directly will fail due to relative imports.

Open the UI in a browser:

```
http://<pi-ip>:8000
```

## Systemd Service

```
sudo cp backend/systemd/maracuya-install.service /etc/systemd/system/maracuya.service
sudo systemctl daemon-reload
sudo systemctl enable maracuya.service
sudo systemctl start maracuya.service
```

Check logs:

```
journalctl -u maracuya.service -f
```

## Sensor Simulation

If the ESP32 is offline, the backend simulates rubber/fabric inputs to keep
the tri-state logic active. Disable simulation by setting:

```
export SIM_SENSORS=false
```

## Serial Sensor Input

The backend reads ESP32 sensor data from the UART device by default. Override
the serial port and baud rate if needed:

```
export SERIAL_PORT=/dev/serial0
export SERIAL_BAUD=115200
```

## ESP32

See `esp32/README.md` for firmware setup and wiring guidance.
- Initiate and Activate environment:
  $ module purge
  $ module load Anaconda3/2024.02
  $ conda activate maracuya
  $ Deactivate environment: $ conda deactivate
- Choose kernel: YOLO Rejection (Py3.10)

#Python version: 3.10.19

#What the environment installation included:

- Python 3.10.19
- Core C/C++ runtime libraries (libgcc, libstdc++, OpenMP)
- OpenSSL 3.0.x (modern, secure)
- pip / setuptools / wheel (modern)
- Tk, X11 libs (needed for matplotlib & OpenCV GUIs)

#Extra core requirements:

- YOLOv8 training
- Multi-class ambiguity (same image → two labels)
- Confidence threshold manipulation
- Access to logits / probabilities (rejection region)
- ONNX export (for Hailo later)
- GPU training on cluster
- Later CPU / accelerator inference on Raspberry Pi

#Libraries:

- GPU & numerical backbone (CONDA):
  -- conda install -y numpy=1.26.4 scipy=1.11.4
- PyTorch + CUDA (CRITICAL):
  -- conda install -y pytorch=2.1 torchvision torchaudio pytorch-cuda=11.8 -c pytorch -c nvidia
- Vision & data handling (CONDA). But before these installations, run these commands:
  -- conda config --add channels conda-forge
  -- conda config --set channel_priority strict
- And then, install the dependencies:
  -- conda install -y opencv=4.9 pillow=10.2 matplotlib=3.8
- Jupyter integration (CONDA):
  -- conda install -y jupyterlab ipykernel
  -- Then register the kernel: python -m ipykernel install --user --name yolo_rejection --display-name "YOLO Rejection (Py3.10)"
- YOLOv8 & tooling (PIP):
  -- pip install ultralytics==8.1.47
- Optional but highly recommended tools:
  -- pip install seaborn==0.13.2
  -- pip install pandas==2.2.2
  -- pip install tqdm==4.66.4
  -- pip install onnx==1.16.0 onnxruntime==1.17.3
- For clearer ONNX:
  -- pip install onnxsim==0.4.36

  ##Full stack libraries:

- Python: 3.10.19
- NumPy: 1.26.x
- PyTorch: 2.1.x
- OpenCV: 4.9.x
- matplotlib: 3.8.x
- seaborn: 0.13.2
- pandas: 2.2.2
- ONNX: 1.16.0

##Cluster server configuration:

- Environment setup:
  -- module purge
  -- module load Anaconda3/2021.05
  -- module list
  -- source activate maracuya
  -- module list
- Partition:
  -- gpu-common
- CPU Threats:
  -- 16
- Memory:
  -- 48Gb
- GPUs:
  -- 1
