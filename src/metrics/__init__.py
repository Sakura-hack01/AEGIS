"""Detection, thermal fusion gain, false alarm rate, and latency evaluators."""

from .evaluators import (
    DetectionEvaluation,
    LatencyStats,
    compute_box_iou,
    evaluate_detections,
    summarize_latency_ms,
)

__all__ = [
    "DetectionEvaluation",
    "LatencyStats",
    "compute_box_iou",
    "evaluate_detections",
    "summarize_latency_ms",
]
