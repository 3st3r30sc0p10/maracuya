from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


AMBIGUITY_LOW_EVIDENCE = "AMBIGUITY_LOW_EVIDENCE"
AMBIGUITY_SPLIT_EVIDENCE = "AMBIGUITY_SPLIT_EVIDENCE"


@dataclass(frozen=True)
class TriStateResult:
    label: str
    in_margin: bool
    delta: float
    max_score: float


def classify_scores(s0: float, s1: float, k: float, amb_min_max: float) -> TriStateResult:
    """
    Apply epistemic tri-state logic.

    Rules:
      - delta = abs(s0 - s1)
      - in_margin = delta <= k
      - if not in_margin: choose stronger class
      - if in_margin and max_score < amb_min_max: low evidence ambiguity
      - if in_margin and max_score >= amb_min_max: split evidence ambiguity
    """
    delta = abs(s0 - s1)
    max_score = max(s0, s1)
    in_margin = delta <= k
    if not in_margin:
        label = "maracuya" if s0 > s1 else "passionfruit"
    else:
        if max_score < amb_min_max:
            label = AMBIGUITY_LOW_EVIDENCE
        else:
            label = AMBIGUITY_SPLIT_EVIDENCE
    return TriStateResult(label=label, in_margin=in_margin, delta=delta, max_score=max_score)


def is_ambiguous_label(label: str) -> bool:
    return label in {AMBIGUITY_LOW_EVIDENCE, AMBIGUITY_SPLIT_EVIDENCE}


def resolve_frame_state(detections: Iterable[dict]) -> str:
    """
    Decide overall frame state based on best detection.
    """
    detections_list = list(detections)
    if not detections_list:
        return "no_detection"
    best = max(detections_list, key=lambda item: float(item.get("conf", 0.0)))
    label = best.get("label", "no_detection")
    if is_ambiguous_label(label) or label == "ambiguous":
        return "ambiguous"
    if label in {"maracuya", "passionfruit"}:
        return label
    return "no_detection"
