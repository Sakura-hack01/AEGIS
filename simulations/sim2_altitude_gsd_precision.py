"""Simulation 2: Altitude vs. GSD & Target Detection Precision (10 m to 150 m)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from src.physics.optics_gsd import OpticalGSDModel, load_optics_config_from_yaml


def run_sim2(
    config_path: str | Path = "configs/uav_mission_profile.yaml",
    output_dir: str | Path = "results",
) -> dict:
    """Evaluate GSD, human target pixel footprint, and Johnson Criteria across 10-150 m."""
    cfg_path = Path(config_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_optics_config_from_yaml(cfg_path) if cfg_path.exists() else None
    model = OpticalGSDModel(cfg)

    altitudes = np.linspace(10.0, 150.0, 29)
    nadir_results = model.sweep_altitudes(altitudes, off_nadir_deg=0.0, residual_smear_px=0.033)
    oblique20_results = model.sweep_altitudes(altitudes, off_nadir_deg=20.0, residual_smear_px=0.033)
    oblique35_results = model.sweep_altitudes(altitudes, off_nadir_deg=35.0, residual_smear_px=0.033)

    rows = []
    for r0, r20, r35 in zip(nadir_results, oblique20_results, oblique35_results):
        d = r0.to_dict()
        d["gsd_oblique20_mean_cm_px"] = float(
            np.sqrt(r20.gsd_cross_track_cm_px * r20.gsd_along_track_cm_px)
        )
        d["gsd_oblique35_mean_cm_px"] = float(
            np.sqrt(r35.gsd_cross_track_cm_px * r35.gsd_along_track_cm_px)
        )
        rows.append(d)

    csv_path = out_dir / "sim2_altitude_gsd_precision.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    sweet_spot = model.evaluate_altitude(altitude_m=65.0, off_nadir_deg=0.0, residual_smear_px=0.033)
    summary = {
        "simulation": "sim2_altitude_gsd_precision",
        "sweet_spot_65m_20floors": sweet_spot.to_dict(),
        "sweep": rows,
    }
    json_path = out_dir / "sim2_altitude_gsd_precision.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    return summary


if __name__ == "__main__":
    res = run_sim2()
    s = res["sweet_spot_65m_20floors"]
    print(
        f"[Sim2] H={s['altitude_m']:.1f} m (~{s['approx_building_floors']:.0f} floors): "
        f"GSD={s['gsd_nadir_cm_px']:.4f} cm/px, "
        f"Human={s['human_width_px']:.1f}x{s['human_height_px']:.1f} px, "
        f"P(ID)={s['p_identification']*100:.2f}%"
    )
