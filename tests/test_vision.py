"""Unit tests for RGB+LWIR Bayesian Dempster-Shafer fusion and behavioral alerts."""

import torch

from src.vision.multispectral_fusion import (
    BehavioralAnomalyScorer,
    CrossModalDSDetector,
    DempsterShaferFusionLayer,
    MultiSpectralSceneGenerator,
    TrackObservation,
)


def test_dempster_shafer_bpa_combination_properties() -> None:
    # Strong thermal evidence (p_lwir=0.95, alpha=0.94) + uncertain RGB (alpha=0.15)
    out = DempsterShaferFusionLayer.combine_bpa(
        p_rgb=torch.tensor([0.35]),
        alpha_rgb=torch.tensor([0.15]),
        p_lwir=torch.tensor([0.95]),
        alpha_lwir=torch.tensor([0.94]),
    )
    belief = float(out["belief_target"].item())
    bg = float(out["belief_bg"].item())
    unc = float(out["uncertainty"].item())

    # Mass conservation: m(T) + m(B) + m(Omega) = 1.0
    assert abs((belief + bg + unc) - 1.0) < 1e-5
    # High LWIR confidence dominates weak/occluded RGB
    assert float(out["pignistic_target"].item()) > 0.85


def test_rgb_lwir_fusion_beats_rgb_under_occlusion_and_night() -> None:
    torch.manual_seed(7)
    detector = CrossModalDSDetector()
    detector.eval()

    for regime in ("foliage_occlusion", "night_blackout"):
        gen = MultiSpectralSceneGenerator(height=128, width=128, seed=123)
        rgb_hits = 0
        fused_hits = 0
        total_gt = 0

        for _ in range(4):
            scene = gen.generate_scene(regime=regime, num_humans=3, num_distractors=2)
            with torch.no_grad():
                out = detector(scene.rgb, scene.lwir_kelvin)

            rgb_boxes = detector.extract_detections(
                out, scene.lwir_kelvin, score_map_key="rgb_prob", threshold=0.45
            )
            fused_boxes = detector.extract_detections(
                out, scene.lwir_kelvin, score_map_key="fused_prob", threshold=0.48
            )

            for gx1, gy1, gx2, gy2 in scene.gt_boxes:
                gcx, gcy = 0.5 * (gx1 + gx2), 0.5 * (gy1 + gy2)
                total_gt += 1
                if any(
                    abs(0.5 * (b.x1 + b.x2) - gcx) < 8.0 and abs(0.5 * (b.y1 + b.y2) - gcy) < 9.0
                    for b in rgb_boxes
                ):
                    rgb_hits += 1
                if any(
                    abs(0.5 * (b.x1 + b.x2) - gcx) < 8.0 and abs(0.5 * (b.y1 + b.y2) - gcy) < 9.0
                    for b in fused_boxes
                ):
                    fused_hits += 1

        assert fused_hits > rgb_hits
        assert (fused_hits / total_gt) >= 0.75


def test_behavioral_anomaly_scorer_triggers_and_signs_alerts() -> None:
    scorer = BehavioralAnomalyScorer(alert_threshold=0.68, window_frames=16)
    dt = 1.0 / 30.0

    # Normal walking phase (first 15 frames) -> zero alerts
    for k in range(15):
        t = k * dt
        t1 = TrackObservation(1, t, 10.0 + 1.0 * t, 20.0, 1.0, 0.0)
        t2 = TrackObservation(2, t, 30.0 + 1.0 * t, 20.0, 1.0, 0.0)
        _, alerts = scorer.update_frame([t1, t2])
        assert len(alerts) == 0

    # Inject pursuit + raised-hands distress incident
    triggered_any = False
    for k in range(15, 35):
        t = k * dt
        victim = TrackObservation(
            1, t, 25.0, 20.0, -4.1, 0.4, bbox_aspect_ratio=0.90, upper_limb_elevation=0.88, fused_belief=0.96
        )
        pursuer = TrackObservation(2, t, 21.5, 20.0, 3.8, 0.0, fused_belief=0.95)
        assessments, alerts = scorer.update_frame([victim, pursuer])
        if alerts:
            triggered_any = True
            assert len(alerts[0].hmac_sha256_tag) == 64
            assert alerts[0].processing_latency_ms < 2.5
            assert any(a.alert_triggered for a in assessments)

    assert triggered_any
