/**
 * Maracuya WebGL 4-Layer Compositor
 * 
 * Three epistemological regimes:
 * - PASSION FRUIT: Colonial/market - hyper-legibility, stability, possession
 * - MARACUYÁ: Animist/situated - material resistance, vitality, relation
 * - AMBIGUOUS: Political praxis - co-presence, negotiation, refusal of closure
 */

// ============ Configuration ============
const CONFIG = {
  // Smoothing time constants (ms)
  FAST_SMOOTH_MS: 150,
  SLOW_SMOOTH_MS: 800,
  
  // Hysteresis thresholds
  AMB_ENTER_GAP: 0.08,
  AMB_EXIT_GAP: 0.15,
  
  // Debug
  DEBUG: true
};

// ============ State ============
const state = {
  // Raw values from backend
  conf_pass: 0,
  conf_mara: 0,
  amb_score: 0,
  rubber_k: 0,
  frame_id: 0,
  bboxes: [],
  backend_state: "",
  backend_winner: "",
  T: 0,
  M: 0,
  
  // Smoothed weights for layers (0-1)
  w_pass: 0,
  w_mara: 0,
  w_amb: 0,
  
  // Epistemic mode: "passion", "maracuya", "ambiguous"
  mode: "ambiguous",
  modeBlend: { passion: 0, maracuya: 0, ambiguous: 1 },
  
  // Timing
  lastUpdate: performance.now(),
  frameCount: 0,
  
  // Previous frame for feedback
  prevFrameData: null,
  
  // Debug overlay
  showDebug: false,
  
  // ===== Epistemic Feedback Panel =====
  // Rubber influence tracking (for Threshold Tension Bar)
  rubber_raw: 0,           // Current raw rubber value from backend
  rubber_smooth: 0,        // Fast-smoothed rubber value (what visitor is doing NOW)
  rubber_influence: 0,     // Slow-lagged value (what system has "accepted")
  influence_strength: 0,   // How close to flipping a class (0-1)
  
  // Latency pulse detection
  pulses: [],              // Active pulses [{t0, strength, duration}]
  lastDominance: null,     // Previous dominant class for flip detection
  lastRubberChangeTime: 0, // When rubber last changed significantly
  lastRubberValue: 0,      // For detecting rubber movement
  
  // Previous confidences for change detection
  prev_conf_pass: 0,
  prev_conf_mara: 0
};

// ============ DOM Elements ============
const canvas = document.getElementById("gl-canvas");
const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
const hudState = document.getElementById("state-label");
const hudWinner = document.getElementById("winner-label");
const hudT = document.getElementById("t-value");
const hudM = document.getElementById("m-value");

// ============ WebGL Resources ============
let program = null;
let quadBuffer = null;
const textures = {
  live: null,
  feedback: null
};

// Framebuffer for feedback
let feedbackFBO = null;
let feedbackTexture = null;

// ============ Shader Sources ============
const VERTEX_SHADER = `
attribute vec2 a_position;
varying vec2 v_uv;
void main() {
  v_uv = a_position * 0.5 + 0.5;
  v_uv.y = 1.0 - v_uv.y;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = `
precision mediump float;

varying vec2 v_uv;

uniform sampler2D u_texLive;
uniform sampler2D u_texFeedback;

uniform float u_time;
uniform float u_wPassion;    // Passion fruit weight (0-1)
uniform float u_wMaracuya;   // Maracuya weight (0-1)
uniform float u_wAmbiguous;  // Ambiguous weight (0-1)
uniform float u_rubberK;     // Rubber cord input (0-1)
// Multiple bounding boxes (up to 8)
uniform vec4 u_bboxes[8];    // Bounding boxes (x, y, w, h) normalized 0-1
uniform int u_numBboxes;     // Number of active bboxes

// ============ Noise Functions ============
float rand(vec2 co) {
  return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  float a = rand(i);
  float b = rand(i + vec2(1.0, 0.0));
  float c = rand(i + vec2(0.0, 1.0));
  float d = rand(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

// Fractal Brownian Motion - multi-octave noise
float fbm(vec2 p, int octaves) {
  float value = 0.0;
  float amplitude = 0.5;
  float frequency = 1.0;
  for (int i = 0; i < 6; i++) {
    if (i >= octaves) break;
    value += amplitude * noise(p * frequency);
    frequency *= 2.0;
    amplitude *= 0.5;
  }
  return value;
}

// Ridged noise for mycelium/fiber patterns
float ridgedNoise(vec2 p) {
  return 1.0 - abs(noise(p) * 2.0 - 1.0);
}

// Multi-octave ridged noise for branching structures
float ridgedFbm(vec2 p, int octaves) {
  float value = 0.0;
  float amplitude = 0.6;
  float frequency = 1.0;
  float weight = 1.0;
  for (int i = 0; i < 5; i++) {
    if (i >= octaves) break;
    float n = ridgedNoise(p * frequency);
    n *= weight;
    weight = clamp(n * 2.0, 0.0, 1.0);
    value += amplitude * n;
    frequency *= 2.2;
    amplitude *= 0.5;
  }
  return value;
}

// Sharpening kernel (for passion fruit)
vec3 sharpen(sampler2D tex, vec2 uv, float strength) {
  vec2 step = vec2(1.0 / 512.0);
  vec3 center = texture2D(tex, uv).rgb * (1.0 + 4.0 * strength);
  center -= texture2D(tex, uv + vec2(-step.x, 0.0)).rgb * strength;
  center -= texture2D(tex, uv + vec2(step.x, 0.0)).rgb * strength;
  center -= texture2D(tex, uv + vec2(0.0, -step.y)).rgb * strength;
  center -= texture2D(tex, uv + vec2(0.0, step.y)).rgb * strength;
  return center;
}

// Single bounding box mask with soft edges
// Returns 1.0 inside bbox, 0.0 outside, smooth transition at edges
float singleBboxMask(vec2 uv, vec4 bbox, float softness) {
  if (bbox.z <= 0.0 || bbox.w <= 0.0) return 0.0;
  
  // bbox is (x, y, w, h) where x,y is top-left corner (normalized 0-1)
  vec2 bboxMin = bbox.xy;
  vec2 bboxMax = bbox.xy + bbox.zw;
  
  // Distance from edges (negative inside, positive outside)
  float left = bboxMin.x - uv.x;
  float right = uv.x - bboxMax.x;
  float top = bboxMin.y - uv.y;
  float bottom = uv.y - bboxMax.y;
  
  // Smooth edges
  float maskL = 1.0 - smoothstep(-softness, softness, left);
  float maskR = 1.0 - smoothstep(-softness, softness, right);
  float maskT = 1.0 - smoothstep(-softness, softness, top);
  float maskB = 1.0 - smoothstep(-softness, softness, bottom);
  
  return maskL * maskR * maskT * maskB;
}

// Combined mask for all bounding boxes
float allBboxesMask(vec2 uv, float softness) {
  float mask = 0.0;
  for (int i = 0; i < 8; i++) {
    if (i >= u_numBboxes) break;
    mask = max(mask, singleBboxMask(uv, u_bboxes[i], softness));
  }
  return mask;
}

// Get y-factor within combined bboxes (0 at top, 1 at bottom) - for gravity bias
float getBboxYFactor(vec2 uv) {
  float yFactor = 0.0;
  float totalWeight = 0.0;
  for (int i = 0; i < 8; i++) {
    if (i >= u_numBboxes) break;
    vec4 bbox = u_bboxes[i];
    if (bbox.z <= 0.0 || bbox.w <= 0.0) continue;
    
    float weight = singleBboxMask(uv, bbox, 0.02);
    if (weight > 0.01) {
      // Y position within this bbox (0 = top, 1 = bottom)
      float localY = (uv.y - bbox.y) / bbox.w;
      localY = clamp(localY, 0.0, 1.0);
      yFactor += localY * weight;
      totalWeight += weight;
    }
  }
  return totalWeight > 0.0 ? yFactor / totalWeight : 0.5;
}

// Get center distance within combined bboxes (0 at center, 1 at edges)
float getBboxCenterDist(vec2 uv) {
  float centerDist = 1.0;
  for (int i = 0; i < 8; i++) {
    if (i >= u_numBboxes) break;
    vec4 bbox = u_bboxes[i];
    if (bbox.z <= 0.0 || bbox.w <= 0.0) continue;
    
    // Center of this bbox
    vec2 center = bbox.xy + bbox.zw * 0.5;
    // Normalized distance from center (0-1 within bbox)
    vec2 d = (uv - center) / (bbox.zw * 0.5);
    float dist = length(d);
    centerDist = min(centerDist, dist);
  }
  return clamp(centerDist, 0.0, 1.0);
}

void main() {
  vec2 uv = v_uv;
  float t = u_time;
  
  // Compute combined object mask from all bounding boxes (soft edges for blending)
  float objectMask = (u_numBboxes > 0) ? allBboxesMask(uv, 0.03) : 0.0;
  
  // Sample base image
  vec4 color = texture2D(u_texLive, uv);
  vec4 baseColor = color;  // Keep original for compositing
  
  // ========== PASSION FRUIT EFFECT (applied to background, or everywhere if passion fruit mode) ==========
  vec4 passionColor = baseColor;
  float passionWeight = max(u_wPassion, max(u_wMaracuya, u_wAmbiguous));  // Apply to background in maracuya/ambiguous
  
  if (passionWeight > 0.01) {
    // STRONG sharpening - maximum clarity/resolution
    vec3 sharpened = sharpen(u_texLive, uv, passionWeight * 0.8);
    passionColor.rgb = mix(passionColor.rgb, sharpened, passionWeight * 0.9);
    
    // Apply second pass of sharpening for ultra-crisp edges
    sharpened = sharpen(u_texLive, uv, passionWeight * 0.5);
    passionColor.rgb = mix(passionColor.rgb, sharpened, passionWeight * 0.4);
    
    // HIGH contrast - dramatic, gloomy blacks, bright whites
    passionColor.rgb = (passionColor.rgb - 0.5) * (1.0 + passionWeight * 0.6) + 0.5;
    
    // Lift shadows slightly for "studio lighting" feel
    passionColor.rgb = mix(passionColor.rgb, smoothstep(0.0, 1.0, passionColor.rgb), passionWeight * 0.3);
    
    // Over-lit: push brightness, make it pop
    passionColor.rgb += passionWeight * 0.08;
    
    // Warm golden tones - desirable, appetizing
    passionColor.r += passionWeight * 0.06;
    passionColor.g += passionWeight * 0.04;
    
    // Boost saturation for salience (opposite of desaturation)
    float gray = dot(passionColor.rgb, vec3(0.299, 0.587, 0.114));
    passionColor.rgb = mix(vec3(gray), passionColor.rgb, 1.0 + passionWeight * 0.25);
    
    // Strong specular highlight exaggeration - glossy, commercial look
    float highlight = max(0.0, (gray - 0.6) * 4.0);
    passionColor.rgb += highlight * passionWeight * 0.25;
    
    // Vignette: subtle darkening at edges to focus attention on center
    float vignette = 1.0 - length(uv - 0.5) * passionWeight * 0.4;
    passionColor.rgb *= vignette;
    
    // Clamp to prevent overflow
    passionColor.rgb = clamp(passionColor.rgb, 0.0, 1.0);
  }
  
  // ========== MARACUYÁ: RGB SHIFT (object-only) ==========
  vec4 rgbShiftColor = baseColor;
  if (u_wMaracuya > 0.01 && objectMask > 0.01) {
    float intensity = u_wMaracuya * objectMask;
    float shift = 0.012 + 0.036 * intensity;
    float wobble = sin(t * 1.7 + uv.y * 12.0) * 0.008 * intensity;
    vec2 shiftR = vec2(shift + wobble, 0.0);
    vec2 shiftB = vec2(-shift + wobble, 0.0);
    float r = texture2D(u_texLive, uv + shiftR).r;
    float g = texture2D(u_texLive, uv).g;
    float b = texture2D(u_texLive, uv + shiftB).b;
    rgbShiftColor = vec4(r, g, b, 1.0);
    // Subtle luminance drift for spectral shimmer
    float glow = sin((uv.x + uv.y) * 20.0 + t * 2.0) * 0.5 + 0.5;
    rgbShiftColor.rgb = mix(rgbShiftColor.rgb, rgbShiftColor.rgb * 1.1, glow * intensity * 0.15);
    rgbShiftColor.rgb = clamp(rgbShiftColor.rgb, 0.0, 1.0);
  }

  // ========== AMBIGUOUS: CLASSIC GLITCH (object-only) ==========
  vec4 glitchColor = baseColor;
  if (u_wAmbiguous > 0.01 && objectMask > 0.01) {
    float intensity = u_wAmbiguous * objectMask;
    vec2 glitchUV = uv;
    
    // ===== 1) RGB CHANNEL SPLIT =====
    float rgbOffset = intensity * 0.015;
    float r = texture2D(u_texLive, uv + vec2(rgbOffset, 0.0)).r;
    float g = texture2D(u_texLive, uv).g;
    float b = texture2D(u_texLive, uv - vec2(rgbOffset, 0.0)).b;
    glitchColor = vec4(r, g, b, 1.0);
    
    // ===== 2) HORIZONTAL BLOCK DISPLACEMENT =====
    float blockSize = 0.03 + noise(vec2(t * 0.5, 0.0)) * 0.02;
    float blockY = floor(uv.y / blockSize);
    float blockRand = rand(vec2(blockY, floor(t * 4.0)));
    
    if (blockRand > 0.7) {
      float displacement = (blockRand - 0.7) * 0.15 * intensity;
      if (mod(blockY, 2.0) < 1.0) displacement = -displacement;
      
      vec2 displaceUV = uv + vec2(displacement, 0.0);
      vec4 displaced = texture2D(u_texLive, displaceUV);
      glitchColor = mix(glitchColor, displaced, 0.8);
      
      // Extra RGB split on displaced blocks
      glitchColor.r = texture2D(u_texLive, displaceUV + vec2(rgbOffset * 1.5, 0.0)).r;
      glitchColor.b = texture2D(u_texLive, displaceUV - vec2(rgbOffset * 1.5, 0.0)).b;
    }
    
    // ===== 3) SCAN LINES =====
    float scanLine = sin(uv.y * 400.0) * 0.5 + 0.5;
    scanLine = pow(scanLine, 1.5);
    glitchColor.rgb *= 1.0 - scanLine * intensity * 0.15;
    
    // ===== 4) HORIZONTAL TEARS =====
    float tearNoise = noise(vec2(uv.y * 10.0, t * 3.0));
    if (tearNoise > 0.85) {
      float tearOffset = (tearNoise - 0.85) * 0.3 * intensity;
      glitchColor.rgb = texture2D(u_texLive, uv + vec2(tearOffset, 0.0)).rgb;
    }
    
    // ===== 5) COLOR POSTERIZATION =====
    float levels = mix(32.0, 8.0, intensity * 0.5);
    glitchColor.rgb = floor(glitchColor.rgb * levels) / levels;
    
    // ===== 6) NOISE BURSTS =====
    float noiseBurst = rand(vec2(floor(uv.y * 50.0), floor(t * 8.0)));
    if (noiseBurst > 0.92) {
      float noiseVal = rand(uv * 500.0 + t);
      glitchColor.rgb = mix(glitchColor.rgb, vec3(noiseVal), intensity * 0.6);
    }
    
    // ===== 7) TEMPORAL FEEDBACK =====
    vec4 feedback = texture2D(u_texFeedback, uv);
    glitchColor = mix(glitchColor, feedback, intensity * 0.25);
    
    // ===== 8) COLOR SHIFT =====
    glitchColor.r += intensity * 0.05;
    glitchColor.g -= intensity * 0.02;
    
    // Clamp
    glitchColor.rgb = clamp(glitchColor.rgb, 0.0, 1.0);
  }
  
  // ========== COMPOSITE: Blend passion fruit background with glitched object ==========
  if (u_wMaracuya > 0.01) {
    // In maracuya mode: background is passion fruit crisp, object RGB shifts
    color = mix(passionColor, rgbShiftColor, objectMask * u_wMaracuya);
  } else if (u_wAmbiguous > 0.01) {
    // In ambiguous mode: background is passion fruit crisp, object glitches
    color = mix(passionColor, glitchColor, objectMask * u_wAmbiguous);
  } else if (u_wPassion > 0.01) {
    // In passion fruit mode: everything is crisp
    color = passionColor;
  }
  
  // Clamp output
  color.rgb = clamp(color.rgb, 0.0, 1.0);
  color.a = 1.0;
  
  gl_FragColor = color;
}
`;

// ============ WebGL Initialization ============
function initWebGL() {
  if (!gl) {
    console.error("[webgl] WebGL not supported");
    return false;
  }
  
  const vs = compileShader(gl.VERTEX_SHADER, VERTEX_SHADER);
  const fs = compileShader(gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  if (!vs || !fs) return false;
  
  program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error("[webgl] Program link error:", gl.getProgramInfoLog(program));
    return false;
  }
  
  quadBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    -1, -1,  1, -1,  -1, 1,
    -1,  1,  1, -1,   1, 1
  ]), gl.STATIC_DRAW);
  
  textures.live = createTexture();
  textures.feedback = createTexture();
  
  // Create framebuffer for feedback effect
  feedbackFBO = gl.createFramebuffer();
  feedbackTexture = createTexture();
  
  if (CONFIG.DEBUG) console.log("[webgl] initialized");
  return true;
}

function compileShader(type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error("[webgl] Shader compile error:", gl.getShaderInfoLog(shader));
    return null;
  }
  return shader;
}

function createTexture() {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0,0,0,255]));
  return tex;
}

function updateTexture(tex, source) {
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
}

// ============ WebSocket Connections ============
let wsState = null;
let wsFrames = null;
let liveImage = new Image();

function connectWebSockets() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const host = location.host;
  
  wsState = new WebSocket(`${protocol}://${host}/ws`);
  wsState.onopen = () => { if (CONFIG.DEBUG) console.log("[ws] state connected"); };
  wsState.onclose = () => { 
    console.warn("[ws] state disconnected, reconnecting...");
    setTimeout(connectWebSockets, 1500);
  };
  wsState.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      state.conf_pass = data.conf_pass || 0;
      state.conf_mara = data.conf_mara || 0;
      state.amb_score = data.amb_score || 0;
      state.rubber_k = data.rubber_k || 0;
      // Debug: log rubber values occasionally
      if (state.frameCount % 100 === 0) {
        console.log("[ws] rubber_k:", state.rubber_k.toFixed(3), "smooth:", state.rubber_smooth.toFixed(3), "influence:", state.rubber_influence.toFixed(3));
      }
      state.frame_id = data.frame_id || 0;
      state.bboxes = data.bboxes || [];
      state.backend_state = data.state || "";
      state.backend_winner = data.winner || "";
      state.T = data.T || 0;
      state.M = data.M || 0;
      updateHUD(data);
    } catch (e) {
      console.warn("[ws] parse error", e);
    }
  };
  
  wsFrames = new WebSocket(`${protocol}://${host}/ws/frames`);
  wsFrames.binaryType = "arraybuffer";
  wsFrames.onopen = () => { if (CONFIG.DEBUG) console.log("[ws] frames connected"); };
  wsFrames.onclose = () => { console.warn("[ws] frames disconnected"); };
  wsFrames.onmessage = (evt) => {
    const data = new Uint8Array(evt.data);
    const jpegData = data.slice(4);
    const blob = new Blob([jpegData], { type: "image/jpeg" });
    const url = URL.createObjectURL(blob);
    liveImage.onload = () => URL.revokeObjectURL(url);
    liveImage.src = url;
  };
}

// ============ Mode & Weight Computation ============
function computeWeights(dt) {
  // Determine epistemic mode from backend - discrete states
  let targetPassion = 0, targetMaracuya = 0, targetAmbiguous = 0;
  
  if (state.backend_state === "AMBIGUOUS") {
    // Full ambiguity - no other modes
    targetAmbiguous = 1.0;
    targetPassion = 0.0;
    targetMaracuya = 0.0;
    state.mode = "ambiguous";
  } else if (state.backend_state === "DECIDED") {
    // Clear decision - ambiguity completely off
    targetAmbiguous = 0.0;
    if (state.backend_winner === "A") {
      targetMaracuya = 1.0;
      targetPassion = 0.0;
      state.mode = "maracuya";
    } else if (state.backend_winner === "B") {
      targetPassion = 1.0;
      targetMaracuya = 0.0;
      state.mode = "passion";
    }
  } else {
    // No decision yet - show ambiguous
    targetAmbiguous = 1.0;
    targetPassion = 0.0;
    targetMaracuya = 0.0;
    state.mode = "ambiguous";
  }
  
  // Smooth weights - faster transition when leaving ambiguous
  const alphaOut = 1 - Math.exp(-dt / CONFIG.FAST_SMOOTH_MS);  // Fast exit from ambiguous
  const alphaIn = 1 - Math.exp(-dt / CONFIG.SLOW_SMOOTH_MS);   // Slow entry to ambiguous
  
  // Use faster smoothing when target is 0 (exiting a mode)
  const alphaPass = targetPassion > state.w_pass ? alphaIn : alphaOut;
  const alphaMara = targetMaracuya > state.w_mara ? alphaIn : alphaOut;
  const alphaAmb = targetAmbiguous > state.w_amb ? alphaIn : alphaOut;
  
  state.w_pass += (targetPassion - state.w_pass) * alphaPass;
  state.w_mara += (targetMaracuya - state.w_mara) * alphaMara;
  state.w_amb += (targetAmbiguous - state.w_amb) * alphaAmb;
  
  // Clamp very small values to 0 for clean transitions
  if (state.w_pass < 0.01) state.w_pass = 0;
  if (state.w_mara < 0.01) state.w_mara = 0;
  if (state.w_amb < 0.01) state.w_amb = 0;
  
  // Update mode blend for other uses
  state.modeBlend.passion = state.w_pass;
  state.modeBlend.maracuya = state.w_mara;
  state.modeBlend.ambiguous = state.w_amb;
}

// ============ Rendering ============
function render() {
  const now = performance.now();
  const dt = now - state.lastUpdate;
  state.lastUpdate = now;
  state.frameCount++;
  
  computeWeights(dt);
  
  // Update epistemic feedback tracking
  updateRubberInfluence(dt);
  detectPulses();
  cleanupPulses();
  
  // Resize canvas - "cover" mode
  const sourceAspect = 1.0;
  const windowW = window.innerWidth;
  const windowH = window.innerHeight;
  const windowAspect = windowW / windowH;
  
  let canvasW, canvasH, offsetX, offsetY;
  
  if (windowAspect > sourceAspect) {
    canvasW = windowW;
    canvasH = windowW / sourceAspect;
    offsetX = 0;
    offsetY = (windowH - canvasH) / 2;
  } else {
    canvasH = windowH;
    canvasW = windowH * sourceAspect;
    offsetX = (windowW - canvasW) / 2;
    offsetY = 0;
  }
  
  if (canvas.width !== canvasW || canvas.height !== canvasH) {
    canvas.width = canvasW;
    canvas.height = canvasH;
    canvas.style.left = offsetX + "px";
    canvas.style.top = offsetY + "px";
    canvas.style.width = canvasW + "px";
    canvas.style.height = canvasH + "px";
    gl.viewport(0, 0, canvasW, canvasH);
    
    overlayCanvas.width = canvasW;
    overlayCanvas.height = canvasH;
    overlayCanvas.style.left = offsetX + "px";
    overlayCanvas.style.top = offsetY + "px";
    overlayCanvas.style.width = canvasW + "px";
    overlayCanvas.style.height = canvasH + "px";
    
    // Resize feedback texture
    gl.bindTexture(gl.TEXTURE_2D, feedbackTexture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, canvasW, canvasH, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  }
  
  // Update live texture
  if (liveImage.complete && liveImage.naturalWidth > 0) {
    updateTexture(textures.live, liveImage);
  }
  
  // Draw
  gl.useProgram(program);
  
  // Bind textures
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, textures.live);
  gl.uniform1i(gl.getUniformLocation(program, "u_texLive"), 0);
  
  gl.activeTexture(gl.TEXTURE1);
  gl.bindTexture(gl.TEXTURE_2D, feedbackTexture);
  gl.uniform1i(gl.getUniformLocation(program, "u_texFeedback"), 1);
  
  // Set uniforms
  gl.uniform1f(gl.getUniformLocation(program, "u_time"), now / 1000.0);
  gl.uniform1f(gl.getUniformLocation(program, "u_wPassion"), state.w_pass);
  gl.uniform1f(gl.getUniformLocation(program, "u_wMaracuya"), state.w_mara);
  gl.uniform1f(gl.getUniformLocation(program, "u_wAmbiguous"), state.w_amb);
  gl.uniform1f(gl.getUniformLocation(program, "u_rubberK"), state.rubber_k);
  
  // Pass all bounding boxes to shader (up to 8)
  const maxBboxes = 8;
  const numBboxes = Math.min(state.bboxes ? state.bboxes.length : 0, maxBboxes);
  gl.uniform1i(gl.getUniformLocation(program, "u_numBboxes"), numBboxes);
  
  for (let i = 0; i < maxBboxes; i++) {
    const loc = gl.getUniformLocation(program, `u_bboxes[${i}]`);
    if (i < numBboxes && state.bboxes[i]) {
      const bbox = state.bboxes[i];
      gl.uniform4f(loc, bbox.x, bbox.y, bbox.w, bbox.h);
    } else {
      gl.uniform4f(loc, 0.0, 0.0, 0.0, 0.0);
    }
  }
  
  // Draw quad
  const posLoc = gl.getAttribLocation(program, "a_position");
  gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
  gl.enableVertexAttribArray(posLoc);
  gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);
  gl.drawArrays(gl.TRIANGLES, 0, 6);
  
  // Copy current frame to feedback texture for next frame
  gl.bindTexture(gl.TEXTURE_2D, feedbackTexture);
  gl.copyTexImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 0, 0, canvas.width, canvas.height, 0);
  
  // Draw bounding boxes and typography
  drawOverlay();
  
  requestAnimationFrame(render);
}

// ============ Overlay: Bounding Boxes & Typography ============
const overlayCanvas = document.getElementById("overlay");
const ctx = overlayCanvas.getContext("2d");

function drawOverlay() {
  ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  
  const w = overlayCanvas.width;
  const h = overlayCanvas.height;
  const t = performance.now() / 1000;
  
  // Always draw epistemic panel and debug, even without bboxes
  if (!state.bboxes || state.bboxes.length === 0) {
    drawEpistemicPanel();
    if (state.showDebug) drawDebugOverlay();
    return;
  }
  
  state.bboxes.forEach(bbox => {
    let x = bbox.x * w;
    let y = bbox.y * h;
    let bw = bbox.w * w;
    let bh = bbox.h * h;
    
    // ========== PASSION FRUIT: Stable, locked, authoritative ==========
    if (state.mode === "passion" && state.w_pass > 0.3) {
      // Perfect rectangles, no jitter
      ctx.strokeStyle = "#FFD700"; // Warm gold
      ctx.lineWidth = 3;
      ctx.strokeRect(x, y, bw, bh);
      
      // Typography: clean, corporate, assertive
      const label = "PASSION FRUIT";
      ctx.font = "bold 18px 'Helvetica Neue', Arial, sans-serif";
      ctx.textBaseline = "bottom";
      
      const textW = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(0,0,0,0.75)";
      ctx.fillRect(x, y - 28, textW + 16, 26);
      
      ctx.fillStyle = "#FFFFFF";
      ctx.fillText(label, x + 8, y - 6);
      
      // Confidence as small text
      const conf = `${(bbox.score * 100).toFixed(0)}%`;
      ctx.font = "12px 'Helvetica Neue', Arial, sans-serif";
      ctx.fillStyle = "#FFD700";
      ctx.fillText(conf, x + textW + 12, y - 8);
    }
    
    // ========== MARACUYÁ: Breathing, provisional, relational ==========
    else if (state.mode === "maracuya" && state.w_mara > 0.3) {
      // Slight wobble - edges breathe
      const wobble = Math.sin(t * 2) * 2 * state.w_mara;
      const breathe = 1 + Math.sin(t * 1.5) * 0.02 * state.w_mara;
      
      x += wobble;
      y += Math.cos(t * 2.3) * 1.5 * state.w_mara;
      bw *= breathe;
      bh *= breathe;
      
      // Organic color: earth tones
      ctx.strokeStyle = `rgba(139, 195, 74, ${0.7 + Math.sin(t) * 0.2})`;
      ctx.lineWidth = 2 + Math.sin(t * 3) * 0.5;
      ctx.strokeRect(x, y, bw, bh);
      
      // Typography: organic, drifting baseline
      const label = "maracuyá";
      const baselineDrift = Math.sin(t * 1.2) * 2;
      
      ctx.font = "italic 17px Georgia, serif";
      ctx.textBaseline = "bottom";
      
      const textW = ctx.measureText(label).width;
      ctx.fillStyle = `rgba(30,30,20,${0.6 + Math.sin(t * 0.8) * 0.15})`;
      ctx.fillRect(x + wobble * 0.5, y - 26 + baselineDrift, textW + 14, 24);
      
      // Letter opacity fluctuates
      ctx.fillStyle = `rgba(200, 230, 180, ${0.85 + Math.sin(t * 2) * 0.1})`;
      ctx.fillText(label, x + 7 + wobble * 0.3, y - 5 + baselineDrift);
    }
    
    // ========== AMBIGUOUS: Neutral bbox (glitch handled in shader) ==========
    else {
      ctx.strokeStyle = "rgba(220, 220, 220, 0.7)";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x, y, bw, bh);
      
      ctx.font = "12px 'Helvetica Neue', Arial, sans-serif";
      ctx.textBaseline = "bottom";
      ctx.fillStyle = "rgba(220, 220, 220, 0.8)";
      ctx.fillText("ambiguous", x + 6, y - 6);
    }
  });
  
  // Always draw epistemic feedback panel
  drawEpistemicPanel();
  
  if (state.showDebug) drawDebugOverlay();
}

function drawDebugOverlay() {
  ctx.fillStyle = "rgba(0,0,0,0.8)";
  ctx.fillRect(10, 10, 220, 200);
  
  ctx.fillStyle = "#fff";
  ctx.font = "11px monospace";
  let y = 28;
  const line = (text) => { ctx.fillText(text, 20, y); y += 15; };
  
  line(`MODE: ${state.mode}`);
  line(`---`);
  line(`w_passion:  ${state.w_pass.toFixed(3)}`);
  line(`w_maracuya: ${state.w_mara.toFixed(3)}`);
  line(`w_ambiguous: ${state.w_amb.toFixed(3)}`);
  line(`---`);
  line(`conf_pass: ${state.conf_pass.toFixed(3)}`);
  line(`conf_mara: ${state.conf_mara.toFixed(3)}`);
  line(`rubber_k: ${state.rubber_k.toFixed(3)}`);
  line(`---`);
  line(`backend: ${state.backend_state} / ${state.backend_winner}`);
  line(`frame: ${state.frame_id}`);
}

// ============ Epistemic Feedback Panel ============

// Update rubber influence tracking (called each frame)
function updateRubberInfluence(dt) {
  const now = performance.now();
  
  // Fast smoothing for "now" indicator (100-200ms)
  const alphaNow = 1 - Math.exp(-dt / 120);
  state.rubber_smooth += (state.rubber_k - state.rubber_smooth) * alphaNow;
  
  // Slow smoothing for "influence" (system absorption) (600-1000ms)
  const alphaInfluence = 1 - Math.exp(-dt / 800);
  state.rubber_influence += (state.rubber_k - state.rubber_influence) * alphaInfluence;
  
  // Compute influence strength: how close to flipping a class?
  // Based on confidence gap - closer gap = more influence potential
  const gap = Math.abs(state.conf_pass - state.conf_mara);
  const gapNormalized = Math.max(0, 1 - gap * 5); // 0 gap = 1.0, 0.2+ gap = 0
  state.influence_strength = state.rubber_k * gapNormalized;
  
  // Detect significant rubber movement for latency tracking
  const rubberDelta = Math.abs(state.rubber_k - state.lastRubberValue);
  if (rubberDelta > 0.05) {
    state.lastRubberChangeTime = now;
    state.lastRubberValue = state.rubber_k;
  }
}

// Detect classification changes and spawn pulses
function detectPulses() {
  const now = performance.now();
  
  // Determine current dominance
  let currentDominance = "ambiguous";
  if (state.backend_state === "DECIDED") {
    currentDominance = state.backend_winner === "A" ? "maracuya" : "passion";
  }
  
  // Detect dominance flip
  if (state.lastDominance !== null && state.lastDominance !== currentDominance) {
    // A flip occurred - spawn a pulse
    const timeSinceRubberChange = now - state.lastRubberChangeTime;
    const latencyMs = Math.min(timeSinceRubberChange, 2000); // Cap at 2s
    
    // Strength based on confidence change magnitude
    const confChange = Math.abs(state.conf_pass - state.prev_conf_pass) + 
                       Math.abs(state.conf_mara - state.prev_conf_mara);
    const strength = Math.min(1, confChange * 2 + 0.3);
    
    // Duration: longer if more latency
    const duration = 400 + latencyMs * 0.3;
    
    state.pulses.push({
      t0: now,
      strength: strength,
      duration: duration,
      latencyMs: latencyMs
    });
    
    // Keep only last 4 pulses
    if (state.pulses.length > 4) {
      state.pulses.shift();
    }
  }
  
  // Also detect significant confidence shifts (not just flips)
  const confShift = Math.abs(state.conf_pass - state.prev_conf_pass) + 
                    Math.abs(state.conf_mara - state.prev_conf_mara);
  if (confShift > 0.15 && state.rubber_k > 0.1) {
    // Minor pulse for significant confidence movement
    const timeSinceRubberChange = now - state.lastRubberChangeTime;
    if (timeSinceRubberChange < 1500) { // Only if rubber moved recently
      state.pulses.push({
        t0: now,
        strength: confShift * 0.5,
        duration: 300,
        latencyMs: timeSinceRubberChange
      });
      
      if (state.pulses.length > 4) {
        state.pulses.shift();
      }
    }
  }
  
  state.lastDominance = currentDominance;
  state.prev_conf_pass = state.conf_pass;
  state.prev_conf_mara = state.conf_mara;
}

// Clean up expired pulses
function cleanupPulses() {
  const now = performance.now();
  state.pulses = state.pulses.filter(p => (now - p.t0) < p.duration);
}

// Draw the epistemic feedback panel (bottom-right)
function drawEpistemicPanel() {
  const w = overlayCanvas.width;
  const h = overlayCanvas.height;
  const now = performance.now();
  
  // Get the visible window size vs canvas size ratio
  const displayW = parseFloat(overlayCanvas.style.width) || w;
  const displayH = parseFloat(overlayCanvas.style.height) || h;
  const scaleX = w / displayW;
  const scaleY = h / displayH;
  
  // Debug: log once
  if (state.frameCount % 300 === 1) {
    console.log("[panel] canvas:", w, h, "display:", displayW, displayH, "scale:", scaleX.toFixed(2), scaleY.toFixed(2));
  }
  
  // Skip if canvas not ready
  if (w <= 0 || h <= 0) {
    console.warn("[panel] canvas not ready:", w, h);
    return;
  }
  
  // Panel positioning (bottom-right of VISIBLE area)
  // Account for canvas offset if it's positioned off-screen
  const offsetX = parseFloat(overlayCanvas.style.left) || 0;
  const offsetY = parseFloat(overlayCanvas.style.top) || 0;
  
  // Calculate visible area in canvas coordinates
  const visibleRight = Math.min(w, (window.innerWidth - offsetX) * scaleX);
  const visibleBottom = Math.min(h, (window.innerHeight - offsetY) * scaleY);
  
  const panelRight = visibleRight - 30 * scaleX;
  const panelBottom = visibleBottom - 40 * scaleY;
  
  // ===== PANEL BACKGROUND =====
  const panelWidth = 280;
  const panelHeight = 80;
  const panelX = panelRight - panelWidth;
  const panelY = panelBottom - panelHeight;
  
  // Semi-transparent background with border
  ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
  ctx.fillRect(panelX - 10, panelY - 10, panelWidth + 20, panelHeight + 30);
  ctx.strokeStyle = "rgba(255, 255, 255, 0.3)";
  ctx.lineWidth = 1;
  ctx.strokeRect(panelX - 10, panelY - 10, panelWidth + 20, panelHeight + 30);
  
  // ===== 1) THRESHOLD TENSION BAR =====
  const barWidth = 220;
  const barHeight = 12;
  const barX = panelRight - barWidth;
  const barY = panelBottom - barHeight;
  
  // Background track (more visible)
  ctx.fillStyle = "rgba(60, 60, 60, 0.9)";
  ctx.fillRect(barX, barY, barWidth, barHeight);
  
  // Fill: rubber_influence (lagged value - what system has "accepted")
  const fillWidth = state.rubber_influence * barWidth;
  
  // Yellow gradient: dim -> intense based on influence
  const kInfluence = Math.max(0, Math.min(1, state.rubber_influence));
  const yellowG = Math.round(160 + 70 * kInfluence);
  const yellowB = Math.round(40 + 80 * kInfluence);
  const yellowA = 0.35 + 0.65 * kInfluence;
  const barColor = `rgba(255, ${yellowG}, ${yellowB}, ${yellowA})`;
  ctx.fillStyle = barColor;
  ctx.fillRect(barX, barY, fillWidth, barHeight);
  
  // Stretch waves: show yellow oscillation when cord is active
  const kNow = Math.max(0, Math.min(1, state.rubber_k));
  if (kNow > 0.02) {
    const t = now * 0.001;
    const waveAmp = 2 + 4 * kNow;
    ctx.beginPath();
    for (let x = 0; x <= barWidth; x += 6) {
      const wx = barX + x;
      const wy = barY - 10 + Math.sin(t * 4 + x * 0.05) * waveAmp;
      if (x === 0) {
        ctx.moveTo(wx, wy);
      } else {
        ctx.lineTo(wx, wy);
      }
    }
    ctx.strokeStyle = `rgba(255, ${Math.round(180 + 60 * kNow)}, ${Math.round(60 + 80 * kNow)}, ${0.2 + 0.6 * kNow})`;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  
  // Ghost marker: rubber_smooth (current input - where visitor is NOW)
  const ghostX = barX + state.rubber_smooth * barWidth;
  ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
  ctx.fillRect(ghostX - 1, barY - 2, 2, barHeight + 4);
  
  // Influence strength indicator (subtle glow/thickness when high)
  if (state.influence_strength > 0.3) {
    const glowAlpha = (state.influence_strength - 0.3) * 0.8;
    ctx.fillStyle = `rgba(255, 255, 255, ${glowAlpha * 0.3})`;
    ctx.fillRect(barX, barY - 2, fillWidth, barHeight + 4);
  }
  
  // Label
  ctx.font = "11px monospace";
  ctx.fillStyle = "rgba(200, 200, 200, 0.9)";
  ctx.textAlign = "right";
  ctx.fillText("THRESHOLD PRESSURE", panelRight, barY - 8);
  
  // Show current rubber value as text
  ctx.font = "10px monospace";
  ctx.fillStyle = `rgba(255, ${Math.round(180 + 60 * kNow)}, ${Math.round(60 + 80 * kNow)}, 0.9)`;
  ctx.fillText(`${(state.rubber_k * 100).toFixed(0)}%`, panelRight, barY + barHeight + 14);
  
  // ===== 2) LATENCY PULSE RING =====
  const ringCenterX = barX - 40;
  const ringCenterY = barY + barHeight / 2;
  const baseRadius = 18;
  
  // Draw each active pulse
  state.pulses.forEach(pulse => {
    const elapsed = now - pulse.t0;
    const progress = Math.min(1, elapsed / pulse.duration);
    
    // Easing: fast start, slow end
    const eased = 1 - Math.pow(1 - progress, 2);
    
    // Ring expands as pulse progresses
    const radius = baseRadius + eased * 15 * (1 + pulse.latencyMs / 2000);
    
    // Opacity fades out
    const opacity = (1 - eased) * pulse.strength * 0.8;
    
    // Ring thickness decreases
    const thickness = 2 + (1 - eased) * 2;
    
    // Color based on mode
    let ringColor;
    if (state.mode === "passion") {
      ringColor = `rgba(255, 215, 0, ${opacity})`;
    } else if (state.mode === "maracuya") {
      ringColor = `rgba(139, 195, 74, ${opacity})`;
    } else {
      ringColor = `rgba(200, 200, 200, ${opacity})`;
    }
    
    ctx.beginPath();
    ctx.arc(ringCenterX, ringCenterY, radius, 0, Math.PI * 2);
    ctx.strokeStyle = ringColor;
    ctx.lineWidth = thickness;
    ctx.stroke();
  });
  
  // Static center dot (shows pulse origin point)
  ctx.beginPath();
  ctx.arc(ringCenterX, ringCenterY, 4, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(255, 255, 255, ${0.4 + state.rubber_k * 0.5})`;
  ctx.fill();
  
  // Static ring outline (always visible)
  ctx.beginPath();
  ctx.arc(ringCenterX, ringCenterY, baseRadius, 0, Math.PI * 2);
  ctx.strokeStyle = "rgba(100, 100, 100, 0.5)";
  ctx.lineWidth = 1;
  ctx.stroke();
  
  // Label for pulse ring
  ctx.font = "8px monospace";
  ctx.fillStyle = "rgba(120, 120, 120, 0.7)";
  ctx.textAlign = "center";
  ctx.fillText("YIELD", ringCenterX, ringCenterY + baseRadius + 12);
  
  // Reset text align
  ctx.textAlign = "left";
}

// ============ HUD Update ============
function updateHUD(data) {
  if (hudState) hudState.textContent = `state: ${(data.state || "--").toLowerCase()}`;
  if (hudWinner) {
    if (data.state === "DECIDED" && data.winner) {
      const name = data.winner === "A" ? "maracuyá" : "passion fruit";
      hudWinner.textContent = `winner: ${name}`;
    } else if (data.state === "AMBIGUOUS") {
      hudWinner.textContent = "winner: contested";
    } else {
      hudWinner.textContent = "winner: --";
    }
  }
  if (hudT) hudT.textContent = (data.T || 0).toFixed(3);
  if (hudM) hudM.textContent = (data.M || 0).toFixed(3);
}

// ============ Keyboard Handler ============
document.addEventListener("keydown", (e) => {
  if (e.key === "d" || e.key === "D") {
    state.showDebug = !state.showDebug;
  }
});

// ============ Initialize ============
function init() {
  if (!initWebGL()) {
    console.error("[init] WebGL initialization failed");
    return;
  }
  
  connectWebSockets();
  requestAnimationFrame(render);
  
  if (CONFIG.DEBUG) console.log("[init] Maracuya epistemological compositor started");
}

init();
