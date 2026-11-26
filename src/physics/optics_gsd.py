"""Optical geometry, Ground Sample Distance (GSD), and Johnson's Criteria model.

Models nadir and oblique RGB global-shutter CMOS resolution alongside
co-bore-sighted LWIR (8-14 um) thermal resolution across building-height
altitudes (nominal H = 65 m / ~20 floors), demonstrating sub-centimeter
GSD = 0.98 cm/px (~51 x 173 px per human target).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import yaml


@dataclass(frozen=True)
class OpticsConfig:
    """Electro-optical and LWIR sensor geometry parameters."""

    # RGB Global-Shutter CMOS
    rgb_sensor_width_mm: float = 13.2
    rgb_sensor_height_mm: float = 8.8
    rgb_width_px: int = 5472
    rgb_height_px: int = 3648
    rgb_focal_length_mm: float = 16.0
    telephoto_focal_length_mm: float = 220.0
    rgb_f_number: float = 2.8
    telephoto_f_number: float = 4.0
    rgb_exposure_time_s: float = 2.5e-4
    telephoto_exposure_time_s: float = 8.0e-5
    rgb_wavelength_um: float = 0.55
    rgb_system_mtf: float = 0.70

    # LWIR 8-14 um Microbolometer
    lwir_sensor_width_mm: float = 7.68
    lwir_sensor_height_mm: float = 6.144
    lwir_width_px: int = 640
    lwir_height_px: int = 512
    lwir_focal_length_mm: float = 25.0

    # Human & Micro-Target Dimensions
    human_width_m: float = 0.50
    human_height_m: float = 1.70
    human_critical_dim_m: float = 0.75
    micro_target_length_mm: float = 6.0
    micro_target_width_mm: float = 2.0

    # Johnson's Criteria N50 cycle thresholds
    n50_detection: float = 1.0
    n50_recognition: float = 4.0
    n50_identification: float = 6.4

    @property
    def rgb_pixel_pitch_um(self) -> float:
        return (self.rgb_sensor_width_mm * 1000.0) / self.rgb_width_px

    @property
    def rgb_hfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.rgb_sensor_width_mm / (2.0 * self.rgb_focal_length_mm)))

    @property
    def rgb_vfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.rgb_sensor_height_mm / (2.0 * self.rgb_focal_length_mm)))


@dataclass(frozen=True)
class GSDAnalysisResult:
    """Computed optical resolution, human footprint, and Johnson Criteria probabilities."""

    altitude_m: float
    approx_building_floors: float
    off_nadir_deg: float
    slant_range_m: float
    gsd_nadir_cm_px: float
    gsd_cross_track_cm_px: float
    gsd_along_track_cm_px: float
    gsd_effective_cm_px: float
    lwir_gsd_cm_px: float
    swath_width_m: float
    swath_height_m: float
    human_width_px: float
    human_height_px: float
    human_area_px: float
    cycles_on_target: float
    p_detection: float
    p_recognition: float
    p_identification: float
    diffraction_airy_um: float
    telephoto_gsd_mm_px: float
    telephoto_micro_length_px: float
    telephoto_micro_width_px: float
    telephoto_smear_px: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def load_optics_config_from_yaml(config_path: str | Path) -> OpticsConfig:
    """Load optical and Johnson criteria parameters from mission YAML."""
    with Path(config_path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    rgb = raw["optics_rgb"]
    lwir = raw["optics_lwir"]
    human = raw["target_human"]
    micro = raw.get("target_micro_ant", {})
    jc = raw["johnson_criteria"]

    return OpticsConfig(
        rgb_sensor_width_mm=float(rgb["sensor_width_mm"]),
        rgb_sensor_height_mm=float(rgb["sensor_height_mm"]),
        rgb_width_px=int(rgb["width_px"]),
        rgb_height_px=int(rgb["height_px"]),
        rgb_focal_length_mm=float(rgb["focal_length_mm"]),
        telephoto_focal_length_mm=float(rgb.get("telephoto_focal_length_mm", 220.0)),
        rgb_f_number=float(rgb["f_number"]),
        telephoto_f_number=float(rgb.get("telephoto_f_number", 4.0)),
        rgb_exposure_time_s=float(rgb["exposure_time_s"]),
        telephoto_exposure_time_s=float(rgb.get("telephoto_exposure_time_s", 8.0e-5)),
        rgb_wavelength_um=float(rgb["wavelength_um"]),
        rgb_system_mtf=float(rgb["system_mtf"]),
        lwir_sensor_width_mm=float(lwir["sensor_width_mm"]),
        lwir_sensor_height_mm=float(lwir["sensor_height_mm"]),
        lwir_width_px=int(lwir["width_px"]),
        lwir_height_px=int(lwir["height_px"]),
        lwir_focal_length_mm=float(lwir["focal_length_mm"]),
        human_width_m=float(human["shoulder_width_m"]),
        human_height_m=float(human["standing_height_m"]),
        human_critical_dim_m=float(human["critical_dimension_m"]),
        micro_target_length_mm=float(micro.get("body_length_mm", 6.0)),
        micro_target_width_mm=float(micro.get("body_width_mm", 2.0)),
        n50_detection=float(jc["n50_detection"]),
        n50_recognition=float(jc["n50_recognition"]),
        n50_identification=float(jc["n50_identification"]),
    )


class OpticalGSDModel:
    """Exact optical GSD, oblique projection, and Johnson Criteria evaluator."""

    def __init__(self, config: OpticsConfig | None = None) -> None:
        self.config = config or OpticsConfig()

    @staticmethod
    def nadir_gsd_cm_per_px(
        altitude_m: float,
        sensor_width_mm: float,
        focal_length_mm: float,
        width_px: int,
    ) -> float:
        """Compute nadir Ground Sample Distance in cm/px.

        GSD = (H * w_sensor) / (f_focal * W_px) * 100 [cm/px]
        """
        if altitude_m <= 0.0:
            raise ValueError(f"Altitude must be positive; got {altitude_m}.")
        if focal_length_mm <= 0.0 or width_px <= 0 or sensor_width_mm <= 0.0:
            raise ValueError("Sensor dimensions and focal length must be strictly positive.")
        gsd_m = (altitude_m * sensor_width_mm) / (focal_length_mm * float(width_px))
        return gsd_m * 100.0

    @staticmethod
    def johnson_ttpf(cycles: float, n50: float) -> float:
        """Evaluate Target Transfer Probability Function (TTPF) for Johnson Criteria."""
        if cycles <= 0.0:
            return 0.0
        ratio = cycles / n50
        exponent = 2.7 + 0.7 * ratio
        powered = ratio**exponent
        return float(powered / (1.0 + powered))

    def evaluate_altitude(
        self,
        altitude_m: float = 65.0,
        off_nadir_deg: float = 0.0,
        residual_smear_px: float = 0.033,
        floor_height_m: float = 3.25,
    ) -> GSDAnalysisResult:
        """Evaluate RGB & LWIR GSD, human pixel span, and Johnson probabilities."""
        cfg = self.config
        phi = math.radians(off_nadir_deg)
        cos_phi = math.cos(phi)
        if cos_phi <= 0.05:
            raise ValueError(f"Off-nadir angle too extreme: {off_nadir_deg} deg.")

        slant_range_m = altitude_m / cos_phi
        gsd_nadir_cm = self.nadir_gsd_cm_per_px(
            altitude_m=altitude_m,
            sensor_width_mm=cfg.rgb_sensor_width_mm,
            focal_length_mm=cfg.rgb_focal_length_mm,
            width_px=cfg.rgb_width_px,
        )
        gsd_cross_cm = gsd_nadir_cm / cos_phi
        gsd_along_cm = gsd_nadir_cm / (cos_phi * cos_phi)

        # Effective GSD incorporates MTF degradation and motion blur quadrature
        smear_factor = math.sqrt(1.0 + (residual_smear_px / 0.5) ** 2)
        gsd_eff_cm = math.sqrt(gsd_cross_cm * gsd_along_cm) * (smear_factor / max(cfg.rgb_system_mtf, 0.1))

        lwir_gsd_cm = (
            self.nadir_gsd_cm_per_px(
                altitude_m=altitude_m,
                sensor_width_mm=cfg.lwir_sensor_width_mm,
                focal_length_mm=cfg.lwir_focal_length_mm,
                width_px=cfg.lwir_width_px,
            )
            / cos_phi
        )

        # Ground footprint of sensor swath at slant range
        swath_w_m = (gsd_cross_cm / 100.0) * cfg.rgb_width_px
        swath_h_m = (gsd_along_cm / 100.0) * cfg.rgb_height_px

        # Human target pixel footprint (cross/along mean geometric scale)
        nominal_gsd_m = math.sqrt(gsd_cross_cm * gsd_along_cm) / 100.0
        human_w_px = cfg.human_width_m / nominal_gsd_m
        human_h_px = cfg.human_height_m / nominal_gsd_m
        human_area_px = human_w_px * human_h_px

        # Resolved cycles across critical human dimension (line pairs = 2 * effective GSD)
        cycles = cfg.human_critical_dim_m / (2.0 * (gsd_eff_cm / 100.0))

        p_det = self.johnson_ttpf(cycles, cfg.n50_detection)
        p_rec = self.johnson_ttpf(cycles, cfg.n50_recognition)
        p_id = self.johnson_ttpf(cycles, cfg.n50_identification)

        # Airy disk diameter: 2.44 * lambda * N
        airy_um = 2.44 * cfg.rgb_wavelength_um * cfg.rgb_f_number

        # Co-axial 220 mm telephoto micro-inspection channel ("ant-scale" verification)
        tele_gsd_cm = (
            self.nadir_gsd_cm_per_px(
                altitude_m=altitude_m,
                sensor_width_mm=cfg.rgb_sensor_width_mm,
                focal_length_mm=cfg.telephoto_focal_length_mm,
                width_px=cfg.rgb_width_px,
            )
            / (cos_phi ** 1.5)
        )
        tele_gsd_mm = tele_gsd_cm * 10.0
        micro_len_px = cfg.micro_target_length_mm / tele_gsd_mm
        micro_wid_px = cfg.micro_target_width_mm / tele_gsd_mm
        # Fine-steering mirror residual smear at Mach 0.50 (171.5 m/s) and 80 us exposure
        tele_req_rate = (171.5 * cos_phi * cos_phi) / altitude_m
        tele_res_rate = 0.0006 * tele_req_rate + 0.0012
        tele_smear_mm = ((altitude_m * tele_res_rate * cfg.telephoto_exposure_time_s) / (cos_phi * cos_phi)) * 1000.0
        tele_smear_px = tele_smear_mm / tele_gsd_mm

        return GSDAnalysisResult(
            altitude_m=altitude_m,
            approx_building_floors=altitude_m / floor_height_m,
            off_nadir_deg=off_nadir_deg,
            slant_range_m=slant_range_m,
            gsd_nadir_cm_px=gsd_nadir_cm,
            gsd_cross_track_cm_px=gsd_cross_cm,
            gsd_along_track_cm_px=gsd_along_cm,
            gsd_effective_cm_px=gsd_eff_cm,
            lwir_gsd_cm_px=lwir_gsd_cm,
            swath_width_m=swath_w_m,
            swath_height_m=swath_h_m,
            human_width_px=human_w_px,
            human_height_px=human_h_px,
            human_area_px=human_area_px,
            cycles_on_target=cycles,
            p_detection=p_det,
            p_recognition=p_rec,
            p_identification=p_id,
            diffraction_airy_um=airy_um,
            telephoto_gsd_mm_px=tele_gsd_mm,
            telephoto_micro_length_px=micro_len_px,
            telephoto_micro_width_px=micro_wid_px,
            telephoto_smear_px=tele_smear_px,
        )

    def sweep_altitudes(
        self,
        altitudes_m: Iterable[float] | None = None,
        off_nadir_deg: float = 0.0,
        residual_smear_px: float = 0.033,
    ) -> list[GSDAnalysisResult]:
        """Sweep altitudes across 10 m to 150 m (including 65 m 20-floor point)."""
        if altitudes_m is None:
            altitudes_m = np.linspace(10.0, 150.0, 29)
        return [
            self.evaluate_altitude(
                altitude_m=float(alt),
                off_nadir_deg=off_nadir_deg,
                residual_smear_px=residual_smear_px,
            )
            for alt in altitudes_m
        ]
