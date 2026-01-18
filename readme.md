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
