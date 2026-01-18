const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");
const mjpeg = document.getElementById("mjpeg");
const video = document.getElementById("state-video");
const stateLabel = document.getElementById("state-label");
const winnerLabel = document.getElementById("winner-label");
const tValue = document.getElementById("t-value");
const mValue = document.getElementById("m-value");

const stateVideos = {
  A: "/assets/maracuya_overlay.mp4",
  B: "/assets/passionfruit_overlay.mp4",
  AMBIGUOUS: "/assets/ambiguous_overlay.mp4",
  NO_DECISION: "/assets/ambiguous_overlay.mp4",
};

function resizeCanvas() {
  canvas.width = mjpeg.clientWidth || window.innerWidth;
  canvas.height = mjpeg.clientHeight || window.innerHeight;
}

window.addEventListener("resize", resizeCanvas);
mjpeg.addEventListener("load", resizeCanvas);
resizeCanvas();

function setState(state, winner, labels) {
  const safeState = state || "NO_DECISION";
  document.body.className = `state-${safeState}`;
  let videoKey = safeState;
  if (safeState === "DECIDED") {
    videoKey = winner || "AMBIGUOUS";
  }
  const videoSrc = stateVideos[videoKey] || stateVideos.AMBIGUOUS;
  if (video.dataset.key !== videoKey) {
    video.dataset.key = videoKey;
    video.src = videoSrc;
    video.play().catch(() => {});
  }
  stateLabel.textContent = `state: ${safeState.toLowerCase()}`;
  if (safeState === "AMBIGUOUS" && labels) {
    winnerLabel.textContent = `winner: ${labels.A} + ${labels.B}`;
  } else if (safeState === "DECIDED" && labels) {
    winnerLabel.textContent = `winner: ${winner === "A" ? labels.A : labels.B}`;
  } else {
    winnerLabel.textContent = "winner: withhold";
  }
}

function colorFor(name) {
  if (name === "A") return "#56ff99";
  if (name === "B") return "#ffb347";
  return "#ffe066";
}

function drawDetections(detections) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!detections || detections.length === 0) return;
  const frameWidth = canvas.width;
  const frameHeight = canvas.height;
  ctx.lineWidth = 3;
  ctx.font = "16px Helvetica";
  ctx.textBaseline = "top";

  detections.forEach((det) => {
    const [x1, y1, x2, y2] = det.box || [0, 0, 0, 0];
    if (x2 - x1 <= 0 || y2 - y1 <= 0) return;
    const color = colorFor(det.name);
    const left = x1 * (frameWidth / 512);
    const top = y1 * (frameHeight / 512);
    const width = (x2 - x1) * (frameWidth / 512);
    const height = (y2 - y1) * (frameHeight / 512);
    ctx.strokeStyle = color;
    ctx.strokeRect(left, top, width, height);
    const label = `${det.label} ${det.score_cal.toFixed(2)}`;
    ctx.fillStyle = "rgba(0,0,0,0.55)";
    ctx.fillRect(left, top - 22, ctx.measureText(label).width + 14, 22);
    ctx.fillStyle = color;
    ctx.fillText(label, left + 6, top - 20);
  });
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      const labels = {
        A: data?.detections?.[0]?.label || "A",
        B: data?.detections?.[1]?.label || "B",
      };
      setState(data.state, data.winner, labels);
      tValue.textContent = Number(data.T).toFixed(3);
      mValue.textContent = Number(data.M).toFixed(3);
      drawDetections(data.detections || []);
    } catch (err) {
      console.warn("WS parse error", err);
    }
  };

  ws.onclose = () => {
    setTimeout(connectWebSocket, 1500);
  };
}

connectWebSocket();
