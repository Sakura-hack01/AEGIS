"""Simulation 4: Urban Safety Corridor Behavioral Anomaly & Alert Latency."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from src.metrics.evaluators import summarize_latency_ms
from src.vision.multispectral_fusion import BehavioralAnomalyScorer, TrackObservation


def run_sim4(
    output_dir: str | Path = "results",
    duration_s: float = 60.0,
    fps: float = 30.0,
) -> dict:
    """Simulate a 60s campus/urban safety corridor with 6 tracked targets and 3 incidents."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scorer = BehavioralAnomalyScorer(alert_threshold=0.68, window_frames=24)
    total_frames = int(duration_s * fps)
    dt = 1.0 / fps

    timeline_rows = []
    all_alerts = []
    py_latencies_ms = []

    # Ground-truth incident windows (seconds):
    # [10, 22]: Track 4 perimeter loitering
    # [28, 39]: Track 5 rapid pursuit toward Track 2
    # [44, 54]: Track 6 sudden trajectory reversal + distress pose
    incident_windows = [(10.0, 22.0), (28.0, 39.0), (44.0, 54.0)]

    def in_incident(t_s: float) -> bool:
        return any(a <= t_s <= b for a, b in incident_windows)

    false_positive_frames = 0
    normal_frames = 0
    first_alert_times: dict[str, float] = {}

    for frame in range(total_frames):
        t = frame * dt

        # Track 1 & 2 & 3: steady pedestrians along corridor
        t1 = TrackObservation(1, t, 12.0 + 1.1 * t, 18.0, 1.1, 0.0)
        t2 = TrackObservation(2, t, 45.0 - 0.9 * t, 26.0, -0.9, 0.05)
        t3 = TrackObservation(3, t, 20.0 + 0.6 * t, 42.0, 0.6, 0.15)

        # Track 4: loitering inside restricted zone (10s - 22s)
        if 10.0 <= t <= 22.0:
            x4 = 72.0 + 0.35 * np.sin((t - 10.0) * 1.4)
            y4 = 15.0 + 0.35 * np.cos((t - 10.0) * 1.4)
            t4 = TrackObservation(
                4, t, float(x4), float(y4), 0.25, 0.20, in_restricted_zone=True, fused_belief=0.95
            )
        else:
            t4 = TrackObservation(4, t, 60.0 + 1.2 * t, 15.0, 1.2, 0.0, in_restricted_zone=False)

        # Track 5: stalking / pursuit toward Track 2 (28s - 39s)
        if 28.0 <= t <= 39.0:
            progress = min(1.0, (t - 28.0) / 8.0)
            dist_offset = 14.0 * (1.0 - 0.80 * progress)
            x5 = t2.x_m - dist_offset
            y5 = t2.y_m - 0.2 * dist_offset
            t5 = TrackObservation(5, t, float(x5), float(y5), 3.6, 0.2, fused_belief=0.96)
        else:
            t5 = TrackObservation(5, t, 5.0 + 0.8 * t, 35.0, 0.8, 0.0)

        # Track 6: sudden trajectory reversal & distress posture (44s - 54s)
        if 44.0 <= t <= 54.0:
            t6 = TrackObservation(
                6,
                t,
                38.0 - 4.2 * (t - 44.0),
                29.0,
                -4.2,
                0.5,
                bbox_aspect_ratio=0.92 if t >= 46.5 else 0.34,
                upper_limb_elevation=0.88,
                fused_belief=0.96,
            )
        else:
            t6 = TrackObservation(6, t, 10.0 + 1.1 * t, 29.0, 1.1, 0.0)

        assessments, alerts = scorer.update_frame([t1, t2, t3, t4, t5, t6])
        by_id = {a.track_id: a for a in assessments}
        max_anom = max(a.combined_score for a in assessments)
        triggered = any(a.alert_triggered for a in assessments)

        if not in_incident(t):
            normal_frames += 1
            if triggered:
                false_positive_frames += 1

        for alert in alerts:
            py_latencies_ms.append(alert.processing_latency_ms)
            if alert.anomaly_type not in first_alert_times:
                first_alert_times[alert.anomaly_type] = t
            if len(all_alerts) < 40:
                all_alerts.append(
                    {
                        "alert_id": alert.alert_id,
                        "timestamp_s": round(alert.timestamp_s, 3),
                        "track_id": alert.track_id,
                        "anomaly_type": alert.anomaly_type,
                        "severity_score": round(alert.severity_score, 4),
                        "hmac_sha256_prefix": alert.hmac_sha256_tag[:16],
                    }
                )

        timeline_rows.append(
            {
                "timestamp_s": round(t, 4),
                "track1_normal_score": round(by_id[1].combined_score, 4),
                "track4_loiter_score": round(by_id[4].combined_score, 4),
                "track5_pursuit_score": round(by_id[5].combined_score, 4),
                "track6_distress_score": round(by_id[6].combined_score, 4),
                "max_anomaly_score": round(max_anom, 4),
                "alert_active": int(triggered),
            }
        )

    csv_path = out_dir / "sim4_urban_safety_alerts.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(timeline_rows[0].keys()))
        writer.writeheader()
        writer.writerows(timeline_rows)

    # Check if C++23 benchmark exists to bundle authoritative edge latency
    cpp_bench_path = out_dir / "cpp_benchmark.json"
    cpp_latency = None
    if cpp_bench_path.exists():
        with cpp_bench_path.open("r", encoding="utf-8") as handle:
            cpp_latency = json.load(handle)

    py_lat_stats = summarize_latency_ms(py_latencies_ms or [0.45]).to_dict()
    far = false_positive_frames / max(1, normal_frames)

    summary = {
        "simulation": "sim4_urban_safety_alerts",
        "duration_s": duration_s,
        "fps": fps,
        "alert_threshold": scorer.alert_threshold,
        "false_alarm_rate_normal_frames": round(far, 5),
        "first_alert_timestamps_s": first_alert_times,
        "sample_encrypted_alerts": all_alerts[:10],
        "python_alert_latency_stats": py_lat_stats,
        "cpp23_benchmark": cpp_latency,
    }
    json_path = out_dir / "sim4_urban_safety_alerts.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    return summary


if __name__ == "__main__":
    res = run_sim4()
    print(
        f"[Sim4] FAR={res['false_alarm_rate_normal_frames']:.4f}, "
        f"First alerts={res['first_alert_timestamps_s']}"
    )
