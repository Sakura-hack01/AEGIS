"""Unit tests for Mach 0.5 aerodynamics, GSD geometry, Johnson criteria, and gimbal kinematics."""

import math
from pathlib import Path

import pytest

from src.physics.aerodynamics import AerodynamicModel, load_aero_parameters_from_yaml
from src.physics.optics_gsd import OpticalGSDModel, load_optics_config_from_yaml


CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs/uav_mission_profile.yaml"


def test_prandtl_glauert_drag_polar_mach_05() -> None:
    params = load_aero_parameters_from_yaml(CONFIG_PATH)
    model = AerodynamicModel(params)

    state = model.evaluate_flight_state(mach=0.50, altitude_m=65.0, off_nadir_deg=0.0)

    # Exact target speed M=0.50 * 343 m/s = 171.5 m/s
    assert math.isclose(state.airspeed_mps, 171.5, rel_tol=1e-6)

    # Prandtl-Glauert beta = sqrt(1 - 0.5^2) = sqrt(0.75)
    expected_beta = math.sqrt(0.75)
    assert math.isclose(state.beta_pg, expected_beta, rel_tol=1e-6)

    # Verify exact C_D = C_D0 / sqrt(1 - M^2) + k * C_L^2
    expected_cd0_comp = params.cd0_incompressible / expected_beta
    expected_cd_ind = params.induced_drag_factor_k * (state.cl_required ** 2)
    assert math.isclose(state.cd0_compressible, expected_cd0_comp, rel_tol=1e-6)
    assert math.isclose(state.cd_total, expected_cd0_comp + expected_cd_ind, rel_tol=1e-6)

    # Dynamic pressure q = 0.5 * rho * v^2 and thrust required T = q * S * C_D
    expected_q = 0.5 * state.rho_kg_m3 * (171.5 ** 2)
    assert math.isclose(state.dynamic_pressure_pa, expected_q, rel_tol=1e-6)
    assert math.isclose(
        state.thrust_required_n, expected_q * params.wing_area_m2 * state.cd_total, rel_tol=1e-6
    )
    assert state.reynolds_number > 2.5e6
    # 220 N micro-turbojet provides positive thrust margin & realistic Jet-A1 burn
    assert state.thrust_margin_pct > 15.0
    assert state.endurance_min > 8.0
    assert state.dash_range_km > 80.0


def test_gimbal_angular_rate_and_motion_blur_suppression() -> None:
    model = AerodynamicModel()
    state_nadir = model.evaluate_flight_state(
        mach=0.50, altitude_m=65.0, off_nadir_deg=0.0, gsd_m_per_px=0.0098
    )

    # theta_dot = v / H = 171.5 / 65.0 rad/s
    assert math.isclose(state_nadir.gimbal_angular_rate_rad_s, 171.5 / 65.0, rel_tol=1e-6)

    # Uncompensated smear fails (> 4 px), whereas active FMC suppresses smear well under 0.5 px
    assert state_nadir.uncompensated_smear_px > 4.0
    assert state_nadir.stabilized_smear_px < 0.50

    # Off-nadir cos^2(phi) scaling
    state_30 = model.evaluate_flight_state(mach=0.50, altitude_m=65.0, off_nadir_deg=30.0)
    expected_ratio = math.cos(math.radians(30.0)) ** 2
    assert math.isclose(
        state_30.gimbal_angular_rate_rad_s / state_nadir.gimbal_angular_rate_rad_s,
        expected_ratio,
        rel_tol=1e-6,
    )


def test_gsd_20_floor_precision_and_johnson_criteria() -> None:
    cfg = load_optics_config_from_yaml(CONFIG_PATH)
    optics = OpticalGSDModel(cfg)

    res = optics.evaluate_altitude(altitude_m=65.0, off_nadir_deg=0.0, residual_smear_px=0.033)

    # GSD = (65 * 13.2) / (16 * 5472) * 100 = 0.9800 cm/px
    assert math.isclose(res.gsd_nadir_cm_px, 0.98, abs_tol=0.005)
    assert math.isclose(res.approx_building_floors, 20.0, abs_tol=0.1)

    # Human target ~ 51 x 173 px
    assert 49.0 <= res.human_width_px <= 53.0
    assert 170.0 <= res.human_height_px <= 176.0

    # Johnson identification probability > 98% at 65 m
    assert res.p_detection > 0.999
    assert res.p_recognition > 0.995
    assert res.p_identification > 0.980

    # Monotonic GSD degradation with altitude
    res_150 = optics.evaluate_altitude(altitude_m=150.0, off_nadir_deg=0.0)
    assert res_150.gsd_nadir_cm_px > res.gsd_nadir_cm_px
    assert res_150.cycles_on_target < res.cycles_on_target

    # 220 mm co-axial telephoto micro-channel achieves < 1 mm/px ("ant on floor @ 20 floors")
    assert math.isclose(res.telephoto_gsd_mm_px, 0.7127, abs_tol=0.01)
    assert res.telephoto_micro_length_px > 8.0
    assert res.telephoto_smear_px < 0.50
