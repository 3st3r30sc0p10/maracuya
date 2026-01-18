Cursor Rules: Hailo Live Inference + Naming/Hesitation Policy
0. Non-negotiables

Do not change model outputs. The HEF inference returns raw scores; we only change the policy that maps scores → state.

NumPy constraint: enforce numpy<2. If environment has NumPy 2.x, downgrade to 1.x.

Hailo API: use hailo_platform 4.20.0 APIs only. Do not use deprecated methods like ConfiguredNetwork.make_input_vstream_params() or VDevice.create_configure_params().

1. Environment & runtime assumptions

Python: 3.11.x

hailo_platform: 4.20.0

Interface: hpf.HailoStreamInterface.PCIe

Input tensor: RGB uint8, shape (1, 512, 512, 3), contiguous

Output stream: maracuya_yolo/yolov8_nms_postprocess (or first output if name differs)

Rule: Print version + IO info at startup:

hailo_platform version

numpy version

HEF path

input vstreams + output vstreams (names, shapes, types)

2. Camera acquisition rules (proof-tested pipeline)

Priority order:

Picamera2 RGB888

OpenCV VideoCapture(/dev/video0) fallback

Picamera2 rules:

Configure preview:

main={"size": (512,512), "format": "RGB888"}

Capture from "main" stream:

rgb = picam2.capture_array("main")

Validate frame:

ndarray, shape (512,512,3), dtype uint8

Convert for display only:

bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

Fallback rule:

If Picamera2 cannot guarantee RGB888, fallback to OpenCV

Always resize OpenCV frames to 512x512

Blue tint mitigation:

Provide Picamera2-only controls:

Toggle AWB

Manual ColourGains warm/cool adjustments

This is a display correction, not required for inference.

3. Hailo inference rules (proof-tested API usage)

Configuration:

hef = hpf.HEF(HEF_PATH)

with hpf.VDevice() as vdevice:

configure_params = hpf.ConfigureParams.create_from_hef(hef, interface=PCIe)

ng = vdevice.configure(hef, configure_params)[0]

Vstream params:

Inputs:

hpf.InputVStreamParams.make_from_network_group(ng, quantized=True, format_type=hpf.FormatType.UINT8)

Outputs:

hpf.OutputVStreamParams.make_from_network_group(ng, quantized=False, format_type=hpf.FormatType.FLOAT32)

Activation + infer:

with ng.activate(ng.create_params()):

with hpf.InferVStreams(ng, in_params, out_params) as pipe:

Run:

result = pipe.infer({input_name: input_tensor})

Do NOT pass batch_size kwarg to infer.

Input tensor construction (hard rule):

take camera frame_bgr

convert to frame_rgb

input_tensor = np.ascontiguousarray(frame_rgb[np.newaxis, ...], dtype=np.uint8)

4. Output decoding rules (current tested structure)

Output is a dict keyed by stream name. For yolov8_nms_postprocess:

result[out_key] is list with length = batch size (1)

result[out_key][0] is list of classes (len=2)

each class element is ndarray shape (N,5) with rows:

[x1, y1, x2, y2, score]

Rule: treat those as candidate detections; if N==0, no detections for that class.

Known issue rule: sometimes boxes are (0,0,0,0) or tiny. Do not trust boxes until validated.

Only draw if:

abs(x2-x1) >= MIN_BOX_SIZE and abs(y2-y1) >= MIN_BOX_SIZE

Always trust scores for policy logic.

Normalization rule:

Support a flag NORMALIZED=0/1

If normalized, multiply x by W and y by H.

5. Naming / hesitation policy rules (the conceptual core)

We have two class names: NAME_A, NAME_B (e.g. "maracuyá", "passion fruit").
They denote two names for the same object.

Do not treat classes as different material states.

Per frame compute:

sA = best score for class A (if any)

sB = best score for class B (if any)

top = max(sA, sB)

gap = abs(sA - sB)

Then compute thresholds from sensors (rubber/fabric):

decision threshold T from rubber

ambiguity margin M from fabric

State machine (strict):

if top < T → NO_DECISION

else if gap <= M and both scores exist → AMBIGUOUS

else → DECIDED (winner = argmax score)

Rule: Ambiguity is the priority output state.

6. Sensor integration rules (rubber + fabric → policy)

Backend reads two sensors each frame (or at fixed rate), normalized to [0,1]:

rubber → r

fabric → f

Apply smoothing:

rubber smoothing fast:

r_s = (1-αr)*r_s + αr*r, αr ≈ 0.20

fabric smoothing slow:

f_s = (1-αf)*f_s + αf*f, αf ≈ 0.05

Map to parameters:

Rubber controls k widely

k = 0.02 + r_s * (0.60 - 0.02)

Convert k to decision threshold:

T = T_min + k*(T_max - T_min)

defaults: T_min=0.05, T_max=0.60

Fabric controls ambiguity margin slowly

M = 0.25 + f_s * (0.50 - 0.25)

Hysteresis rule to avoid flicker:

Use T_enter = T + h, T_exit = T - h (e.g. h=0.02)

Only switch into decision when top > T_enter

Only switch out when top < T_exit

7. Balancing rule (optional, preserves ambiguity)

Purpose: prevent one name from always dominating due to training bias, without faking hesitation.

Hard constraints:

Do not modify raw model outputs.

Do not update balancing during ambiguous frames.

Mechanism:

Maintain per-class bias offsets:

biasA, biasB in range [-0.25, +0.25]

Calibrated score:

s_cal = clip(s_raw + bias[class], 0..1)

Use calibrated scores for:

thresholding

winner selection

ambiguity detection

Update biases ONLY on clear DECIDED frames:

Keep rolling winner history window, size 200

Target ratio for A: 0.50 by default

Update step:

err = fracA - targetA

biasA -= lr*err

biasB += lr*err

lr ~ 0.002

Never update on AMBIGUOUS

8. Backend↔Frontend protocol rules (WebSocket “policy packet”)

Backend must publish a JSON packet every frame (or at fixed fps, e.g. 30):

Required fields:

{
  "ts": 0,
  "scores_raw": {"A": 0.0, "B": 0.0},
  "scores_cal": {"A": 0.0, "B": 0.0},
  "top": 0.0,
  "gap": 0.0,
  "T": 0.0,
  "M": 0.0,
  "k": 0.0,
  "rubber": {"raw": 0.0, "norm": 0.0, "smooth": 0.0},
  "fabric": {"raw": 0.0, "norm": 0.0, "smooth": 0.0},
  "state": "NO_DECISION|AMBIGUOUS|DECIDED",
  "winner": "A|B|null",
  "detections": [
    {"name":"A","score_raw":0.0,"score_cal":0.0,"box":[0,0,0,0]},
    {"name":"B","score_raw":0.0,"score_cal":0.0,"box":[0,0,0,0]}
  ]
}


Frontend rules:

overlay bounding boxes if valid size

show label text based on state:

NO_DECISION: “withhold”

AMBIGUOUS: show both names simultaneously, blended visuals

DECIDED: show winner strongly

show live gauges for T and M (audience sees policy control)

9. Console logging rules (for debugging + documentation)

Backend prints to console only on events:

when state changes

or every 0.25s while ambiguous

Log format:

AMBIGUOUS:

timestamp + both names + raw & cal scores + gap + T + M

DECIDED:

timestamp + winner name + raw & cal score + T + M

10. Implementation structure rules (files, responsibilities)

Create these modules:

camera.py

Camera class (Picamera2 + fallback)

WB controls

hailo_infer.py

HEF load, network group config

infer_frame(frame_rgb_uint8) -> decoded scores + det arrays

policy.py

smoothing + hysteresis

rubber/fabric mapping → k, T, M

state machine + ambiguity

optional balancing

server.py

WebSocket loop

emits policy packets at frame rate

ui/ (JS frontend)

renders video, overlays boxes, blends videos, displays gauges

Rule: No module should mix camera IO + inference + policy + networking in one file except a small main.py glue.