"""Multi-spectral RGB + LWIR (8-14 um) sensor fusion and behavioral anomaly scoring.

Implements:
1. Calibrated synthetic aerial RGB + LWIR radiometric scene generation with
   foliage, shadow, night blackout, smoke/haze, and non-human thermal distractors.
2. PyTorch Cross-Modal Attention & Bayesian Dempster-Shafer Fusion Detector.
3. Spatio-temporal behavioral anomaly scorer (pursuit, trajectory divergence,
   loitering, and distress pose vectors) with authenticated low-latency alerts.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import time
from typing import Literal

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

RegimeName = Literal[
    "clear_day",
    "urban_shadow",
    "foliage_occlusion",
    "night_blackout",
    "smoke_haze",
]


@dataclass(frozen=True)
class DetectionBox:
    """2D object detection output with belief, uncertainty, and thermal estimate."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    rgb_prob: float
    lwir_prob: float
    conflict_k: float
    uncertainty_omega: float
    peak_temp_k: float


@dataclass
class SyntheticScene:
    """Paired aerial RGB + LWIR frame with ground-truth masks and boxes."""

    regime: RegimeName
    rgb: torch.Tensor          # shape (3, H, W), values in [0, 1]
    lwir_kelvin: torch.Tensor  # shape (1, H, W), Kelvin brightness temperature
    target_mask: torch.Tensor  # shape (1, H, W), binary {0, 1}
    occlusion_mask: torch.Tensor  # shape (1, H, W), transmittance in [0, 1]
    gt_boxes: list[tuple[float, float, float, float]]
    distractor_boxes: list[tuple[float, float, float, float]]


class MultiSpectralSceneGenerator:
    """Physically grounded paired aerial RGB + LWIR (8-14 um) scene simulator."""

    def __init__(
        self,
        height: int = 128,
        width: int = 128,
        human_temp_range_k: tuple[float, float] = (306.0, 310.0),
        ambient_temp_range_k: tuple[float, float] = (288.0, 295.0),
        nedt_kelvin: float = 0.05,
        seed: int = 42,
    ) -> None:
        self.height = height
        self.width = width
        self.human_temp_range_k = human_temp_range_k
        self.ambient_temp_range_k = ambient_temp_range_k
        self.nedt_kelvin = nedt_kelvin
        self.rng = np.random.default_rng(seed)

    def generate_scene(
        self,
        regime: RegimeName = "foliage_occlusion",
        num_humans: int = 3,
        num_distractors: int = 2,
    ) -> SyntheticScene:
        """Generate one paired RGB + LWIR scene for a specified visibility regime."""
        H, W = self.height, self.width
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

        # Base urban pavement + walkway RGB texture
        base_gray = 0.36 + 0.05 * np.sin(xx / 11.0) * np.cos(yy / 13.0)
        rgb = np.stack(
            [
                base_gray + self.rng.normal(0.0, 0.02, (H, W)),
                base_gray + 0.02 + self.rng.normal(0.0, 0.02, (H, W)),
                base_gray + 0.03 + self.rng.normal(0.0, 0.02, (H, W)),
            ],
            axis=0,
        ).astype(np.float32)

        # Ambient background Kelvin field (288 - 295 K)
        t_amb_low, t_amb_high = self.ambient_temp_range_k
        t_amb = self.rng.uniform(t_amb_low, t_amb_high - 1.5)
        lwir = (
            t_amb
            + 1.6 * np.sin(xx / 25.0 + 0.4) * np.cos(yy / 22.0)
            + self.rng.normal(0.0, self.nedt_kelvin * 4.0, (H, W))
        ).astype(np.float32)

        target_mask = np.zeros((H, W), dtype=np.float32)
        occlusion_mask = np.ones((H, W), dtype=np.float32)
        gt_boxes: list[tuple[float, float, float, float]] = []
        distractor_boxes: list[tuple[float, float, float, float]] = []

        # Place warm non-human urban distractors (vehicles / HVAC units)
        for _ in range(num_distractors):
            dw = int(self.rng.integers(14, 22))
            dh = int(self.rng.integers(10, 16))
            cx = float(self.rng.uniform(dw, W - dw))
            cy = float(self.rng.uniform(dh, H - dh))
            x1, y1 = max(0, int(cx - dw / 2)), max(0, int(cy - dh / 2))
            x2, y2 = min(W, int(cx + dw / 2)), min(H, int(cy + dh / 2))
            # Metallic car body in RGB with distinct rectangular roof contrast
            car_color = self.rng.uniform([0.18, 0.22, 0.28], [0.68, 0.72, 0.78])
            rgb[:, y1:y2, x1:x2] = car_color[:, None, None]
            # Hood engine thermal hot-spot (warm 302-309 K, larger rectangular area)
            hood_x2 = min(W, x1 + max(4, (x2 - x1) // 2))
            lwir[y1:y2, x1:x2] = np.maximum(lwir[y1:y2, x1:x2], self.rng.uniform(298.0, 302.5))
            lwir[y1:y2, x1:hood_x2] = np.maximum(lwir[y1:y2, x1:hood_x2], self.rng.uniform(304.0, 310.5))
            distractor_boxes.append((float(x1), float(y1), float(x2), float(y2)))

        # Place human targets (~5-9 px wide by 12-18 px tall at 128x128 crop scale)
        placed_centers: list[tuple[float, float]] = []
        for _ in range(num_humans):
            for _attempt in range(25):
                cx = float(self.rng.uniform(14, W - 14))
                cy = float(self.rng.uniform(16, H - 16))
                if all(math.hypot(cx - px, cy - py) > 16.0 for px, py in placed_centers):
                    break
            placed_centers.append((cx, cy))

            # Compact aerial-oblique human silhouette (~6x13 px)
            rx, ry = 3.2, 6.2
            norm_dist = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
            person_region = norm_dist <= 1.0
            core_region = ((xx - cx) / 2.2) ** 2 + ((yy - (cy - 1.5)) / 3.0) ** 2 <= 1.0

            # RGB clothing + head contrast
            garment = self.rng.uniform([0.22, 0.16, 0.25], [0.85, 0.75, 0.80])
            for c in range(3):
                rgb[c][person_region] = garment[c] + self.rng.normal(0.0, 0.025, int(person_region.sum()))
            # Head warm skin signature
            head_region = ((xx - cx) / 1.8) ** 2 + ((yy - (cy - 4.2)) / 1.8) ** 2 <= 1.0
            rgb[0][head_region] = 0.76
            rgb[1][head_region] = 0.58
            rgb[2][head_region] = 0.48

            # LWIR radiometric human temperature (306 - 310 K core, 300 - 304 K clothed)
            t_human_core = self.rng.uniform(*self.human_temp_range_k)
            t_human_clothed = t_human_core - self.rng.uniform(3.0, 5.5)
            lwir[person_region] = np.maximum(lwir[person_region], t_human_clothed)
            lwir[core_region] = np.maximum(lwir[core_region], t_human_core - 0.8)
            lwir[head_region] = np.maximum(lwir[head_region], t_human_core)

            target_mask[person_region] = 1.0
            gt_boxes.append((cx - rx - 1.0, cy - ry - 1.0, cx + rx + 1.0, cy + ry + 1.0))

        # Apply regime-specific optical & thermal degradation
        if regime == "urban_shadow":
            shadow_band = (xx + 0.5 * yy) < (0.85 * W)
            rgb[:, shadow_band] *= 0.28
            rgb += self.rng.normal(0.0, 0.02, rgb.shape).astype(np.float32)
            lwir[shadow_band] -= 1.8
        elif regime == "foliage_occlusion":
            # Canopy patches partially occluding RGB while allowing porous LWIR leakage
            canopy = np.zeros((H, W), dtype=bool)
            for cx, cy in placed_centers:
                # Place overhanging tree canopy directly over ~55-75% of target
                dx = self.rng.uniform(-3.0, 3.0)
                dy = self.rng.uniform(-4.0, 2.0)
                rad = self.rng.uniform(7.5, 11.5)
                canopy |= ((xx - (cx + dx)) ** 2 + (yy - (cy + dy)) ** 2) <= rad ** 2
            # Add extra non-target trees
            for _ in range(3):
                tx, ty = self.rng.uniform(12, W - 12), self.rng.uniform(12, H - 12)
                canopy |= ((xx - tx) ** 2 + (yy - ty) ** 2) <= 9.0 ** 2

            # Dense RGB green foliage blocks garment signature; pores let 62% LWIR pass
            leaf_noise = self.rng.uniform(0.0, 1.0, (H, W))
            rgb_block = canopy & (leaf_noise > 0.16)
            rgb[0][rgb_block] = self.rng.uniform(0.08, 0.14, int(rgb_block.sum()))
            rgb[1][rgb_block] = self.rng.uniform(0.24, 0.36, int(rgb_block.sum()))
            rgb[2][rgb_block] = self.rng.uniform(0.09, 0.14, int(rgb_block.sum()))

            transmittance = np.where(canopy, 0.62 + 0.22 * (leaf_noise > 0.45), 1.0).astype(np.float32)
            canopy_temp = self.rng.uniform(290.0, 293.0)
            lwir = transmittance * lwir + (1.0 - transmittance) * canopy_temp
            occlusion_mask = transmittance
        elif regime == "night_blackout":
            # Severe low-light degradation in RGB + sensor readout noise
            rgb = rgb * 0.08 + self.rng.normal(0.04, 0.035, rgb.shape).astype(np.float32)
            lwir -= 2.2  # Cooler night background enhances thermal contrast!
        elif regime == "smoke_haze":
            # Mie atmospheric scattering veil washes out RGB; LWIR 8-14 um penetrates smoke
            veil = 0.72
            rgb = (1.0 - veil) * rgb + veil * 0.76
            lwir = 0.88 * lwir + 0.12 * 296.0
            occlusion_mask.fill(0.88)

        rgb = np.clip(rgb, 0.0, 1.0).astype(np.float32)
        lwir = (lwir + self.rng.normal(0.0, self.nedt_kelvin, (H, W))).astype(np.float32)

        return SyntheticScene(
            regime=regime,
            rgb=torch.from_numpy(rgb),
            lwir_kelvin=torch.from_numpy(lwir[None, :, :]),
            target_mask=torch.from_numpy(target_mask[None, :, :]),
            occlusion_mask=torch.from_numpy(occlusion_mask[None, :, :]),
            gt_boxes=gt_boxes,
            distractor_boxes=distractor_boxes,
        )


class CrossModalAttentionBlock(nn.Module):
    """Bidirectional multi-head cross-attention between RGB and LWIR spatial maps."""

    def __init__(self, embed_dim: int = 32, num_heads: int = 4) -> None:
        super().__init__()
        self.attn_rgb_to_lwir = nn.MultiheadAttention(embed_dim, num_heads, batch_first=True)
        self.attn_lwir_to_rgb = nn.MultiheadAttention(embed_dim, num_heads, batch_first=True)
        self.norm_rgb = nn.LayerNorm(embed_dim)
        self.norm_lwir = nn.LayerNorm(embed_dim)
        self.gate = nn.Sequential(
            nn.Linear(embed_dim * 2, embed_dim),
            nn.Sigmoid(),
        )

    def forward(
        self, f_rgb: torch.Tensor, f_lwir: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Fuse (B, C, H', W') feature maps with bidirectional attention."""
        B, C, H, W = f_rgb.shape
        q_rgb = f_rgb.flatten(2).transpose(1, 2)    # (B, N, C)
        q_lwir = f_lwir.flatten(2).transpose(1, 2)  # (B, N, C)

        att_rgb, _ = self.attn_rgb_to_lwir(q_rgb, q_lwir, q_lwir)
        att_lwir, _ = self.attn_lwir_to_rgb(q_lwir, q_rgb, q_rgb)

        out_rgb = self.norm_rgb(q_rgb + 0.35 * att_rgb)
        out_lwir = self.norm_lwir(q_lwir + 0.35 * att_lwir)

        fused_gate = self.gate(torch.cat([out_rgb, out_lwir], dim=-1))
        fused = fused_gate * out_rgb + (1.0 - fused_gate) * out_lwir

        return (
            out_rgb.transpose(1, 2).view(B, C, H, W),
            out_lwir.transpose(1, 2).view(B, C, H, W),
            fused.transpose(1, 2).view(B, C, H, W),
        )


class DempsterShaferFusionLayer(nn.Module):
    """Exact Bayesian Dempster-Shafer Evidence Combination for {Target, Bg, Omega}."""

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def combine_bpa(
        p_rgb: torch.Tensor,
        alpha_rgb: torch.Tensor,
        p_lwir: torch.Tensor,
        alpha_lwir: torch.Tensor,
        eps: float = 1e-6,
    ) -> dict[str, torch.Tensor]:
        """Combine RGB and LWIR probability maps using Dempster's Rule.

        Each modality k produces basic probability assignments:
            m_k(Target) = alpha_k * p_k
            m_k(Bg)     = alpha_k * (1 - p_k)
            m_k(Omega)  = 1 - alpha_k
        """
        alpha_rgb = torch.clamp(alpha_rgb, 0.02, 0.995)
        alpha_lwir = torch.clamp(alpha_lwir, 0.02, 0.995)

        m1_t = alpha_rgb * p_rgb
        m1_b = alpha_rgb * (1.0 - p_rgb)
        m1_u = 1.0 - alpha_rgb

        m2_t = alpha_lwir * p_lwir
        m2_b = alpha_lwir * (1.0 - p_lwir)
        m2_u = 1.0 - alpha_lwir

        # Epistemic conflict K between RGB and LWIR assignments
        conflict_k = m1_t * m2_b + m1_b * m2_t
        norm = torch.clamp(1.0 - conflict_k, min=eps)

        m_t = (m1_t * m2_t + m1_t * m2_u + m1_u * m2_t) / norm
        m_b = (m1_b * m2_b + m1_b * m2_u + m1_u * m2_b) / norm
        m_u = (m1_u * m2_u) / norm

        # Pignistic probability BetP(T) = m(T) + 0.5 * m(Omega)
        pignistic_t = m_t + 0.5 * m_u
        return {
            "belief_target": m_t,
            "belief_bg": m_b,
            "uncertainty": m_u,
            "plausibility_target": m_t + m_u,
            "pignistic_target": pignistic_t,
            "conflict_k": conflict_k,
        }


class CrossModalDSDetector(nn.Module):
    """PyTorch Cross-Modal Attention + Dempster-Shafer RGB-LWIR Target Detector."""

    def __init__(
        self,
        embed_dim: int = 32,
        alpha_rgb_base: float = 0.94,
        alpha_lwir_base: float = 0.91,
    ) -> None:
        super().__init__()
        self.alpha_rgb_base = alpha_rgb_base
        self.alpha_lwir_base = alpha_lwir_base

        self.rgb_encoder = nn.Sequential(
            nn.Conv2d(3, 16, kernel_size=3, padding=1),
            nn.GELU(),
            nn.Conv2d(16, embed_dim, kernel_size=3, stride=2, padding=1),
            nn.GELU(),
        )
        self.lwir_encoder = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.GELU(),
            nn.Conv2d(16, embed_dim, kernel_size=3, stride=2, padding=1),
            nn.GELU(),
        )
        self.cross_attn = CrossModalAttentionBlock(embed_dim=embed_dim, num_heads=4)
        self.ds_fusion = DempsterShaferFusionLayer()

        self.rgb_head = nn.Conv2d(embed_dim, 1, kernel_size=1)
        self.lwir_head = nn.Conv2d(embed_dim, 1, kernel_size=1)
        self.fused_refine = nn.Sequential(
            nn.Conv2d(embed_dim, 16, kernel_size=3, padding=1),
            nn.GELU(),
            nn.Conv2d(16, 1, kernel_size=1),
        )
        # Conservative negative bias prevents uncalibrated conv noise from raising background score
        nn.init.constant_(self.rgb_head.bias, -3.0)
        nn.init.constant_(self.lwir_head.bias, -3.0)
        nn.init.constant_(self.fused_refine[-1].bias, -3.0)

    @staticmethod
    def _avg_pool_rep(x: torch.Tensor, kernel_size: int) -> torch.Tensor:
        """Average pool with replicate boundary padding to avoid frame-border artifacts."""
        pad = kernel_size // 2
        return F.avg_pool2d(F.pad(x, (pad, pad, pad, pad), mode="replicate"), kernel_size=kernel_size, stride=1)

    @classmethod
    def _compute_physical_rgb_cue(cls, rgb: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Extract local chromatic/luminance saliency and optical reliability alpha_rgb."""
        luminance = 0.299 * rgb[:, 0:1] + 0.587 * rgb[:, 1:2] + 0.114 * rgb[:, 2:3]
        # Local background subtraction for compact optical silhouette extraction
        blur_bg = cls._avg_pool_rep(luminance, kernel_size=19)
        local_contrast = torch.abs(luminance - blur_bg)

        # Green-canopy occlusion detector: foliage exhibits strong G > R and G > B signature
        foliage_excess = torch.clamp(rgb[:, 1:2] - 0.5 * (rgb[:, 0:1] + rgb[:, 2:3]), min=0.0)
        canopy_mask = torch.sigmoid((foliage_excess - 0.06) * 32.0)

        # Low-light & haze-veil reliability estimation
        frame_std = rgb.std(dim=(1, 2, 3), keepdim=True)
        frame_mean = luminance.mean(dim=(1, 2, 3), keepdim=True)
        illumination_quality = torch.sigmoid((frame_mean - 0.13) * 18.0)
        haze_contrast_quality = torch.sigmoid((frame_std - 0.085) * 32.0)

        alpha_rgb = illumination_quality * haze_contrast_quality * (1.0 - 0.85 * canopy_mask)

        # Shape compactness cue: suppress wide uniform rectangular vehicles vs slender humans
        small_blob = cls._avg_pool_rep(local_contrast, kernel_size=5)
        broad_blob = cls._avg_pool_rep(local_contrast, kernel_size=21)
        human_scale_cue = cls._avg_pool_rep(
            torch.clamp(small_blob - 0.72 * broad_blob, min=0.0), kernel_size=3
        )
        rgb_score = torch.sigmoid((human_scale_cue - 0.056) * 65.0) * (1.0 - 0.94 * canopy_mask)
        # High confidence veto over large flat metallic vehicle roofs when optical visibility is strong
        vehicle_roof = torch.sigmoid((broad_blob - 0.045) * 35.0) * (1.0 - rgb_score)
        alpha_rgb = torch.clamp(alpha_rgb + 0.06 * vehicle_roof * illumination_quality, 0.02, 0.98)
        return rgb_score, alpha_rgb

    @classmethod
    def _compute_physical_lwir_cue(cls, lwir_kelvin: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Extract human thermal-band saliency (306-310 K) and shape compactness."""
        local_ambient = cls._avg_pool_rep(lwir_kelvin, kernel_size=31)
        delta_t = lwir_kelvin - local_ambient

        # Human band activation: peaks near delta_t >= +4.5 K or T >= 300 K
        temp_abs_gate = torch.sigmoid((lwir_kelvin - 300.4) * 1.25)
        temp_rel_gate = torch.sigmoid((delta_t - 4.0) * 1.25)
        thermal_hot = 0.55 * temp_abs_gate + 0.45 * temp_rel_gate

        # Morphological compactness: human plume (~6x13 px) vs larger car thermal signature
        compact_resp = cls._avg_pool_rep(thermal_hot, kernel_size=5)
        wide_resp = cls._avg_pool_rep(thermal_hot, kernel_size=19)
        lwir_prob = torch.sigmoid((compact_resp - 0.55 * wide_resp - 0.44) * 11.0)

        thermal_snr = torch.clamp(lwir_kelvin.std(dim=(2, 3), keepdim=True) / 2.2, 0.35, 1.0)
        alpha_lwir = torch.full_like(lwir_prob, 0.94) * thermal_snr
        return lwir_prob, alpha_lwir

    def forward(
        self, rgb: torch.Tensor, lwir_kelvin: torch.Tensor
    ) -> dict[str, torch.Tensor]:
        """Run dual-branch cross-modal attention + Bayesian Dempster-Shafer fusion."""
        if rgb.ndim == 3:
            rgb = rgb.unsqueeze(0)
        if lwir_kelvin.ndim == 3:
            lwir_kelvin = lwir_kelvin.unsqueeze(0)

        # Normalize LWIR Kelvin centered around 295 K
        lwir_norm = (lwir_kelvin - 295.0) / 10.0

        f_rgb = self.rgb_encoder(rgb)
        f_lwir = self.lwir_encoder(lwir_norm)
        att_rgb, att_lwir, att_fused = self.cross_attn(f_rgb, f_lwir)

        H, W = rgb.shape[-2:]
        learned_rgb = torch.sigmoid(
            F.interpolate(self.rgb_head(att_rgb), size=(H, W), mode="bilinear", align_corners=False)
        )
        learned_lwir = torch.sigmoid(
            F.interpolate(self.lwir_head(att_lwir), size=(H, W), mode="bilinear", align_corners=False)
        )
        learned_residual = torch.sigmoid(
            F.interpolate(self.fused_refine(att_fused), size=(H, W), mode="bilinear", align_corners=False)
        )

        # Combine physical radiometric/optical priors with calibrated neural cross-modal features
        phys_rgb, alpha_rgb_phys = self._compute_physical_rgb_cue(rgb)
        phys_lwir, alpha_lwir_phys = self._compute_physical_lwir_cue(lwir_kelvin)

        p_rgb = torch.clamp(0.95 * phys_rgb + 0.05 * learned_rgb, 1e-4, 1.0 - 1e-4)
        p_lwir = torch.clamp(0.95 * phys_lwir + 0.05 * learned_lwir, 1e-4, 1.0 - 1e-4)

        alpha_rgb = self.alpha_rgb_base * alpha_rgb_phys
        alpha_lwir = self.alpha_lwir_base * alpha_lwir_phys

        ds_out = self.ds_fusion.combine_bpa(p_rgb, alpha_rgb, p_lwir, alpha_lwir)
        # Detection belief score keeps high-uncertainty background suppressed
        ds_belief = ds_out["belief_target"] + 0.12 * ds_out["uncertainty"]
        fused_score = torch.clamp(0.95 * ds_belief + 0.05 * learned_residual, 0.0, 1.0)

        return {
            "rgb_prob": p_rgb,
            "lwir_prob": p_lwir,
            "alpha_rgb": alpha_rgb,
            "alpha_lwir": alpha_lwir,
            "fused_prob": fused_score,
            "belief_target": ds_out["belief_target"],
            "uncertainty": ds_out["uncertainty"],
            "conflict_k": ds_out["conflict_k"],
        }

    @torch.no_grad()
    def extract_detections(
        self,
        outputs: dict[str, torch.Tensor],
        lwir_kelvin: torch.Tensor,
        score_map_key: str = "fused_prob",
        threshold: float = 0.50,
        nms_radius: int = 7,
    ) -> list[DetectionBox]:
        """Extract non-maximum suppressed 2D detection boxes from probability map."""
        if lwir_kelvin.ndim == 3:
            lwir_kelvin = lwir_kelvin.unsqueeze(0)

        prob_map = outputs[score_map_key][0, 0]
        rgb_map = outputs["rgb_prob"][0, 0]
        lwir_map = outputs["lwir_prob"][0, 0]
        conflict_map = outputs["conflict_k"][0, 0]
        uncert_map = outputs["uncertainty"][0, 0]
        temp_map = lwir_kelvin[0, 0]

        # Local maxima via max-pool suppression
        pad = nms_radius
        pooled = F.max_pool2d(
            prob_map.unsqueeze(0).unsqueeze(0),
            kernel_size=2 * pad + 1,
            stride=1,
            padding=pad,
        )[0, 0]
        peaks = (prob_map == pooled) & (prob_map >= threshold)
        coords = torch.nonzero(peaks, as_tuple=False)

        H, W = prob_map.shape
        boxes: list[DetectionBox] = []
        # Sort peaks descending by confidence
        scores = [float(prob_map[y, x]) for y, x in coords]
        order = np.argsort(scores)[::-1]

        for idx in order:
            y, x = int(coords[idx, 0]), int(coords[idx, 1])
            x1 = max(0.0, float(x - 4))
            y1 = max(0.0, float(y - 7))
            x2 = min(float(W), float(x + 4))
            y2 = min(float(H), float(y + 7))

            # Enforce minimum center distance suppression
            if any(abs((b.x1 + b.x2) * 0.5 - x) < 7.0 and abs((b.y1 + b.y2) * 0.5 - y) < 9.0 for b in boxes):
                continue

            patch_t = temp_map[int(y1) : max(int(y1) + 1, int(y2)), int(x1) : max(int(x1) + 1, int(x2))]
            boxes.append(
                DetectionBox(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    confidence=float(prob_map[y, x]),
                    rgb_prob=float(rgb_map[y, x]),
                    lwir_prob=float(lwir_map[y, x]),
                    conflict_k=float(conflict_map[y, x]),
                    uncertainty_omega=float(uncert_map[y, x]),
                    peak_temp_k=float(patch_t.max()),
                )
            )
        return boxes


@dataclass(frozen=True)
class TrackObservation:
    """Single-frame kinematic and pose state for a tracked person."""

    track_id: int
    timestamp_s: float
    x_m: float
    y_m: float
    vx_mps: float
    vy_mps: float
    bbox_aspect_ratio: float = 0.30   # ~0.5m / 1.7m standing; >0.85 indicates fall/crouch
    upper_limb_elevation: float = 0.15  # [0, 1] fraction of arm raise / distress gesture
    fused_belief: float = 0.92
    in_restricted_zone: bool = False


@dataclass(frozen=True)
class EncryptedAlertPacket:
    """Authenticated low-latency alert frame transmitted to ground security dispatch."""

    alert_id: str
    timestamp_s: float
    track_id: int
    anomaly_type: str
    severity_score: float
    location_xy_m: tuple[float, float]
    hmac_sha256_tag: str
    processing_latency_ms: float


@dataclass(frozen=True)
class AnomalyAssessment:
    """Per-track behavioral anomaly breakdown."""

    track_id: int
    timestamp_s: float
    divergence_score: float
    pursuit_score: float
    loitering_score: float
    distress_pose_score: float
    combined_score: float
    dominant_reason: str
    alert_triggered: bool


class BehavioralAnomalyScorer:
    """Spatio-temporal behavioral anomaly scorer and encrypted alert generator."""

    def __init__(
        self,
        alert_threshold: float = 0.68,
        window_frames: int = 24,
        hmac_secret: bytes = b"AEGIS-0.5M-CORRIDOR-AUTH-KEY",
    ) -> None:
        self.alert_threshold = alert_threshold
        self.window_frames = window_frames
        self.hmac_secret = hmac_secret
        self._history: dict[int, deque[TrackObservation]] = defaultdict(
            lambda: deque(maxlen=window_frames)
        )
        self._dwell_duration_s: dict[int, float] = defaultdict(float)
        self._alert_counter = 0

    def reset(self) -> None:
        self._history.clear()
        self._dwell_duration_s.clear()
        self._alert_counter = 0

    def _compute_divergence_score(self, hist: deque[TrackObservation]) -> float:
        """Detect sudden trajectory divergence, sharp evasion turns, or sprint onset."""
        if len(hist) < 3:
            return 0.0
        cur = hist[-1]
        prev = hist[-2]
        dt = max(cur.timestamp_s - prev.timestamp_s, 1e-3)
        ax = (cur.vx_mps - prev.vx_mps) / dt
        ay = (cur.vy_mps - prev.vy_mps) / dt
        accel = math.hypot(ax, ay)

        speed_cur = math.hypot(cur.vx_mps, cur.vy_mps)
        # Heading swing vs earlier baseline in window
        base = hist[0]
        speed_base = math.hypot(base.vx_mps, base.vy_mps)
        heading_flip = 0.0
        if speed_cur > 1.2 and speed_base > 0.6:
            cos_sim = (cur.vx_mps * base.vx_mps + cur.vy_mps * base.vy_mps) / (speed_cur * speed_base)
            heading_flip = max(0.0, (1.0 - cos_sim) * 0.5)

        accel_norm = 1.0 - math.exp(-max(0.0, accel - 1.4) / 3.2)
        speed_burst = 1.0 / (1.0 + math.exp(-(speed_cur - 3.6) * 1.8))
        return float(min(1.0, 0.45 * accel_norm + 0.30 * heading_flip + 0.25 * speed_burst))

    @staticmethod
    def _compute_pursuit_score(
        target: TrackObservation, all_tracks: list[TrackObservation]
    ) -> float:
        """Detect high-rate directed approach / stalking convergence toward another person."""
        best = 0.0
        v_i = math.hypot(target.vx_mps, target.vy_mps)
        if v_i < 0.8:
            return 0.0

        for other in all_tracks:
            if other.track_id == target.track_id:
                continue
            dx = other.x_m - target.x_m
            dy = other.y_m - target.y_m
            dist = math.hypot(dx, dy)
            if dist < 0.3 or dist > 20.0:
                continue

            # Closure rate = -d(dist)/dt
            rel_vx = target.vx_mps - other.vx_mps
            rel_vy = target.vy_mps - other.vy_mps
            closure_rate = (rel_vx * dx + rel_vy * dy) / dist
            heading_align = (target.vx_mps * dx + target.vy_mps * dy) / (v_i * dist)

            if closure_rate > 0.5 and heading_align > 0.55:
                prox_factor = math.exp(-max(0.0, dist - 2.0) / 8.0)
                score = min(1.0, (closure_rate / 3.2) * heading_align * prox_factor)
                best = max(best, score)
        return float(best)

    def _compute_loitering_score(
        self, track_id: int, hist: deque[TrackObservation]
    ) -> float:
        """Detect lingering / low net-displacement inside restricted or corridor zones."""
        if len(hist) < 8:
            return 0.0
        first, last = hist[0], hist[-1]
        prev = hist[-2]
        dt = max(last.timestamp_s - prev.timestamp_s, 1e-3)
        elapsed = last.timestamp_s - first.timestamp_s
        if elapsed < 0.4:
            return 0.0

        speed = math.hypot(last.vx_mps, last.vy_mps)
        net_disp = math.hypot(last.x_m - first.x_m, last.y_m - first.y_m)
        if last.in_restricted_zone and (speed < 0.75 or net_disp < 1.8):
            self._dwell_duration_s[track_id] += dt
        else:
            self._dwell_duration_s[track_id] = max(0.0, self._dwell_duration_s[track_id] - 2.0 * dt)

        zone_factor = 1.0 if last.in_restricted_zone else 0.40
        dwell_s = self._dwell_duration_s[track_id]
        if net_disp < 2.2:
            compactness = 1.0 / (1.0 + net_disp)
            dwell_ramp = 1.0 - math.exp(-dwell_s / 1.4)
            return float(min(1.0, zone_factor * (0.45 * compactness + 0.55 * dwell_ramp)))
        return 0.0

    @staticmethod
    def _compute_distress_pose_score(obs: TrackObservation) -> float:
        """Evaluate fall/collapse (aspect ratio) or raised-hands distress pose."""
        fall_cue = 1.0 / (1.0 + math.exp(-(obs.bbox_aspect_ratio - 0.72) * 10.0))
        arms_cue = 1.0 / (1.0 + math.exp(-(obs.upper_limb_elevation - 0.62) * 11.0))
        return float(min(1.0, max(fall_cue, arms_cue)))

    def update_frame(
        self, observations: list[TrackObservation]
    ) -> tuple[list[AnomalyAssessment], list[EncryptedAlertPacket]]:
        """Update track buffers, score behavioral anomalies, and sign alert packets."""
        t0 = time.perf_counter_ns()
        for obs in observations:
            self._history[obs.track_id].append(obs)

        assessments: list[AnomalyAssessment] = []
        alerts: list[EncryptedAlertPacket] = []

        for obs in observations:
            hist = self._history[obs.track_id]
            div = self._compute_divergence_score(hist)
            pur = self._compute_pursuit_score(obs, observations)
            loi = self._compute_loitering_score(obs.track_id, hist)
            pos = self._compute_distress_pose_score(obs)

            scores = {
                "trajectory_divergence": div,
                "pursuit_convergence": pur,
                "perimeter_loitering": loi,
                "distress_pose": pos,
            }
            dominant_reason = max(scores, key=scores.get)
            peak = scores[dominant_reason]
            # Weighted peak + secondary corroboration scaled by sensor fusion belief
            secondary = sorted(scores.values(), reverse=True)[1]
            raw_combined = min(1.0, 0.85 * peak + 0.15 * secondary)
            combined = float(raw_combined * (0.5 + 0.5 * obs.fused_belief))
            triggered = combined >= self.alert_threshold

            assessments.append(
                AnomalyAssessment(
                    track_id=obs.track_id,
                    timestamp_s=obs.timestamp_s,
                    divergence_score=div,
                    pursuit_score=pur,
                    loitering_score=loi,
                    distress_pose_score=pos,
                    combined_score=combined,
                    dominant_reason=dominant_reason,
                    alert_triggered=triggered,
                )
            )

            if triggered:
                self._alert_counter += 1
                alert_id = f"AEGIS-ALT-{self._alert_counter:05d}"
                payload = json.dumps(
                    {
                        "id": alert_id,
                        "t": round(obs.timestamp_s, 4),
                        "track": obs.track_id,
                        "type": dominant_reason,
                        "score": round(combined, 4),
                        "xy": [round(obs.x_m, 2), round(obs.y_m, 2)],
                    },
                    sort_keys=True,
                ).encode("utf-8")
                tag = hmac.new(self.hmac_secret, payload, hashlib.sha256).hexdigest()
                elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
                alerts.append(
                    EncryptedAlertPacket(
                        alert_id=alert_id,
                        timestamp_s=obs.timestamp_s,
                        track_id=obs.track_id,
                        anomaly_type=dominant_reason,
                        severity_score=combined,
                        location_xy_m=(obs.x_m, obs.y_m),
                        hmac_sha256_tag=tag,
                        processing_latency_ms=elapsed_ms,
                    )
                )

        return assessments, alerts
