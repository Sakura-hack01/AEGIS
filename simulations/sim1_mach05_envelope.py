"""Simulation 1: Mach 0.05-0.55 Compressible Drag Polar, Thrust & Gimbal Blur Suppression."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from src.physics.aerodynamics import AerodynamicModel, load_aero_parameters_from_yaml


def run_sim1(
    config_path: str | Path = "configs/uav_mission_profile.yaml",
    output_dir: str | Path = "results",
) -> dict:
    """Execute Mach 0.05-0.55 aerodynamic & gimbal compensation sweep."""
    cfg_path = Path(config_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    params = load_aero_parameters_from_yaml(cfg_path) if cfg_path.exists() else None
    model = AerodynamicModel(params)

    mach_grid = np.round(np.linspace(0.05, 0.55, 51), 4)
    nadir_states = model.sweep_mach_envelope(
        mach_values=mach_grid,
        altitude_m=65.0,
        off_nadir_deg=0.0,
        gsd_m_per_px=0.0098,
        exposure_time_s=2.5e-4,
    )
    oblique_states = model.sweep_mach_envelope(
        mach_values=mach_grid,
        altitude_m=65.0,
        off_nadir_deg=30.0,
        gsd_m_per_px=0.0098,
        exposure_time_s=2.5e-4,
    )

    csv_path = out_dir / "sim1_mach05_envelope.csv"
    fieldnames = list(nadir_states[0].to_dict().keys()) + [
        "cd_incompressible_ref",
        "gimbal_rate_deg_s_30deg",
    ]

    rows = []
    for st_nadir, st_obl in zip(nadir_states, oblique_states):
        cd_incomp = model.params.cd0_incompressible + model.params.induced_drag_factor_k * (
            st_nadir.cl_required ** 2
        )
        row = st_nadir.to_dict()
        row["cd_incompressible_ref"] = cd_incomp
        row["gimbal_rate_deg_s_30deg"] = st_obl.gimbal_angular_rate_deg_s
        rows.append(row)

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    cruise = model.evaluate_flight_state(
        mach=0.50,
        altitude_m=65.0,
        off_nadir_deg=0.0,
        gsd_m_per_px=0.0098,
        exposure_time_s=2.5e-4,
    )

    summary = {
        "simulation": "sim1_mach05_envelope",
        "cruise_mach_050": cruise.to_dict(),
        "max_mach_tested": float(mach_grid[-1]),
        "min_mach_tested": float(mach_grid[0]),
        "num_points": len(rows),
        "sweep": rows,
    }
    json_path = out_dir / "sim1_mach05_envelope.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    return summary


if __name__ == "__main__":
    res = run_sim1()
    c = res["cruise_mach_050"]
    print(
        f"[Sim1] Mach {c['mach']:.2f} ({c['airspeed_mps']:.1f} m/s): "
        f"CD={c['cd_total']:.5f}, T_req={c['thrust_required_n']:.2f} N, "
        f"Gimbal={c['gimbal_angular_rate_deg_s']:.2f} deg/s, "
        f"Smear: {c['uncompensated_smear_px']:.2f} px -> {c['stabilized_smear_px']:.3f} px"
    )
