"""Unified CLI for AEGIS-0.5M digital twin (`python -m src.cli test|sim|plot|cpp-bench|serve`)."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def cmd_test() -> int:
    """Run pytest test suite."""
    return subprocess.call([sys.executable, "-m", "pytest", "-v"], cwd=REPO_ROOT)


def cmd_sim() -> int:
    """Run all four reproducible simulations."""
    os.chdir(REPO_ROOT)
    from simulations.sim1_mach05_envelope import run_sim1
    from simulations.sim2_altitude_gsd_precision import run_sim2
    from simulations.sim3_rgb_lwir_occlusion import run_sim3
    from simulations.sim4_urban_safety_alerts import run_sim4
    from simulations.sim5_delhi_500m_city import run_sim5

    s1 = run_sim1(REPO_ROOT / "configs/uav_mission_profile.yaml", REPO_ROOT / "results")
    c = s1["cruise_mach_050"]
    print(
        f"[Sim1] Mach {c['mach']:.2f} ({c['airspeed_mps']:.1f} m/s) | "
        f"CD={c['cd_total']:.5f} | T={c['thrust_required_n']:.2f} N | "
        f"Gimbal={c['gimbal_angular_rate_deg_s']:.2f} deg/s | "
        f"Smear={c['uncompensated_smear_px']:.2f}->{c['stabilized_smear_px']:.3f} px"
    )

    s2 = run_sim2(REPO_ROOT / "configs/uav_mission_profile.yaml", REPO_ROOT / "results")
    sw = s2["sweet_spot_65m_20floors"]
    print(
        f"[Sim2] H={sw['altitude_m']:.1f} m (~{sw['approx_building_floors']:.0f} floors) | "
        f"GSD={sw['gsd_nadir_cm_px']:.4f} cm/px | "
        f"Human={sw['human_width_px']:.1f}x{sw['human_height_px']:.1f} px | "
        f"P(ID)={sw['p_identification']*100:.2f}%"
    )

    s3 = run_sim3(REPO_ROOT / "results")
    for r in s3["results"]:
        if r["modality"] == "RGB+LWIR-DS-Fusion":
            print(
                f"[Sim3] {r['regime']:18s} | DS-Fusion Recall={r['recall']:.3f} | "
                f"AP50={r['ap_50']:.3f} | FAR={r['false_alarm_rate_per_frame']:.3f}"
            )

    s4 = run_sim4(REPO_ROOT / "results")
    print(
        f"[Sim4] Corridor FAR={s4['false_alarm_rate_normal_frames']:.4f} | "
        f"First Alerts={s4['first_alert_timestamps_s']}"
    )

    s5 = run_sim5(REPO_ROOT / "configs/uav_mission_profile.yaml", REPO_ROOT / "results")
    c5 = s5["cassegrain_500m_nadir"]
    print(
        f"[Sim5] Delhi 500m AGL | GSD={c5['gsd_mm_px']:.3f} mm/px | "
        f"Rayleigh={c5['rayleigh_diffraction_mm']:.2f} mm | "
        f"6mm Target={c5['target_6mm_length_px']:.2f} px | "
        f"FSM Smear={c5['fsm_stabilized_smear_px']:.3f} px"
    )
    return 0


def cmd_plot() -> int:
    """Generate 300-DPI PNG and PDF publication figures."""
    os.chdir(REPO_ROOT)
    from visualization.plot_figures import generate_all_figures

    paths = generate_all_figures(
        results_dir=REPO_ROOT / "results",
        figures_dir=REPO_ROOT / "figures",
        docs_assets_dir=REPO_ROOT / "docs/assets",
    )
    for p in paths:
        print(f"[Plot] {p}")
    return 0


def cmd_cpp_bench() -> int:
    """Compile and run the zero-dependency C++23 real-time edge inference kernel."""
    cpp_src = REPO_ROOT / "cpp_inference/uav_edge_pipeline.cpp"
    out_json = REPO_ROOT / "results/cpp_benchmark.json"
    (REPO_ROOT / "results").mkdir(parents=True, exist_ok=True)

    exe_name = "uav_edge_pipeline.exe" if os.name == "nt" else "uav_edge_pipeline"
    bin_path = REPO_ROOT / "cpp_inference" / exe_name

    if not bin_path.exists():
        gxx = shutil.which("g++")
        clangxx = shutil.which("clang++")
        if gxx and os.name != "nt":
            subprocess.check_call(
                [gxx, "-std=c++23", "-O3", "-Wall", "-Wextra", str(cpp_src), "-o", str(bin_path)]
            )
        elif clangxx:
            subprocess.check_call(
                [clangxx, "-std=c++23", "-O3", "-Wall", "-Wextra", str(cpp_src), "-o", str(bin_path)]
            )
        elif gxx:
            subprocess.check_call(
                [gxx, "-std=c++23", "-O3", "-Wall", "-Wextra", str(cpp_src), "-o", str(bin_path)]
            )
        else:
            raise RuntimeError("No prebuilt binary or C++23 compiler found on PATH.")

    return subprocess.call([str(bin_path), "--frames", "2000", "--json-out", str(out_json)])


def cmd_serve(port: int = 8000) -> int:
    """Serve the MIT-styled GitHub Pages interactive dashboard locally."""
    docs_dir = REPO_ROOT / "docs"
    handler = partial(SimpleHTTPRequestHandler, directory=str(docs_dir))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Serving AEGIS-0.5M GitHub Pages dashboard at http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aegis-mach05-uav",
        description="AEGIS-0.5M Aerospace & Multi-Spectral Surveillance Digital Twin CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("test", help="Run pytest unit test suite")
    sub.add_parser("sim", help="Run all 4 physics, optics, fusion, and safety simulations")
    sub.add_parser("plot", help="Generate 4 publication-grade 300-DPI figures")
    sub.add_parser("cpp-bench", help="Build and benchmark the C++23 real-time edge kernel")
    serve_p = sub.add_parser("serve", help="Serve interactive GitHub Pages dashboard locally")
    serve_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.command == "test":
        return cmd_test()
    if args.command == "sim":
        return cmd_sim()
    if args.command == "plot":
        return cmd_plot()
    if args.command == "cpp-bench":
        return cmd_cpp_bench()
    if args.command == "serve":
        return cmd_serve(args.port)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
