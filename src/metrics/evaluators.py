"""Quantitative detection, thermal occlusion recall, FAR, and latency evaluators."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class DetectionEvaluation:
    """Standard object detection and occlusion-resilience metrics."""

    precision: float
    recall: float
    f1_score: float
    ap_50: float
    false_alarm_rate_per_frame: float
    true_positives: int
    false_positives: int
    false_negatives: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True)
class LatencyStats:
    """Real-time edge inference latency percentiles."""

    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    fps_mean: float
    meets_2_5ms_budget: bool

    def to_dict(self) -> dict[str, float | bool]:
        return asdict(self)


def compute_box_iou(
    box_a: tuple[float, float, float, float],
    box_b: tuple[float, float, float, float],
) -> float:
    """Compute Intersection-over-Union between two (x1, y1, x2, y2) boxes."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0.0 else 0.0


def evaluate_detections(
    predicted_boxes_per_frame: Sequence[Sequence[tuple[float, float, float, float, float]]],
    gt_boxes_per_frame: Sequence[Sequence[tuple[float, float, float, float]]],
    iou_threshold: float = 0.30,
    center_dist_fallback_px: float = 7.5,
) -> DetectionEvaluation:
    """Evaluate precision, recall, F1, FAR, and AP@0.5-style VOC AUC across frames.

    Each predicted box is `(x1, y1, x2, y2, confidence)`. Matches use IoU >= iou_threshold
    or center-point distance <= center_dist_fallback_px for sub-10px aerial targets.
    """
    all_preds: list[tuple[int, float, tuple[float, float, float, float]]] = []
    total_gt = 0

    for frame_idx, (preds, gts) in enumerate(zip(predicted_boxes_per_frame, gt_boxes_per_frame)):
        total_gt += len(gts)
        for p in preds:
            all_preds.append((frame_idx, float(p[4]), (float(p[0]), float(p[1]), float(p[2]), float(p[3]))))

    all_preds.sort(key=lambda item: item[1], reverse=True)
    matched_gt = {idx: [False] * len(gts) for idx, gts in enumerate(gt_boxes_per_frame)}

    tp_flags = np.zeros(len(all_preds), dtype=np.float64)
    fp_flags = np.zeros(len(all_preds), dtype=np.float64)

    for i, (f_idx, _conf, p_box) in enumerate(all_preds):
        gts = gt_boxes_per_frame[f_idx]
        best_j = -1
        best_score = -1.0
        px = 0.5 * (p_box[0] + p_box[2])
        py = 0.5 * (p_box[1] + p_box[3])

        for j, g_box in enumerate(gts):
            if matched_gt[f_idx][j]:
                continue
            iou = compute_box_iou(p_box, g_box)
            gx = 0.5 * (g_box[0] + g_box[2])
            gy = 0.5 * (g_box[1] + g_box[3])
            cdist = float(np.hypot(px - gx, py - gy))
            if iou >= iou_threshold or cdist <= center_dist_fallback_px:
                match_quality = iou + (1.0 / (1.0 + cdist))
                if match_quality > best_score:
                    best_score = match_quality
                    best_j = j

        if best_j >= 0:
            matched_gt[f_idx][best_j] = True
            tp_flags[i] = 1.0
        else:
            fp_flags[i] = 1.0

    tp = int(tp_flags.sum())
    fp = int(fp_flags.sum())
    fn = max(0, total_gt - tp)

    precision = tp / max(1, tp + fp)
    recall = tp / max(1, total_gt)
    f1 = (2.0 * precision * recall) / max(1e-9, precision + recall)

    # All-point interpolated AP
    if len(all_preds) > 0 and total_gt > 0:
        cum_tp = np.cumsum(tp_flags)
        cum_fp = np.cumsum(fp_flags)
        rec_curve = cum_tp / total_gt
        prec_curve = cum_tp / np.maximum(cum_tp + cum_fp, 1e-9)
        mrec = np.concatenate(([0.0], rec_curve, [1.0]))
        mpre = np.concatenate(([0.0], prec_curve, [0.0]))
        for k in range(len(mpre) - 2, -1, -1):
            mpre[k] = max(mpre[k], mpre[k + 1])
        idx = np.where(mrec[1:] != mrec[:-1])[0]
        ap = float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))
    else:
        ap = 0.0

    num_frames = max(1, len(gt_boxes_per_frame))
    return DetectionEvaluation(
        precision=float(precision),
        recall=float(recall),
        f1_score=float(f1),
        ap_50=ap,
        false_alarm_rate_per_frame=float(fp / num_frames),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
    )


def summarize_latency_ms(latencies_ms: Iterable[float], budget_ms: float = 2.5) -> LatencyStats:
    """Compute latency percentiles and check compliance with real-time <2.5 ms budget."""
    arr = np.asarray(list(latencies_ms), dtype=np.float64)
    if arr.size == 0:
        raise ValueError("Latency array cannot be empty.")
    mean_ms = float(np.mean(arr))
    p99 = float(np.percentile(arr, 99))
    return LatencyStats(
        mean_ms=mean_ms,
        p50_ms=float(np.percentile(arr, 50)),
        p95_ms=float(np.percentile(arr, 95)),
        p99_ms=p99,
        max_ms=float(np.max(arr)),
        fps_mean=float(1000.0 / max(mean_ms, 1e-6)),
        meets_2_5ms_budget=bool(p99 < budget_ms),
    )
