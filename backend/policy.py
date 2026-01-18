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
    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._bias_a = 0.0
        self._bias_b = 0.0
        self._decision_active = False
        self._history: Deque[str] = deque(maxlen=config.bias_window)
        self._last_state: Optional[str] = None
        self._last_ambig_log = 0.0

    def evaluate(
        self,
        scores_raw: Dict[str, float],
        boxes: Dict[str, list],
        has_a: bool,
        has_b: bool,
        sensors: SensorState,
    ) -> PolicyResult:
        k = 0.02 + sensors.rubber_smooth * (0.60 - 0.02)
        t = self._config.t_min + k * (self._config.t_max - self._config.t_min)
        m = 0.25 + sensors.fabric_smooth * (0.50 - 0.25)
        t_enter = t + self._config.hysteresis
        t_exit = max(0.0, t - self._config.hysteresis)

        s_a_raw = float(scores_raw.get("A", 0.0))
        s_b_raw = float(scores_raw.get("B", 0.0))
        s_a_cal = self._clip(s_a_raw + self._bias_a)
        s_b_cal = self._clip(s_b_raw + self._bias_b)

        top = max(s_a_cal, s_b_cal)
        gap = abs(s_a_cal - s_b_cal)

        if self._decision_active:
            if top < t_exit:
                self._decision_active = False
        else:
            if top > t_enter:
                self._decision_active = True

        state = "NO_DECISION"
        winner = None
        if self._decision_active:
            if gap <= m and has_a and has_b:
                state = "AMBIGUOUS"
            else:
                state = "DECIDED"
                winner = "A" if s_a_cal >= s_b_cal else "B"

        if state == "DECIDED" and winner:
            self._history.append(winner)
            self._update_biases()

        packet = {
            "ts": time.time(),
            "scores_raw": {"A": s_a_raw, "B": s_b_raw},
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
            "winner": winner,
            "detections": [
                {
                    "name": "A",
                    "label": self._config.name_a,
                    "score_raw": s_a_raw,
                    "score_cal": s_a_cal,
                    "box": boxes.get("A", [0, 0, 0, 0]),
                },
                {
                    "name": "B",
                    "label": self._config.name_b,
                    "score_raw": s_b_raw,
                    "score_cal": s_b_cal,
                    "box": boxes.get("B", [0, 0, 0, 0]),
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
        if state == "AMBIGUOUS":
            print(
                f"[{now:.2f}] AMBIGUOUS {self._config.name_a} {packet['scores_raw']['A']:.2f}/{packet['scores_cal']['A']:.2f} "
                f"{self._config.name_b} {packet['scores_raw']['B']:.2f}/{packet['scores_cal']['B']:.2f} gap={packet['gap']:.3f} "
                f"T={packet['T']:.3f} M={packet['M']:.3f}"
            )
        elif state == "DECIDED" and winner:
            label = self._config.name_a if winner == "A" else self._config.name_b
            score_raw = packet["scores_raw"][winner]
            score_cal = packet["scores_cal"][winner]
            print(
                f"[{now:.2f}] DECIDED {label} raw={score_raw:.2f} cal={score_cal:.2f} "
                f"T={packet['T']:.3f} M={packet['M']:.3f}"
            )

    def _clip(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def _clip_bias(self, value: float) -> float:
        return max(-self._config.bias_limit, min(self._config.bias_limit, value))
