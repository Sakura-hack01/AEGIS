"""Simulation 3: RGB-Only vs LWIR-Only vs RGB+LWIR Dempster-Shafer Fusion under Occlusion."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import torch

from src.metrics.evaluators import evaluate_detections
from src.vision.multispectral_fusion import (
    CrossModalDSDetector,
    MultiSpectralSceneGenerator,
    RegimeName,
)


REGIMES: tuple[RegimeName, ...] = (
    "clear_day",
    "urban_shadow",
    "foliage_occlusion",
    "night_blackout",
    "smoke_haze",
)


def run_sim3(
    output_dir: str | Path = "results",
    scenes_per_regime: int = 12,
    seed: int = 2026,
) -> dict:
    """Benchmark detection recall, mAP@0.5, and FAR across five visibility regimes."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(seed)
    detector = CrossModalDSDetector()
    detector.eval()

    rows = []
    triptych_saved = False

    for reg_idx, regime in enumerate(REGIMES):
        gen = MultiSpectralSceneGenerator(height=128, width=128, seed=seed + reg_idx * 100)

        rgb_preds, lwir_preds, fused_preds, gt_all = [], [], [], []
        conflicts = []

        for s_idx in range(scenes_per_regime):
            scene = gen.generate_scene(regime=regime, num_humans=3, num_distractors=2)
            with torch.no_grad():
                out = detector(scene.rgb, scene.lwir_kelvin)

            conflicts.append(float(out["conflict_k"].mean()))

            rgb_boxes = detector.extract_detections(
                out, scene.lwir_kelvin, score_map_key="rgb_prob", threshold=0.45
            )
            lwir_boxes = detector.extract_detections(
                out, scene.lwir_kelvin, score_map_key="lwir_prob", threshold=0.48
            )
            fused_boxes = detector.extract_detections(
                out, scene.lwir_kelvin, score_map_key="fused_prob", threshold=0.48
            )

            rgb_preds.append([(b.x1, b.y1, b.x2, b.y2, b.confidence) for b in rgb_boxes])
            lwir_preds.append([(b.x1, b.y1, b.x2, b.y2, b.confidence) for b in lwir_boxes])
            fused_preds.append([(b.x1, b.y1, b.x2, b.y2, b.confidence) for b in fused_boxes])
            gt_all.append(scene.gt_boxes)

            # Save one illustrative foliage_occlusion scene triptych for Fig 3
            if regime == "foliage_occlusion" and s_idx == 0 and not triptych_saved:
                np.savez(
                    out_dir / "sim3_sample_triptych.npz",
                    rgb=scene.rgb.permute(1, 2, 0).numpy(),
                    lwir_kelvin=scene.lwir_kelvin[0].numpy(),
                    fused_prob=out["fused_prob"][0, 0].numpy(),
                    rgb_prob=out["rgb_prob"][0, 0].numpy(),
                    gt_boxes=np.array(scene.gt_boxes, dtype=np.float32),
                    fused_boxes=np.array(
                        [(b.x1, b.y1, b.x2, b.y2, b.confidence) for b in fused_boxes],
                        dtype=np.float32,
                    ),
                )
                triptych_saved = True

        eval_rgb = evaluate_detections(rgb_preds, gt_all)
        eval_lwir = evaluate_detections(lwir_preds, gt_all)
        eval_fused = evaluate_detections(fused_preds, gt_all)

        for modality, ev in (
            ("RGB-Only", eval_rgb),
            ("LWIR-Only", eval_lwir),
            ("RGB+LWIR-DS-Fusion", eval_fused),
        ):
            rows.append(
                {
                    "regime": regime,
                    "modality": modality,
                    "precision": round(ev.precision, 4),
                    "recall": round(ev.recall, 4),
                    "f1_score": round(ev.f1_score, 4),
                    "ap_50": round(ev.ap_50, 4),
                    "false_alarm_rate_per_frame": round(ev.false_alarm_rate_per_frame, 4),
                    "mean_epistemic_conflict_k": round(float(np.mean(conflicts)), 4),
                }
            )

    csv_path = out_dir / "sim3_rgb_lwir_occlusion.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "simulation": "sim3_rgb_lwir_occlusion",
        "scenes_per_regime": scenes_per_regime,
        "results": rows,
    }
    json_path = out_dir / "sim3_rgb_lwir_occlusion.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    return summary


if __name__ == "__main__":
    res = run_sim3()
    for r in res["results"]:
        if r["regime"] in ("foliage_occlusion", "night_blackout"):
            print(
                f"[Sim3] {r['regime']:18s} | {r['modality']:18s} | "
                f"Recall={r['recall']:.3f}, AP50={r['ap_50']:.3f}, FAR={r['false_alarm_rate_per_frame']:.3f}"
            )
