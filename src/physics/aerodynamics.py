"""Subsonic compressible aerodynamics, propulsion power, and active gimbal dynamics.

Implements Prandtl-Glauert compressibility corrections for a compact
blended-wing-body (BWB) surveillance UAV operating from Mach 0.05 to 0.55
(nominal cruise M = 0.50, v = 171.5 m/s at a = 343.0 m/s).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import yaml


@dataclass(frozen=True)
class AeroParameters:
    """Physical airframe and atmospheric constants for the AEGIS-0.5M UAV."""

    mass_kg: float = 14.5
    wing_span_m: float = 1.80
    wing_area_m2: float = 0.48
    mean_aerodynamic_chord_m: float = 0.28
    aspect_ratio: float = 6.75
    oswald_efficiency: float = 0.84
    cd0_incompressible: float = 0.0185
    cl_alpha_0_per_rad: float = 4.85
    propulsive_efficiency: float = 0.78
    speed_of_sound_mps: float = 343.0
    rho_sea_level_kg_m3: float = 1.225
    dynamic_viscosity_pa_s: float = 1.81e-5
    gravity_mps2: float = 9.80665
    max_static_thrust_n: float = 220.0
    tsfc_kg_per_n_hr: float = 0.128
    fuel_mass_kg: float = 3.8

    @property
    def induced_drag_factor_k(self) -> float:
        """Return induced drag factor k = 1 / (pi * AR * e)."""
        return 1.0 / (math.pi * self.aspect_ratio * self.oswald_efficiency)

    @property
    def weight_n(self) -> float:
        """Return aircraft weight in Newtons."""
        return self.mass_kg * self.gravity_mps2


@dataclass(frozen=True)
class FlightStateResult:
    """Evaluated steady-level aerodynamic and gimbal state at (Mach, Altitude)."""

    mach: float
    altitude_m: float
    airspeed_mps: float
    rho_kg_m3: float
    beta_pg: float
    dynamic_pressure_pa: float
    reynolds_number: float
    cl_required: float
    cl_alpha_compressible_per_rad: float
    cd0_compressible: float
    cd_induced: float
    cd_total: float
    lift_to_drag: float
    thrust_required_n: float
    thrust_margin_pct: float
    fuel_burn_kg_per_hr: float
    endurance_min: float
    dash_range_km: float
    aerodynamic_power_w: float
    shaft_power_w: float
    off_nadir_deg: float
    gimbal_angular_rate_rad_s: float
    gimbal_angular_rate_deg_s: float
    uncompensated_smear_px: float
    stabilized_smear_px: float

    def to_dict(self) -> dict[str, float]:
        """Serialize flight state to a plain dictionary."""
        return asdict(self)


def load_aero_parameters_from_yaml(config_path: str | Path) -> AeroParameters:
    """Load aerodynamic and atmospheric parameters from mission YAML."""
    with Path(config_path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    plat = raw["platform"]
    atmo = raw["atmosphere"]
    prop = raw.get("propulsion", {})
    return AeroParameters(
        mass_kg=float(plat["mass_kg"]),
        wing_span_m=float(plat["wing_span_m"]),
        wing_area_m2=float(plat["wing_area_m2"]),
        mean_aerodynamic_chord_m=float(plat["mean_aerodynamic_chord_m"]),
        aspect_ratio=float(plat["aspect_ratio"]),
        oswald_efficiency=float(plat["oswald_efficiency"]),
        cd0_incompressible=float(plat["cd0_incompressible"]),
        cl_alpha_0_per_rad=float(plat["cl_alpha_0_per_rad"]),
        propulsive_efficiency=float(plat["propulsive_efficiency"]),
        speed_of_sound_mps=float(atmo["speed_of_sound_mps"]),
        rho_sea_level_kg_m3=float(atmo["rho_sea_level_kg_m3"]),
        dynamic_viscosity_pa_s=float(atmo["dynamic_viscosity_pa_s"]),
        gravity_mps2=float(atmo["gravity_mps2"]),
        max_static_thrust_n=float(prop.get("max_static_thrust_n", 220.0)),
        tsfc_kg_per_n_hr=float(prop.get("tsfc_kg_per_n_hr", 0.128)),
        fuel_mass_kg=float(plat.get("fuel_mass_kg", 3.8)),
    )


class AerodynamicModel:
    """Compressible subsonic flight-dynamics and active gimbal compensation model."""

    def __init__(self, params: AeroParameters | None = None) -> None:
        self.params = params or AeroParameters()

    @staticmethod
    def prandtl_glauert_factor(mach: float) -> float:
        """Compute Prandtl-Glauert compressibility factor beta = sqrt(1 - M^2)."""
        if not 0.0 < mach < 1.0:
            raise ValueError(f"Mach number must lie in (0, 1) for subsonic PG model; got {mach}.")
        return math.sqrt(1.0 - mach * mach)

    def air_density(self, altitude_m: float) -> float:
        """Compute tropospheric air density using standard exponential ISA scaling."""
        if altitude_m < 0.0:
            raise ValueError(f"Altitude must be non-negative; got {altitude_m}.")
        # Standard tropospheric barometric density decay (~8500 m scale height for low AGL)
        t_sea = 288.15
        lapse = 0.0065
        temp = max(216.65, t_sea - lapse * altitude_m)
        exponent = (self.params.gravity_mps2 / (287.058 * lapse)) - 1.0
        return self.params.rho_sea_level_kg_m3 * (temp / t_sea) ** exponent

    def speed_of_sound(self, altitude_m: float = 0.0) -> float:
        """Return speed of sound referenced to a_0 = 343.0 m/s with mild lapse scaling."""
        t_ref = 293.15  # temperature corresponding to a_0 = 343 m/s
        lapse = 0.0065
        temp = max(216.65, t_ref - lapse * altitude_m)
        return self.params.speed_of_sound_mps * math.sqrt(temp / t_ref)

    def dynamic_pressure(self, velocity_mps: float, altitude_m: float = 0.0) -> float:
        """Compute incompressible/subsonic dynamic pressure q = 0.5 * rho * v^2."""
        rho = self.air_density(altitude_m)
        return 0.5 * rho * velocity_mps * velocity_mps

    def reynolds_number(self, velocity_mps: float, altitude_m: float = 0.0) -> float:
        """Compute chord Reynolds number Re = rho * v * c / mu."""
        rho = self.air_density(altitude_m)
        return (rho * velocity_mps * self.params.mean_aerodynamic_chord_m) / (
            self.params.dynamic_viscosity_pa_s
        )

    def lift_slope_compressible(self, mach: float) -> float:
        """Apply Prandtl-Glauert compressibility scaling to lift-curve slope."""
        beta = self.prandtl_glauert_factor(mach)
        return self.params.cl_alpha_0_per_rad / beta

    def drag_coefficient(self, mach: float, cl: float) -> tuple[float, float, float]:
        """Return (cd_total, cd0_compressible, cd_induced) using PG drag polar.

        C_D(M, C_L) = C_D0 / sqrt(1 - M^2) + k * C_L^2
        """
        beta = self.prandtl_glauert_factor(mach)
        cd0_comp = self.params.cd0_incompressible / beta
        cd_ind = self.params.induced_drag_factor_k * (cl * cl)
        return cd0_comp + cd_ind, cd0_comp, cd_ind

    @staticmethod
    def gimbal_angular_rate(
        velocity_mps: float,
        altitude_m: float,
        off_nadir_deg: float = 0.0,
    ) -> float:
        """Compute required 2-axis gimbal pitch/slew rate (rad/s) for FMC blur cancellation.

        theta_dot = (v * cos^2(phi)) / H
        """
        if altitude_m <= 0.0:
            raise ValueError(f"Altitude must be positive; got {altitude_m}.")
        phi = math.radians(off_nadir_deg)
        cos_phi = math.cos(phi)
        return (velocity_mps * cos_phi * cos_phi) / altitude_m

    @staticmethod
    def compute_motion_smear_px(
        velocity_mps: float,
        altitude_m: float,
        gsd_m_per_px: float,
        exposure_time_s: float = 2.5e-4,
        off_nadir_deg: float = 0.0,
        servo_residual_fraction: float = 0.0045,
        imu_jitter_rad_s: float = 0.008,
    ) -> tuple[float, float]:
        """Compute uncompensated and active-gimbal-stabilized motion smear in pixels."""
        if gsd_m_per_px <= 0.0:
            raise ValueError("GSD must be positive.")
        phi = math.radians(off_nadir_deg)
        cos_sq = math.cos(phi) ** 2

        # Uncompensated linear ground translation projected across exposure window
        uncomp_ground_m = velocity_mps * exposure_time_s
        uncomp_px = uncomp_ground_m / gsd_m_per_px

        # Residual angular velocity error of closed-loop 2-axis FMC gimbal
        req_rate = AerodynamicModel.gimbal_angular_rate(velocity_mps, altitude_m, off_nadir_deg)
        residual_rate_rad_s = servo_residual_fraction * req_rate + imu_jitter_rad_s
        residual_ground_m = (altitude_m * residual_rate_rad_s * exposure_time_s) / max(cos_sq, 1e-6)
        stabilized_px = residual_ground_m / gsd_m_per_px
        return uncomp_px, stabilized_px

    def evaluate_flight_state(
        self,
        mach: float,
        altitude_m: float = 65.0,
        off_nadir_deg: float = 0.0,
        gsd_m_per_px: float = 0.0098,
        exposure_time_s: float = 2.5e-4,
        servo_residual_fraction: float = 0.0045,
        imu_jitter_rad_s: float = 0.008,
        use_sea_level_reference_a: bool = True,
    ) -> FlightStateResult:
        """Evaluate complete aerodynamic, propulsion, and gimbal state."""
        a = self.params.speed_of_sound_mps if use_sea_level_reference_a else self.speed_of_sound(altitude_m)
        v = mach * a
        rho = self.air_density(altitude_m)
        beta = self.prandtl_glauert_factor(mach)
        q = 0.5 * rho * v * v
        re = (rho * v * self.params.mean_aerodynamic_chord_m) / self.params.dynamic_viscosity_pa_s

        cl_req = self.params.weight_n / (q * self.params.wing_area_m2)
        cl_alpha_comp = self.lift_slope_compressible(mach)
        cd_tot, cd0_comp, cd_ind = self.drag_coefficient(mach, cl_req)
        l_over_d = cl_req / cd_tot

        thrust_req = q * self.params.wing_area_m2 * cd_tot
        thrust_margin_pct = 100.0 * (self.params.max_static_thrust_n - thrust_req) / max(
            self.params.max_static_thrust_n, 1e-6
        )
        fuel_burn = self.params.tsfc_kg_per_n_hr * thrust_req
        endurance_hr = self.params.fuel_mass_kg / max(fuel_burn, 1e-6)
        endurance_min = endurance_hr * 60.0
        dash_range_km = (v * endurance_hr * 3600.0) / 1000.0
        p_aero = thrust_req * v
        p_shaft = p_aero / self.params.propulsive_efficiency

        rate_rad_s = self.gimbal_angular_rate(v, altitude_m, off_nadir_deg)
        uncomp_px, stab_px = self.compute_motion_smear_px(
            velocity_mps=v,
            altitude_m=altitude_m,
            gsd_m_per_px=gsd_m_per_px,
            exposure_time_s=exposure_time_s,
            off_nadir_deg=off_nadir_deg,
            servo_residual_fraction=servo_residual_fraction,
            imu_jitter_rad_s=imu_jitter_rad_s,
        )

        return FlightStateResult(
            mach=mach,
            altitude_m=altitude_m,
            airspeed_mps=v,
            rho_kg_m3=rho,
            beta_pg=beta,
            dynamic_pressure_pa=q,
            reynolds_number=re,
            cl_required=cl_req,
            cl_alpha_compressible_per_rad=cl_alpha_comp,
            cd0_compressible=cd0_comp,
            cd_induced=cd_ind,
            cd_total=cd_tot,
            lift_to_drag=l_over_d,
            thrust_required_n=thrust_req,
            thrust_margin_pct=thrust_margin_pct,
            fuel_burn_kg_per_hr=fuel_burn,
            endurance_min=endurance_min,
            dash_range_km=dash_range_km,
            aerodynamic_power_w=p_aero,
            shaft_power_w=p_shaft,
            off_nadir_deg=off_nadir_deg,
            gimbal_angular_rate_rad_s=rate_rad_s,
            gimbal_angular_rate_deg_s=math.degrees(rate_rad_s),
            uncompensated_smear_px=uncomp_px,
            stabilized_smear_px=stab_px,
        )

    def sweep_mach_envelope(
        self,
        mach_values: Iterable[float] | None = None,
        altitude_m: float = 65.0,
        off_nadir_deg: float = 0.0,
        gsd_m_per_px: float = 0.0098,
        exposure_time_s: float = 2.5e-4,
    ) -> list[FlightStateResult]:
        """Evaluate flight states across a Mach sweep (default 0.05 to 0.55)."""
        if mach_values is None:
            mach_values = np.round(np.linspace(0.05, 0.55, 51), 4)
        return [
            self.evaluate_flight_state(
                mach=float(m),
                altitude_m=altitude_m,
                off_nadir_deg=off_nadir_deg,
                gsd_m_per_px=gsd_m_per_px,
                exposure_time_s=exposure_time_s,
            )
            for m in mach_values
        ]

    def evaluate_servo_hinge_moment_kgcm(
        self,
        dynamic_pressure_pa: float,
        elevon_chord_m: float = 0.055,
        elevon_span_m: float = 0.24,
        max_deflection_deg: float = 6.0,
        inset_balance_factor: float = 0.30,
    ) -> float:
        """Estimate split-elevon aerodynamic hinge moment (kg*cm) with 25% inset hinge balance."""
        area = elevon_chord_m * elevon_span_m
        # Unbalanced Ch ~ 0.045/deg * delta_deg, reduced by 25%-chord aerodynamic hinge balance
        ch_effective = 0.045 * max_deflection_deg * inset_balance_factor
        moment_nm = dynamic_pressure_pa * area * elevon_chord_m * ch_effective
        # Convert N*m to kg*cm: 1 N*m = 10.19716 kg*cm
        return moment_nm * 10.19716

    def evaluate_delhi_mission_phases(
        self,
        delhi_ground_msl_m: float = 216.0,
        patrol_agl_m: float = 500.0,
    ) -> list[dict[str, float | str]]:
        """Compute 5-stage flight dynamics & propulsion telemetry over New Delhi (216m MSL)."""
        cruise_alt_msl = delhi_ground_msl_m + patrol_agl_m
        phases = [
            ("1. Pneumatic Rail Launch", 0.095, 5.0, 0.0),
            ("2. Climb to 500m AGL", 0.25, 250.0, 12.0),
            ("3. Delhi Loiter Patrol (M0.14)", 0.14, patrol_agl_m, 0.0),
            ("4. Mach 0.50 Dash Over Delhi", 0.50, patrol_agl_m, 15.0),
            ("5. Glide & Recovery Approach", 0.12, 80.0, 0.0),
        ]
        results = []
        for name, mach, agl, phi_deg in phases:
            st = self.evaluate_flight_state(
                mach=mach,
                altitude_m=agl,
                off_nadir_deg=phi_deg,
                gsd_m_per_px=0.000771 if agl >= 400.0 else 0.0098,
                exposure_time_s=4.5e-5 if agl >= 400.0 else 2.5e-4,
                servo_residual_fraction=0.0012 if agl >= 400.0 else 0.0045,
                imu_jitter_rad_s=0.0015 if agl >= 400.0 else 0.008,
                use_sea_level_reference_a=False,
            )
            rho_msl = self.air_density(delhi_ground_msl_m + agl)
            # Speed-scheduled elevon deflection limit: 18 deg at launch/loiter, 6 deg at Mach 0.50
            delta_limit = 6.0 if mach >= 0.40 else 14.0
            hinge_kgcm = self.evaluate_servo_hinge_moment_kgcm(
                st.dynamic_pressure_pa, max_deflection_deg=delta_limit
            )
            results.append(
                {
                    "phase": name,
                    "mach": mach,
                    "agl_m": agl,
                    "msl_m": delhi_ground_msl_m + agl,
                    "airspeed_mps": round(st.airspeed_mps, 2),
                    "rho_msl_kg_m3": round(rho_msl, 4),
                    "dynamic_pressure_kpa": round(st.dynamic_pressure_pa / 1000.0, 2),
                    "cd_total": round(st.cd_total, 5),
                    "lift_to_drag": round(st.lift_to_drag, 2),
                    "thrust_required_n": round(st.thrust_required_n, 2),
                    "thrust_margin_pct": round(st.thrust_margin_pct, 2),
                    "fuel_burn_kg_hr": round(st.fuel_burn_kg_per_hr, 2),
                    "endurance_min": round(st.endurance_min, 1),
                    "gimbal_rate_deg_s": round(st.gimbal_angular_rate_deg_s, 2),
                    "elevon_hinge_kgcm": round(hinge_kgcm, 2),
                    "cruise_alt_msl_ref": cruise_alt_msl,
                }
            )
        return results
