"""Simulation 5: New Delhi 500 m AGL High-Altitude Millimeter-Scale ISR Simulation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from src.physics.aerodynamics import AerodynamicModel, load_aero_parameters_from_yaml
from src.physics.optics_gsd import OpticalGSDModel


# Central New Delhi Operational Sector (4000 m E-W x 2500 m N-S, local origin SW corner)
# Anchored around real Central Delhi topology: Connaught Place, Kartavya Path, India Gate, Lodhi Gardens, ITO Yamuna
DELHI_LANDMARKS = [
    {
        "name": "Connaught Place (Inner Circle)",
        "x_m": 1050.0,
        "y_m": 1920.0,
        "zone_type": "high_density_ring",
        "ambient_temp_k": 301.5,
        "canopy_fraction": 0.20,
    },
    {
        "name": "Kartavya Path (Central Vista)",
        "x_m": 1680.0,
        "y_m": 1180.0,
        "zone_type": "vip_corridor",
        "ambient_temp_k": 299.0,
        "canopy_fraction": 0.15,
    },
    {
        "name": "India Gate Memorial Plaza",
        "x_m": 2250.0,
        "y_m": 1160.0,
        "zone_type": "restricted_plaza",
        "ambient_temp_k": 300.2,
        "canopy_fraction": 0.10,
    },
    {
        "name": "Lodhi Gardens Canopy Sector",
        "x_m": 1920.0,
        "y_m": 460.0,
        "zone_type": "dense_foliage",
        "ambient_temp_k": 293.8,
        "canopy_fraction": 0.78,
    },
    {
        "name": "ITO & Yamuna Western Approach",
        "x_m": 3420.0,
        "y_m": 1640.0,
        "zone_type": "bridge_chokepoint",
        "ambient_temp_k": 297.4,
        "canopy_fraction": 0.12,
    },
    {
        "name": "Barakhamba High-Rise District",
        "x_m": 1520.0,
        "y_m": 1760.0,
        "zone_type": "urban_canyon",
        "ambient_temp_k": 300.8,
        "canopy_fraction": 0.18,
    },
]


def run_sim5(
    config_path: str | Path = "configs/uav_mission_profile.yaml",
    output_dir: str | Path = "results",
) -> dict:
    """Simulate 500 m AGL flight over Central New Delhi with millimeter-scale verification."""
    cfg_path = Path(config_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    params = load_aero_parameters_from_yaml(cfg_path) if cfg_path.exists() else None
    aero = AerodynamicModel(params)
    optics = OpticalGSDModel()

    # 1. Mission phases over Delhi (216 m MSL ground elevation + 500 m AGL = 716 m MSL)
    mission_phases = aero.evaluate_delhi_mission_phases(delhi_ground_msl_m=216.0, patrol_agl_m=500.0)

    # 2. Altitude sweep 50 m -> 600 m comparing Wide (16 mm), Tactical (220 mm), and Cassegrain (1200 mm)
    alt_rows = []
    for alt in np.linspace(50.0, 600.0, 23):
        wide_res = optics.evaluate_altitude(altitude_m=float(alt), off_nadir_deg=0.0)
        cass_res = optics.evaluate_500m_cassegrain_channel(altitude_m=float(alt), off_nadir_deg=0.0)
        alt_rows.append(
            {
                "altitude_m": float(alt),
                "wide_16mm_gsd_cm_px": round(wide_res.gsd_nadir_cm_px, 3),
                "tele_220mm_gsd_mm_px": round(wide_res.telephoto_gsd_mm_px, 3),
                "cassegrain_1200mm_gsd_mm_px": round(cass_res.gsd_mm_px, 4),
                "rayleigh_diffraction_mm": round(cass_res.rayleigh_diffraction_mm, 3),
                "target_6mm_px": round(cass_res.target_6mm_length_px, 2),
                "fsm_smear_px": round(cass_res.fsm_stabilized_smear_px, 4),
                "uncomp_smear_px": round(cass_res.uncompensated_smear_px, 2),
            }
        )

    csv_path = out_dir / "sim5_delhi_500m_city.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(alt_rows[0].keys()))
        writer.writeheader()
        writer.writerows(alt_rows)

    # 3. Mach 0.50 racetrack flight trajectory visiting all Central Delhi landmarks at 500 m AGL
    t_vals = np.linspace(0.0, 60.0, 181)
    # Smooth closed ellipse over Connaught Place -> Barakhamba -> ITO -> India Gate -> Lodhi -> Kartavya
    traj_x = 2050.0 + 1350.0 * np.cos(t_vals * (2.0 * np.pi / 60.0))
    traj_y = 1180.0 + 760.0 * np.sin(t_vals * (2.0 * np.pi / 60.0))

    c500_nadir = optics.evaluate_500m_cassegrain_channel(altitude_m=500.0, off_nadir_deg=0.0)
    c500_oblique = optics.evaluate_500m_cassegrain_channel(altitude_m=500.0, off_nadir_deg=25.0)
    wide_500 = optics.evaluate_altitude(altitude_m=500.0, off_nadir_deg=0.0)

    # Millimeter-scale test targets placed across Delhi landmarks
    mm_targets = [
        {"id": "DEL-MM-01", "landmark": "India Gate Memorial Plaza", "size_mm": 6.0, "type": "6 mm Metallic Micro-Bolt / FOD", "x_m": 2250.0, "y_m": 1160.0},
        {"id": "DEL-MM-02", "landmark": "Kartavya Path (Central Vista)", "size_mm": 4.5, "type": "4.5 mm Optical Wire / Micro-Beacon", "x_m": 1680.0, "y_m": 1180.0},
        {"id": "DEL-MM-03", "landmark": "Lodhi Gardens Canopy Sector", "size_mm": 8.0, "type": "8 mm Thermal/Optical Marker (Canopy Gap)", "x_m": 1920.0, "y_m": 460.0},
    ]
    for mt in mm_targets:
        mt["resolved_px_at_500m"] = round(mt["size_mm"] / c500_nadir.gsd_mm_px, 2)
        mt["exceeds_rayleigh_limit"] = mt["size_mm"] >= c500_nadir.rayleigh_diffraction_mm

    summary = {
        "simulation": "sim5_delhi_500m_city",
        "city": "New Delhi, India (28.6139 N, 77.2090 E | 216 m MSL)",
        "sector_dimensions_m": {"width_ew": 4000.0, "height_ns": 2500.0},
        "target_altitude_agl_m": 500.0,
        "cassegrain_500m_nadir": c500_nadir.to_dict(),
        "cassegrain_500m_25deg_oblique": c500_oblique.to_dict(),
        "wide_16mm_at_500m": wide_500.to_dict(),
        "mission_phases": mission_phases,
        "landmarks": DELHI_LANDMARKS,
        "mm_targets": mm_targets,
        "trajectory_sample": [
            {"t_s": round(float(t), 2), "x_m": round(float(x), 1), "y_m": round(float(y), 1)}
            for t, x, y in zip(t_vals, traj_x, traj_y)
        ],
        "altitude_sweep": alt_rows,
    }

    json_path = out_dir / "sim5_delhi_500m_city.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    return summary


if __name__ == "__main__":
    res = run_sim5()
    c = res["cassegrain_500m_nadir"]
    print(
        f"[Sim5 Delhi 500m] GSD={c['gsd_mm_px']:.3f} mm/px | "
        f"Rayleigh={c['rayleigh_diffraction_mm']:.2f} mm | "
        f"6mm Target={c['target_6mm_length_px']:.2f} px | "
        f"FSM Smear={c['fsm_stabilized_smear_px']:.3f} px"
    )
