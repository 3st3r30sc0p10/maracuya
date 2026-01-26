from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Deque, Dict, Optional

from .config import BackendConfig
from .sensors import SensorState


@dataclass
class PolicyResult:
    packet: Dict
    state: str
    winner: Optional[str]


class PolicyEngine:
    # Score smoothing alpha (higher = more responsive, lower = more stable)
    SCORE_ALPHA = 0.15
    # State hysteresis: require N consecutive frames in a state before switching
    STATE_HOLD_FRAMES = 1  # Immediate state changes for responsive rubber control
    # Ambiguity margin range - controlled by fabric sensor
    # M_MIN: minimum margin (fabric relaxed) - low ambiguity zone
    # M_MAX: maximum margin (fabric stretched) - high ambiguity zone
    M_MIN = 0.20
    M_MAX = 0.35

    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._bias_a = 0.0
        self._bias_b = 0.0
        self._decision_active = False
        self._history: Deque[str] = deque(maxlen=config.bias_window)
        self._last_state: Optional[str] = None
        self._last_ambig_log = 0.0
        # Score smoothing state
        self._smooth_a = 0.0
        self._smooth_b = 0.0
        self._initialized_scores = False
        # State hysteresis
        self._pending_state: Optional[str] = None
        self._pending_winner: Optional[str] = None
        self._pending_count = 0
        self._confirmed_state = "NO_DECISION"
        self._confirmed_winner: Optional[str] = None

    def evaluate(
        self,
        scores_raw: Dict[str, float],
        boxes: Dict[str, list],
        has_a: bool,
        has_b: bool,
        sensors: SensorState,
    ) -> PolicyResult:
        # Compute thresholds from rubber sensor - use RAW norm for instant response
        # rubber_norm is immediate, rubber_smooth has slight lag for display smoothness
        rubber_instant = sensors.rubber_norm  # Immediate response
        k = 0.02 + rubber_instant * (0.60 - 0.02)
        t = self._config.t_min + k * (self._config.t_max - self._config.t_min)
        # Ambiguity margin - fixed base, rubber expands it
        m_base = self.M_MIN  # Fixed base (fabric influence removed)
        # Rubber stretching expands the ambiguity zone (makes AMBIGUOUS more likely)
        m = m_base + rubber_instant * 0.20  # Add up to 0.20 when fully stretched
        t_enter = t + self._config.hysteresis
        t_exit = max(0.0, t - self._config.hysteresis)
        
        # Rubber also affects class bias - stretching shifts toward balance
        # When stretched, reduce the dominant class's advantage
        # Strong effect: up to 0.40 shift can flip winner when model is uncertain
        rubber_bias_shift = rubber_instant * 0.40

        # Get raw scores
        s_a_raw = float(scores_raw.get("A", 0.0))
        s_b_raw = float(scores_raw.get("B", 0.0))

        # Apply score smoothing (EMA) to reduce flickering
        if not self._initialized_scores:
            self._smooth_a = s_a_raw
            self._smooth_b = s_b_raw
            self._initialized_scores = True
        else:
            self._smooth_a = (1 - self.SCORE_ALPHA) * self._smooth_a + self.SCORE_ALPHA * s_a_raw
            self._smooth_b = (1 - self.SCORE_ALPHA) * self._smooth_b + self.SCORE_ALPHA * s_b_raw

        # Use smoothed scores for policy (but report raw in packet)
        # Apply rubber-based rebalancing: when stretched, boost the weaker score
        # and reduce the stronger score, pushing toward ambiguity
        if self._smooth_a >= self._smooth_b:
            # A is stronger - rubber reduces A, boosts B
            s_a_cal = self._clip(self._smooth_a + self._bias_a - rubber_bias_shift)
            s_b_cal = self._clip(self._smooth_b + self._bias_b + rubber_bias_shift)
        else:
            # B is stronger - rubber reduces B, boosts A
            s_a_cal = self._clip(self._smooth_a + self._bias_a + rubber_bias_shift)
            s_b_cal = self._clip(self._smooth_b + self._bias_b - rubber_bias_shift)

        top = max(s_a_cal, s_b_cal)
        gap = abs(s_a_cal - s_b_cal)

        # Decision activation hysteresis (unchanged)
        if self._decision_active:
            if top < t_exit:
                self._decision_active = False
        else:
            if top > t_enter:
                self._decision_active = True

        # Compute raw state (before state hysteresis)
        raw_state = "NO_DECISION"
        raw_winner = None
        if self._decision_active:
            # When rubber is stretched (>25%), force winner to flip
            # Use rubber_instant (raw norm) for immediate response to stretching
            if rubber_instant > 0.25:
                # Force switch to the weaker class
                raw_state = "DECIDED"
                raw_winner = "B" if self._smooth_a >= self._smooth_b else "A"
            elif gap <= m and has_a and has_b:
                raw_state = "AMBIGUOUS"
            else:
                raw_state = "DECIDED"
                raw_winner = "A" if s_a_cal >= s_b_cal else "B"

        # Apply state hysteresis: require N consecutive frames before switching
        if raw_state == self._pending_state and raw_winner == self._pending_winner:
            self._pending_count += 1
        else:
            self._pending_state = raw_state
            self._pending_winner = raw_winner
            self._pending_count = 1

        if self._pending_count >= self.STATE_HOLD_FRAMES:
            self._confirmed_state = self._pending_state
            self._confirmed_winner = self._pending_winner

        state = self._confirmed_state
        winner = self._confirmed_winner

        if state == "DECIDED" and winner:
            self._history.append(winner)
            self._update_biases()

        packet = {
            "ts": time.time(),
            "scores_raw": {"A": s_a_raw, "B": s_b_raw},
            "scores_smooth": {"A": self._smooth_a, "B": self._smooth_b},
            "scores_cal": {"A": s_a_cal, "B": s_b_cal},
            "top": top,
            "gap": gap,
            "T": t,
            "M": m,
            "k": k,
            "rubber": {
                "raw": sensors.rubber_raw,
                "norm": sensors.rubber_norm,
                "smooth": sensors.rubber_smooth,
            },
            "fabric": {
                "raw": sensors.fabric_raw,
                "norm": sensors.fabric_norm,
                "smooth": sensors.fabric_smooth,
            },
            "state": state,
            "raw_state": raw_state,  # Pre-hysteresis state for debugging
            "winner": winner,
            "detections": [
                {
                    "name": "A",
                    "label": self._config.name_a,
                    "score_raw": s_a_raw,
                    "score_smooth": self._smooth_a,
                    "score_cal": s_a_cal,
                    "box": boxes.get("A", [0, 0, 0, 0]),
                    "detected": has_a,
                },
                {
                    "name": "B",
                    "label": self._config.name_b,
                    "score_raw": s_b_raw,
                    "score_smooth": self._smooth_b,
                    "score_cal": s_b_cal,
                    "box": boxes.get("B", [0, 0, 0, 0]),
                    "detected": has_b,
                },
            ],
        }
        self._maybe_log(state, winner, packet)
        return PolicyResult(packet=packet, state=state, winner=winner)

    def _update_biases(self) -> None:
        if not self._history:
            return
        count_a = sum(1 for item in self._history if item == "A")
        frac_a = count_a / len(self._history)
        err = frac_a - self._config.target_ratio_a
        self._bias_a = self._clip_bias(self._bias_a - self._config.bias_lr * err)
        self._bias_b = self._clip_bias(self._bias_b + self._config.bias_lr * err)

    def _maybe_log(self, state: str, winner: Optional[str], packet: Dict) -> None:
        now = time.time()
        should_log = False
        if state != self._last_state:
            should_log = True
            self._last_state = state
        elif state == "AMBIGUOUS" and (now - self._last_ambig_log) >= self._config.ambiguous_log_interval:
            should_log = True
        if not should_log:
            return
        self._last_ambig_log = now
        # Show smoothed scores in logs
        s_a = packet["scores_smooth"]["A"]
        s_b = packet["scores_smooth"]["B"]
        if state == "AMBIGUOUS":
            print(
                f"[{now:.2f}] AMBIGUOUS {self._config.name_a}={s_a:.2f} "
                f"{self._config.name_b}={s_b:.2f} gap={packet['gap']:.3f} "
                f"T={packet['T']:.3f} M={packet['M']:.3f}"
            )
        elif state == "DECIDED" and winner:
            label = self._config.name_a if winner == "A" else self._config.name_b
            score = packet["scores_smooth"][winner]
            print(
                f"[{now:.2f}] DECIDED {label}={score:.2f} "
                f"T={packet['T']:.3f} M={packet['M']:.3f}"
            )
        elif state == "NO_DECISION":
            print(
                f"[{now:.2f}] NO_DECISION top={packet['top']:.2f} "
                f"T={packet['T']:.3f}"
            )

    def _clip(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def _clip_bias(self, value: float) -> float:
        return max(-self._config.bias_limit, min(self._config.bias_limit, value))
