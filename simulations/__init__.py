"""Reproducible simulation suite for AEGIS-0.5M."""

from .sim1_mach05_envelope import run_sim1
from .sim2_altitude_gsd_precision import run_sim2
from .sim3_rgb_lwir_occlusion import run_sim3
from .sim4_urban_safety_alerts import run_sim4
from .sim5_delhi_500m_city import run_sim5

__all__ = ["run_sim1", "run_sim2", "run_sim3", "run_sim4", "run_sim5"]
