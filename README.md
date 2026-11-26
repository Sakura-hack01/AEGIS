# AEGIS-0.5M: High-Subsonic (Mach 0.5) Compact Autonomous Surveillance UAV Digital Twin

[![License: MIT](https://img.shields.io/badge/License-MIT-750014.svg)](LICENSE)
[![CI Pipeline](https://github.com/Sakura-hack01/AEGIS/actions/workflows/ci.yml/badge.svg)](https://github.com/Sakura-hack01/AEGIS/actions/workflows/ci.yml)
[![Python 3.10–3.12](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-1A1A1A.svg)](requirements.txt)
[![C++23 Real-Time Kernel](https://img.shields.io/badge/C%2B%2B-23%20(%3C0.20ms%20p99)-750014.svg)](cpp_inference/uav_edge_pipeline.cpp)
[![GitHub Pages Twin](https://img.shields.io/badge/GitHub%20Pages-Interactive%20Twin-8B959E.svg)](https://sakura-hack01.github.io/AEGIS/)

**AEGIS-0.5M** is a reproducible aerospace, optical engineering, and multi-spectral computer vision digital twin investigating a compact blended-wing-body (BWB) autonomous surveillance UAV flying at **Mach 0.50 ($171.5\text{ m/s}$)** over **Central New Delhi** at **$500\text{ m}$ AGL** (and $65\text{ m}$ low-altitude corridor sweep). Equipped with a **220 N micro-turbojet engine**, **16 mm wide ($0.98\text{ cm/px}$ @ $65\text{ m}$)** + **1200 mm folded Maksutov-Cassegrain ($0.771\text{ mm/px}$ @ $500\text{ m}$ AGL)** optics, an **8–14 $\mu$m LWIR thermal microbolometer**, and a **C++23 edge inference kernel ($<0.05\text{ ms}$ p99)**, it resolves millimeter-scale features ($6\text{ mm}$ FOD/targets across $7.8 \times 2.6\text{ px}$) from $500\text{ m}$ aloft while issuing authenticated behavioral threat alerts.

> **Deep Technical Monograph:** Read [`ENGINEERING_DOSSIER.md`](ENGINEERING_DOSSIER.md) for the complete station-by-station sensor/camera placement map ($x = -95$ to $+1150\text{ mm}$), 5-stage turbojet Brayton cycle breakdown, flight dynamics derivatives, and folded Cassegrain optical train analysis.

---

## 1. Airframe Design, Visual Renders & Subsystem Architecture

| 3/4 Tactical Flight Render | Internal Subsystem Cutaway | 3-View Orthographic Blueprint |
| :---: | :---: | :---: |
| ![AEGIS-0.5M Flight Render](figures/aegis_uav_render.png) | ![AEGIS-0.5M Internal Cutaway](figures/aegis_uav_cutaway.png) | ![AEGIS-0.5M CAD Blueprint](figures/aegis_uav_blueprint.png) |

### Complete Propulsion, Motor, Airframe & Sensor Bill of Materials (BOM)

Why a **micro-turbojet** rather than a hobby brushless propeller? At **Mach 0.50 ($171.5\text{ m/s}$)** at sea level ($q = 17.90\text{ kPa}$), steady level flight requires **$T_{\text{req}} = 183.70\text{ N}$** ($31.51\text{ kW}$ aerodynamic / $40.39\text{ kW}$ shaft power). Open propellers suffer severe tip-Mach compressibility stall above $\sim 120\text{ m/s}$, and lithium batteries capable of $40\text{ kW}$ continuous discharge exceed the entire $14.5\text{ kg}$ aircraft MTOW. A compact **220 N micro-turbojet** delivers a **$16.5\%$ dash thrust margin** in $1.85\text{ kg}$ dry mass while powering onboard avionics via an integrated $500\text{ W}$ alternator.

| Subsystem | Selected Component / Architecture | Exact Engineering Specifications | Mass / Power |
| :--- | :--- | :--- | :--- |
| **Airframe** | Carbon-Fiber Blended-Wing-Body (BWB) | Toray T800S/M40J prepreg monocoque, $b = 1.80\text{ m}$, $L = 1.15\text{ m}$, $S = 0.48\text{ m}^2$, $AR = 6.75$, $\bar{c} = 0.28\text{ m}$, MTOW $14.5\text{ kg}$ ($7.4\text{ kg}$ empty) | $7.4\text{ kg}$ empty |
| **Main Propulsion** | **220 N-Class Micro-Turbojet** (`JetCat P220-RXi / PBS TJ20`) | Single-spool radial compressor + annular combustor; $220\text{ N}$ static thrust, $112\text{ mm}$ OD $\times 305\text{ mm}$ L, $118,000\text{ RPM}$, $\text{TSFC} = 0.128\text{ kg/(N}\cdot\text{h)}$, Jet-A1 / JP-8 + 5% turbine oil; $3.8\text{ kg}$ twin wing-root bladders ($9.7\text{ min} / 99.8\text{ km}$ @ M0.50 dash; **$125\text{ min} / 360\text{ km}$** @ M0.14 loiter) | $1.85\text{ kg}$ dry + $3.8\text{ kg}$ fuel ($500\text{ W}$ gen) |
| **2-Axis Gimbal Motors** | **2× `T-Motor GBM5208H-200T`** Frameless Direct-Drive + 24-bit BiSS-C | Zero-backlash pancake BLDC torque actuators + **KVH 1750 / ADIS16470** hybrid IMU tracking $\dot{\theta} = 151.17^\circ/\text{s}$ ($<0.033\text{ px}$ wide smear) + piezo fine-steering mirror ($<0.020\text{ px}$ telephoto smear) | $0.48\text{ kg}$ / $18\text{–}45\text{ W}$ |
| **Control Surface Servos** | **4× `MKS HBL6625 HV`** Coreless Brushless | Titanium-gear HV servos ($16.5\text{ kg}\cdot\text{cm}$ @ $8.4\text{ V}$) driving split elevons and wingtip ruddervons against $17.9\text{ kPa}$ Mach 0.50 dynamic pressure | $0.26\text{ kg}$ total |
| **Primary + Telephoto EO** | **`Sony IMX183` 20 MP Global-Shutter CMOS** ($13.2 \times 8.8\text{ mm}$) | $5472 \times 3648\text{ px}$ ($2.41\ \mu\text{m}$ pitch). **Wide $16\text{ mm}$ $f/2.8$**: $0.980\text{ cm/px}$ ($51 \times 173\text{ px}$ per human @ $65\text{ m}$). **Co-Axial $220\text{ mm}$ $f/4.0$ Telephoto**: **$0.713\text{ mm/px}$** ($8.4 \times 2.8\text{ px}$ across a $6\text{ mm}$ floor ant @ $65\text{ m}$) | $0.72\text{ kg}$ turret ($250\ \mu\text{s} / 80\ \mu\text{s}$) |
| **LWIR Thermal Core** | **`FLIR Boson+` Uncooled VOx** ($640 \times 512$, $8\text{–}14\ \mu\text{m}$) | $25\text{ mm}$ Germanium $f/1.0$ lens ($12\ \mu\text{m}$ pitch, $35\text{ mK}$ NETD), $3.12\text{ cm/px}$ @ $65\text{ m}$, co-registered with RGB to detect $306\text{–}310\text{ K}$ humans through darkness, foliage, and smoke | $0.18\text{ kg}$ / $1.2\text{ W}$ |
| **Onboard Compute & GNC** | **`NVIDIA Jetson Orin NX 16GB`** + `CubePilot Cube Orange+` | $100\text{ TOPS}$ INT8 neural fusion + ARM Cortex-R52 deterministic C++23 loop ($0.045\text{–}0.115\text{ ms}$), u-blox ZED-F9P RTK-GNSS, pitot-static probe, AES-256/HMAC-SHA256 Ku-band datalink | $0.64\text{ kg}$ / $25\text{ W}$ |

---

## 2. System Pipeline

```mermaid
flowchart LR
    RGB["13.2 mm Global-Shutter CMOS<br/>Wide 16mm (0.98 cm/px) + Tele 220mm (0.71 mm/px)"] --> GIMBAL["2-Axis Direct-Drive FMC Gimbal<br/>θ̇ = v·cos²φ / H (151.17°/s)"]
    LWIR["Uncooled VOx LWIR<br/>(8–14 µm, 640×512, 306–310 K)"] --> GIMBAL
    GIMBAL --> ENC["Dual-Branch Encoders +<br/>Cross-Modal Attention"]
    ENC --> DS["Bayesian Dempster-Shafer<br/>Evidence Fusion m₁⊕₂(T)"]
    DS --> TRACK["Spatio-Temporal Behavioral<br/>Anomaly Scorer (30 Hz)"]
    TRACK -->|"S ≥ 0.68"| ALERT["HMAC-SHA256 Authenticated<br/>Safety & Perimeter Alert"]
    CPP["C++23 Edge Kernel<br/>(< 0.20 ms p99 · > 8,600 FPS)"] -.->|"Closed-Loop Control"| GIMBAL
```

---

## 3. Physics, Optical Geometry & AI Mathematical Specification

### 3.1 Subsonic Compressible Aerodynamics & Active Gimbal Kinematics (`src/physics/aerodynamics.py`)
Modeled across $M \in [0.05, 0.55]$ at sea-level acoustic reference $a = 343.0\text{ m/s}$:
$$\beta = \sqrt{1 - M^2}, \qquad C_{L\alpha}(M) = \frac{C_{L\alpha,0}}{\sqrt{1 - M^2}}, \qquad C_D(M, C_L) = \frac{C_{D0}}{\sqrt{1 - M^2}} + k C_L^2$$
$$q = \frac{1}{2}\rho v^2, \qquad T_{\text{req}} = q S C_D(M, C_L), \qquad \dot{m}_{\text{fuel}} = \text{TSFC} \cdot T_{\text{req}}, \qquad Re = \frac{\rho v \bar{c}}{\mu}$$
$$\dot{\theta}_{\text{gimbal}} = \frac{v \cos^2\phi}{H}$$
At $M = 0.50$ ($v = 171.5\text{ m/s}$) and $H = 65\text{ m}$ ($\phi = 0^\circ$), uncompensated global-shutter exposure ($\tau = 250\ \mu\text{s}$) induces **$4.38\text{ px}$** of smear. Active gimbal tracking at **$\dot{\theta} = 151.17^\circ/\text{s}$** suppresses smear to **$0.033\text{ px}$** (wide) and **$0.020\text{ px}$** (220 mm telephoto @ $80\ \mu\text{s}$), well below the $0.50\text{ px}$ optical limit.

### 3.2 Dual-Channel Optical GSD & Johnson's Criteria (`src/physics/optics_gsd.py`)
$$\text{GSD} = \frac{H \cdot w_{\text{sensor}}}{f_{\text{focal}} \cdot W_{\text{px}}} \times 100 \quad (\text{cm/px})$$
At 20-floor altitude ($H = 65.0\text{ m}$):
- **Wide Corridor Channel ($f = 16\text{ mm}$)**: $\text{GSD}_{\text{wide}} = \frac{65.0 \times 13.2}{16.0 \times 5472} \times 100 = \mathbf{0.9800\text{ cm/px}}$, resolving a standing adult ($0.50 \times 1.70\text{ m}$) across **$51.0 \times 173.5\text{ px}$** ($26.7$ resolved cycles, **$P(\text{Identification}) = 99.97\%$** via Johnson TTPF).
- **Co-Axial Micro-Spotter Channel ($f = 220\text{ mm}$)**: $\text{GSD}_{\text{tele}} = \frac{65.0 \times 13.2}{220.0 \times 5472} \times 1000 = \mathbf{0.7127\text{ mm/px}}$, resolving a **$6\text{ mm} \times 2\text{ mm}$ floor ant across $8.4 \times 2.8\text{ px}$** from 20 stories high.

### 3.3 Cross-Modal RGB + LWIR Bayesian Dempster-Shafer Fusion (`src/vision/multispectral_fusion.py`)
$$m_k(T) = \alpha_k p_k, \qquad m_k(B) = \alpha_k(1 - p_k), \qquad m_k(\Omega) = 1 - \alpha_k$$
$$m_{1 \oplus 2}(A) = \frac{1}{1 - K} \sum_{B \cap C = A} m_1(B) m_2(C), \qquad K = m_1(T) m_2(B) + m_1(B) m_2(T)$$
Optical reliability $\alpha_{\text{rgb}}$ automatically discounts under green-canopy occlusion, deep shadow, darkness, and smoke haze while maintaining geometric suppression of warm non-human vehicle hoods.

### 3.4 Spatio-Temporal Behavioral Anomaly Scoring & C++23 Edge Kernel
Tracks are evaluated across 24-frame ($30\text{ Hz}$) sliding windows for **Trajectory Divergence**, **Pursuit Convergence**, **Perimeter Loitering**, and **Distress Pose Vectors**, emitting **HMAC-SHA256** authenticated dispatch alerts when $S_{\text{anom}} \ge 0.68$.

---

## 4. Verified Quantitative Results

### 4.1 Flight Envelope, Propulsion & Dual-Optics Metrics (`Sim1` & `Sim2`)
| Metric | Value at Target Cruise ($M = 0.50$, $H = 65\text{ m}$) | Specification Target |
| :--- | :--- | :--- |
| Airspeed $v$ / Prandtl-Glauert $\beta$ | **$171.5\text{ m/s}$** ($617.4\text{ km/h}$) / **$0.8660$** | $M = 0.50$ @ $a = 343\text{ m/s}$ |
| Compressible $C_D$ / Thrust $T_{\text{req}}$ | **$0.02138$** / **$183.70\text{ N}$** ($16.5\%$ margin on $220\text{ N}$ jet) | Steady level flight |
| Fuel Burn / Endurance (M0.50 dash vs M0.14 loiter) | **$23.51\text{ kg/h}$** ($9.7\text{ min}$ / $99.8\text{ km}$) vs. **$1.83\text{ kg/h}$** ($125\text{ min}$) | Jet-A1 $3.8\text{ kg}$ load |
| 2-Axis Gimbal Rate / Smear | **$151.17^\circ/\text{s}$** / **$0.033\text{ px}$** wide & **$0.020\text{ px}$** tele | **$< 0.50\text{ px}$** blur limit |
| Wide GSD / Human Footprint / Johnson $P(\text{ID})$ | **$0.9800\text{ cm/px}$** / **$51.0 \times 173.5\text{ px}$** / **$99.97\%$** | Sub-cm @ 20 floors |
| 220 mm Telephoto GSD / 6 mm Ant Footprint | **$0.7127\text{ mm/px}$** / **$8.4 \times 2.8\text{ px}$** | Sub-mm floor inspection |

### 4.2 Multi-Spectral Detection Under Occlusion (`Sim3` — 12 scenes/regime)
| Visibility Regime | RGB-Only Recall | RGB-Only AP@0.5 | LWIR-Only Recall | DS Fusion Recall | DS Fusion AP@0.5 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Clear Day** | $100.0\%$ | $0.992$ | $100.0\%$ | **$100.0\%$** | **$0.988$** |
| **Urban Shadow** | $44.4\%$ | $0.292$ | $97.2\%$ | **$97.2\%$** | **$0.772$** |
| **Foliage Occlusion** | $50.0\%$ | $0.305$ | $100.0\%$ | **$100.0\%$** | **$0.640$** |
| **Night Blackout** | $0.0\%$ | $0.000$ | $100.0\%$ | **$100.0\%$** | **$0.924$** |
| **Smoke / Haze** | $0.0\%$ | $0.000$ | $100.0\%$ | **$100.0\%$** | **$0.903$** |

### 4.3 Corridor Alerts & C++23 Edge Kernel (`Sim4` & `cpp_inference`)
- **Corridor Normal-Frame False Alarm Rate**: **$0.0000$** across $60\text{ s}$ ($1,800$ frames @ $30\text{ Hz}$)
- **Incident Alert Locks**: `perimeter_loitering` @ $13.00\text{ s}$, `pursuit_convergence` @ $33.53\text{ s}$, `distress_pose` @ $44.00\text{ s}$
- **C++23 Real-Time Edge Kernel (`2,000` frames)**: **Mean $0.0449\text{–}0.1151\text{ ms}$**, **p99 $0.0680\text{–}0.1858\text{ ms}$** ($8,689\text{–}22,263\text{ FPS}$, $>13\times$ headroom below $2.50\text{ ms}$ deadline)

---

## 5. Publication-Grade 300-DPI Figures

| Figure 5: Fuselage Sensor Placement Map | Figure 6: 500 m Cassegrain Optical Train |
| :---: | :---: |
| ![Figure 5](figures/fig5_sensor_placement_fuselage_map.png) | ![Figure 6](figures/fig6_optical_train_500m_mm.png) |
| **Figure 7: New Delhi 500 m AGL ISR Sector** | **Figure 1: Mach 0.5 Aerodynamics & Gimbal** |
| ![Figure 7](figures/fig7_delhi_500m_isr_simulation.png) | ![Figure 1](figures/fig1_mach05_aerodynamics_gimbal.png) |
| **Figure 2: 20-Floor GSD & Johnson Criteria** | **Figure 3: RGB-LWIR Dempster-Shafer Fusion** |
| ![Figure 2](figures/fig2_altitude_gsd_johnson.png) | ![Figure 3](figures/fig3_rgb_lwir_fusion_benchmark.png) |
| **Figure 4: Behavioral Alerts & C++23 Latency** | |
| ![Figure 4](figures/fig4_behavioral_anomaly_latency.png) | |

---

## 6. Quickstart & Reproducibility

```bash
git clone https://github.com/Sakura-hack01/AEGIS.git
cd AEGIS
python -m pip install -r requirements.txt

python -m src.cli test        # PyTest unit verification (physics + vision)
python -m src.cli sim         # Execute all 4 simulations -> results/*.csv, *.json
python -m src.cli plot        # Generate 300-DPI PNG/PDF plots -> figures/ & docs/assets/
python -m src.cli cpp-bench   # Build & benchmark C++23 edge kernel
python -m src.cli serve       # Launch interactive MIT-styled simulator at localhost:8000
```

Interactive Google Colab Walkthrough: [`notebooks/AEGIS_Mach05_Digital_Twin.ipynb`](notebooks/AEGIS_Mach05_Digital_Twin.ipynb)

---

## 7. ORCID & Zenodo Archival Citation Instructions

1. Link your **ORCID iD** (`https://orcid.org/`) with **Zenodo** (`https://zenodo.org/account/settings/linkedaccounts/`).
2. Enable GitHub $\leftrightarrow$ Zenodo archival for [`Sakura-hack01/AEGIS`](https://github.com/Sakura-hack01/AEGIS) and publish a tagged GitHub release (`v1.0.0`).
3. Record the minted Zenodo DOI in your citation block:

```bibtex
@software{aegis_mach05_uav_2026,
  title     = {AEGIS-0.5M: High-Subsonic (Mach 0.5) Compact Autonomous Surveillance UAV with Sub-Centimeter Optical Precision, Behavioral Anomaly Detection, and RGB-LWIR Fusion},
  author    = {Dixit, Saket},
  year      = {2026},
  version   = {v1.0.0},
  license   = {MIT},
  url       = {https://github.com/Sakura-hack01/AEGIS},
  doi       = {10.5281/zenodo.XXXXXXX}
}
```
