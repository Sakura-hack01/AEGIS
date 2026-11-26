/**
 * AEGIS-0.5M New Delhi 500 m AGL Military-Grade Interactive City Simulation
 * - 4.0 km x 2.5 km Central New Delhi Sector (Connaught Place, Kartavya Path, India Gate, Lodhi Gardens, Yamuna ITO)
 * - 3-Stage Optics: 16 mm Wide (7.54 cm/px @ 500 m) + 1200 mm Folded Cassegrain (0.771 mm/px @ 500 m) + Boson+ LWIR
 * - 2-Stage Coarse Gimbal + 2 kHz Piezo Fast Steering Mirror (0.053 px smear @ 500 m & M0.50)
 * - Professor Briefing Tour + Interactive Click-to-Lock Millimeter & Behavioral Targets
 */
(() => {
  const canvas = document.getElementById("twinCanvas");
  const ctx = canvas.getContext("2d");

  const state = {
    mach: 0.50,
    altitudeM: 500.0,
    offNadirDeg: 0.0,
    sensorMode: "fused", // "rgb" | "lwir" | "fused" | "tele"
    gimbalActive: true,
    playing: true,
    speedMult: 1.0,
    audioOn: false,
    scenario: "mm500", // "mm500" | "foliage" | "pursuit" | "night"
    timeS: 0,
    uavX: 0.35,
    uavY: 0.45,
    uavHeadingDeg: 90,
    lockedTargetId: "DEL-MM-01",
    tourIdx: 0,
    alertLog: [],
    lastAlertSimT: -10,
    audioCtx: null,
  };

  const CFG = {
    massKg: 14.5,
    wingAreaM2: 0.48,
    cd0: 0.0185,
    kInd: 0.05614,
    delhiGroundMslM: 216.0,
    a0: 343.0,
    g: 9.80665,
    maxThrustN: 220.0,
    tsfc: 0.128,
    fuelMassKg: 3.8,
    wideSensorWmm: 13.2,
    wideFocalMm: 16.0,
    wideWidthPx: 5472,
    cassFocalMm: 1200.0,
    cassApertureMm: 150.0,
    cassPitchUm: 1.85,
    cassExposureS: 4.5e-5,
    fsmResidualRadS: 0.0018,
    mmBoltLenMm: 6.0,
    mmBoltWidMm: 2.0,
  };

  const TOUR_STAGES = [
    {
      title: "Stage 1/5 — Central New Delhi Sector (500 m AGL, Mach 0.50)",
      desc: "AEGIS-0.5M patrols at 500 m AGL (716 m MSL) over Connaught Place, Kartavya Path, India Gate, Lodhi Gardens & ITO Bridge. 220 N micro-turbojet cruises at 171.5 m/s with 20.7% thrust margin.",
      mode: "fused", scenario: "mm500", alt: 500, mach: 0.50, lock: "DEL-MM-01", gimbal: true,
    },
    {
      title: "Stage 2/5 — 500 m Millimeter Detection (1200 mm Cassegrain + Piezo FSM)",
      desc: "3-bounce folded Cassegrain (f=1200 mm, D=150 mm) achieves 0.771 mm/px GSD & 2.24 mm Rayleigh limit. Look at the bottom-right microscope loupe: a 6 mm metallic FOD bolt at India Gate resolves across 7.8 x 2.6 px with 0.053 px FSM smear!",
      mode: "tele", scenario: "mm500", alt: 500, mach: 0.50, lock: "DEL-MM-01", gimbal: true,
    },
    {
      title: "Stage 3/5 — Lodhi Gardens Canopy Occlusion & Night Blackout (RGB vs LWIR)",
      desc: "Dense Lodhi canopy & night blackout blind RGB wide sensors. FLIR Boson+ LWIR (8-14 um) + Dempster-Shafer fusion restores 100% recall on 308 K human signatures while rejecting warm car hoods.",
      mode: "fused", scenario: "foliage", alt: 500, mach: 0.50, lock: "agent-1", gimbal: true,
    },
    {
      title: "Stage 4/5 — Kartavya Path Behavioral Threat & C++23 Alert Dispatch",
      desc: "24-frame sliding-window C++23 edge kernel (0.049 ms p99) tracks pursuit convergence (#5 -> #3), restricted plaza loitering (#4), and distress pose (#6), dispatching HMAC-SHA256 authenticated alerts.",
      mode: "fused", scenario: "pursuit", alt: 500, mach: 0.50, lock: "agent-5", gimbal: true,
    },
    {
      title: "Stage 5/5 — Low-Altitude 65 m (20-Floor) High-Density Inspection Mode",
      desc: "Descending to H = 65 m switches wide 16 mm CMOS to 0.98 cm/px (51 x 173 px/human, 99.97% Johnson P(ID)) with 2-axis direct-drive gimbal slewing at 151.2 deg/s.",
      mode: "fused", scenario: "pursuit", alt: 65, mach: 0.50, lock: "agent-5", gimbal: true,
    },
  ];

  // Central New Delhi Landmarks (normalized to 4000m x 2500m sector)
  const landmarks = [
    { id: "cp", name: "CONNAUGHT PLACE", x: 0.26, y: 0.23, kind: "ring" },
    { id: "barakhamba", name: "BARAKHAMBA TOWERS", x: 0.38, y: 0.30, kind: "towers" },
    { id: "kartavya", name: "KARTAVYA PATH", x: 0.42, y: 0.53, kind: "vista" },
    { id: "indiagate", name: "INDIA GATE PLAZA", x: 0.56, y: 0.53, kind: "plaza" },
    { id: "lodhi", name: "LODHI GARDENS CANOPY", x: 0.48, y: 0.81, kind: "canopy" },
    { id: "ito", name: "ITO YAMUNA BRIDGE", x: 0.85, y: 0.34, kind: "bridge" },
  ];

  const canopies = [
    { x: 0.45, y: 0.80, r: 0.075 },
    { x: 0.51, y: 0.82, r: 0.068 },
    { x: 0.26, y: 0.23, r: 0.032 },
    { x: 0.36, y: 0.58, r: 0.042 },
  ];

  const vehicles = [
    { id: "veh-cp", x: 0.21, y: 0.34, w: 0.032, h: 0.018, vx: 0.025, vy: 0.0, tempK: 307.5, label: "Connaught Taxi (307 K)" },
    { id: "veh-ito", x: 0.72, y: 0.33, w: 0.035, h: 0.018, vx: 0.032, vy: 0.0, tempK: 306.4, label: "ITO Arterial Truck (306 K)" },
  ];

  // Millimeter-scale targets verifiable from 500 m AGL via 1200 mm Cassegrain
  const mmTargets = [
    { id: "DEL-MM-01", x: 0.56, y: 0.53, sizeMm: 6.0, label: "6.0 mm Metallic FOD Bolt (India Gate)" },
    { id: "DEL-MM-02", x: 0.42, y: 0.53, sizeMm: 4.5, label: "4.5 mm Micro-Beacon Wire (Kartavya Path)" },
    { id: "DEL-MM-03", x: 0.48, y: 0.80, sizeMm: 8.0, label: "8.0 mm Optical Marker (Lodhi Gap)" },
  ];

  const agents = [
    { id: 1, x: 0.46, y: 0.81, vx: 0.008, vy: 0.003, tempK: 308.4, role: "Lodhi Canopy Pedestrian", status: "normal" },
    { id: 2, x: 0.26, y: 0.24, vx: -0.009, vy: 0.005, tempK: 307.9, role: "Connaught Shopper", status: "normal" },
    { id: 3, x: 0.40, y: 0.52, vx: 0.011, vy: 0.001, tempK: 308.2, role: "Kartavya Jogger", status: "normal" },
    { id: 4, x: 0.58, y: 0.50, vx: 0.001, vy: 0.001, tempK: 309.0, role: "India Gate Restricted Loiterer", status: "loiter" },
    { id: 5, x: 0.31, y: 0.54, vx: 0.028, vy: -0.002, tempK: 309.4, role: "Kartavya Pursuit Vector", status: "pursuit" },
    { id: 6, x: 0.28, y: 0.22, vx: -0.004, vy: 0.003, tempK: 308.7, role: "Distress Pose Subject", status: "distress" },
  ];

  function playAlertTone() {
    if (!state.audioOn) return;
    try {
      if (!state.audioCtx) state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const ac = state.audioCtx;
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(920, ac.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1280, ac.currentTime + 0.07);
      gain.gain.setValueAtTime(0.045, ac.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.13);
      osc.connect(gain);
      gain.connect(ac.destination);
      osc.start();
      osc.stop(ac.currentTime + 0.13);
    } catch (_) {}
  }

  function airDensity(mslM) {
    const temp = Math.max(216.65, 288.15 - 0.0065 * mslM);
    const exp = CFG.g / (287.058 * 0.0065) - 1.0;
    return 1.225 * Math.pow(temp / 288.15, exp);
  }

  function computeTelemetry() {
    const M = state.mach;
    const H = state.altitudeM;
    const msl = CFG.delhiGroundMslM + H;
    const rho = airDensity(msl);
    const phi = (state.offNadirDeg * Math.PI) / 180.0;
    const cosPhi = Math.cos(phi);
    const v = M * CFG.a0;
    const beta = Math.sqrt(1 - M * M);
    const q = 0.5 * rho * v * v;
    const cl = (CFG.massKg * CFG.g) / (q * CFG.wingAreaM2);
    const cd = CFG.cd0 / beta + CFG.kInd * cl * cl;
    const thrust = q * CFG.wingAreaM2 * cd;
    const marginPct = ((CFG.maxThrustN - thrust) / CFG.maxThrustN) * 100.0;
    const fuelBurn = CFG.tsfc * thrust;
    const endurMin = (CFG.fuelMassKg / Math.max(fuelBurn, 0.1)) * 60.0;

    // Wide 16 mm GSD
    const wideGsdCm = ((H * CFG.wideSensorWmm) / (CFG.wideFocalMm * CFG.wideWidthPx)) * 100.0 / Math.pow(cosPhi, 1.5);

    // 1200 mm Folded Cassegrain GSD & Rayleigh Diffraction
    const slantM = H / cosPhi;
    const cassGsdMm = ((slantM * CFG.cassPitchUm) / CFG.cassFocalMm) / Math.sqrt(cosPhi);
    const rayleighMm = (1.22 * 0.55e-6 * slantM / (CFG.cassApertureMm * 1e-3)) * 1000.0;

    // Coarse gimbal slew rate & Piezo FSM smear
    const gimbalRateRad = (v * cosPhi * cosPhi) / H;
    const gimbalRateDeg = (gimbalRateRad * 180.0) / Math.PI;
    const uncompPx = (v * CFG.cassExposureS * 1000.0) / cassGsdMm;
    const fsmGroundMm = ((H * CFG.fsmResidualRadS * CFG.cassExposureS) / (cosPhi * cosPhi)) * 1000.0;
    const fsmSmearPx = state.gimbalActive ? fsmGroundMm / cassGsdMm : uncompPx;

    const lockEnt = getLockedEntity();
    const targetSizeMm = lockEnt.kind === "mm" ? lockEnt.sizeMm : 6.0;
    const targetLenPx = targetSizeMm / cassGsdMm;
    const targetWidPx = (targetSizeMm / 3.0) / cassGsdMm;

    let dsBelief = 0.94;
    let dsUncert = 0.04;
    let dsConflict = 0.04;
    if (state.sensorMode === "rgb") {
      dsBelief = state.scenario === "night" ? 0.05 : state.scenario === "foliage" ? 0.42 : 0.90;
      dsUncert = state.scenario === "night" ? 0.74 : 0.12;
      dsConflict = 0.02;
    } else if (state.sensorMode === "lwir") {
      dsBelief = 0.92;
      dsUncert = 0.06;
      dsConflict = 0.05;
    } else {
      dsBelief = state.gimbalActive ? 0.95 : 0.66;
      dsUncert = state.gimbalActive ? 0.04 : 0.19;
      dsConflict = state.scenario === "foliage" || state.scenario === "night" ? 0.15 : 0.03;
    }

    return {
      v, rho, q, cd, thrust, marginPct, fuelBurn, endurMin, msl, slantM,
      wideGsdCm, cassGsdMm, rayleighMm, gimbalRateDeg, fsmSmearPx,
      targetLenPx, targetWidPx, targetSizeMm, dsBelief, dsUncert, dsConflict,
    };
  }

  function updateReadout(t) {
    document.getElementById("machVal").textContent = `M ${state.mach.toFixed(2)} (${t.v.toFixed(1)} m/s)`;
    document.getElementById("altVal").textContent = `${state.altitudeM.toFixed(0)} m AGL (${t.msl.toFixed(0)} m MSL)`;
    document.getElementById("phiVal").textContent = `${state.offNadirDeg.toFixed(0)} deg`;

    document.getElementById("teleCd").textContent = `${t.cd.toFixed(4)} · ${(t.q / 1000).toFixed(1)} kPa`;
    document.getElementById("teleThrust").textContent = `${t.thrust.toFixed(1)} N (${t.marginPct.toFixed(1)}%)`;
    document.getElementById("teleFuel").textContent = `${t.fuelBurn.toFixed(1)} kg/h · ${t.endurMin.toFixed(1)}m`;
    document.getElementById("teleGimbal").textContent = `${t.gimbalRateDeg.toFixed(1)} deg/s`;

    document.getElementById("teleGsd").textContent = `${t.cassGsdMm.toFixed(3)} mm/px`;
    document.getElementById("teleRayleigh").textContent = `${t.rayleighMm.toFixed(2)} mm`;
    document.getElementById("teleWide").textContent = `${t.wideGsdCm.toFixed(2)} cm/px`;

    const antEl = document.getElementById("teleAnt");
    antEl.textContent = `${t.targetLenPx.toFixed(1)} × ${t.targetWidPx.toFixed(1)} px`;
    antEl.className = "tele-v " + (t.targetLenPx >= 3.0 && state.gimbalActive ? "ok" : "warn");

    const smearEl = document.getElementById("teleSmear");
    smearEl.textContent = `${t.fsmSmearPx.toFixed(3)} px`;
    smearEl.className = "tele-v " + (t.fsmSmearPx <= 0.5 ? "ok" : "warn");

    document.getElementById("dsBeliefBar").style.width = `${Math.round(t.dsBelief * 100)}%`;
    document.getElementById("dsBeliefVal").textContent = t.dsBelief.toFixed(2);
    document.getElementById("dsUncertBar").style.width = `${Math.round(t.dsUncert * 100)}%`;
    document.getElementById("dsUncertVal").textContent = t.dsUncert.toFixed(2);
    document.getElementById("dsConflictBar").style.width = `${Math.round(t.dsConflict * 100)}%`;
    document.getElementById("dsConflictVal").textContent = t.dsConflict.toFixed(2);
  }

  function pushAlert(type, label, score) {
    const hash = Math.abs(Math.sin(state.timeS * 81.7 + score * 37.3) * 0xffffff)
      .toString(16)
      .padStart(6, "0")
      .slice(0, 8)
      .toUpperCase();
    const entry = `[t=${state.timeS.toFixed(1)}s] <span class="alert-badge">${type}</span> · ${label} · S=${score.toFixed(2)} · HMAC=${hash}`;
    state.alertLog.unshift(entry);
    if (state.alertLog.length > 10) state.alertLog.pop();
    const feed = document.getElementById("alertFeed");
    feed.innerHTML = state.alertLog.map((e) => `<div class="alert-entry">${e}</div>`).join("");
    playAlertTone();
  }

  function stepAgents(dt) {
    const sdt = dt * state.speedMult;
    state.timeS += sdt;

    // Closed Mach 0.50 racetrack flight path over Central New Delhi
    const theta = state.timeS * (0.12 + state.mach * 0.42);
    const prevX = state.uavX;
    const prevY = state.uavY;
    state.uavX = 0.51 + 0.34 * Math.cos(theta);
    state.uavY = 0.50 + 0.31 * Math.sin(theta);
    state.uavHeadingDeg = ((Math.atan2(state.uavY - prevY, state.uavX - prevX) * 180) / Math.PI + 450) % 360;

    for (const v of vehicles) {
      v.x += v.vx * sdt;
      if (v.x > 0.90) v.x = 0.10;
    }

    for (const a of agents) {
      if (state.scenario === "pursuit" && a.id === 5) {
        const tgt = agents[2];
        const dx = tgt.x - a.x;
        const dy = tgt.y - a.y;
        const d = Math.hypot(dx, dy);
        if (d > 0.02) {
          a.x += (dx / d) * sdt * 0.055;
          a.y += (dy / d) * sdt * 0.055;
        } else {
          a.x = 0.28;
          a.y = 0.55;
        }
      } else if (a.id === 4) {
        a.x = 0.58 + 0.01 * Math.cos(state.timeS * 1.3);
        a.y = 0.50 + 0.01 * Math.sin(state.timeS * 1.3);
      } else {
        a.x += a.vx * sdt;
        a.y += a.vy * sdt;
        if (a.x < 0.14 || a.x > 0.80) a.vx *= -1;
        if (a.y < 0.16 || a.y > 0.88) a.vy *= -1;
      }
    }

    if (state.timeS - state.lastAlertSimT > 2.7) {
      state.lastAlertSimT = state.timeS;
      if (state.scenario === "pursuit") {
        pushAlert("PURSUIT_CONVERGENCE", "Kartavya Track #5 -> #3", 0.92);
      } else if (state.scenario === "mm500") {
        pushAlert("CASSEGRAIN_MM_LOCK", "India Gate 6mm FOD (7.8px @ 500m)", 0.97);
      } else {
        pushAlert("LOITER_PERIMETER", "India Gate Plaza #4", 0.79);
      }
    }
  }

  function getLockedEntity() {
    const mm = mmTargets.find((m) => m.id === state.lockedTargetId);
    if (mm) return { kind: "mm", ...mm };
    const ag = agents.find((a) => `agent-${a.id}` === state.lockedTargetId);
    if (ag) return { kind: "human", ...ag };
    const vh = vehicles.find((v) => v.id === state.lockedTargetId);
    if (vh) return { kind: "vehicle", ...vh };
    return { kind: "mm", ...mmTargets[0] };
  }

  function drawCassegrainPip(W, H, dpr, t) {
    const pipW = Math.min(295 * dpr, W * 0.32);
    const pipH = Math.min(210 * dpr, H * 0.36);
    const px = W - pipW - 14 * dpr;
    const py = H - pipH - 14 * dpr;
    const locked = getLockedEntity();

    ctx.save();
    ctx.fillStyle = "#0b0e13";
    ctx.fillRect(px, py, pipW, pipH);
    ctx.strokeStyle = "#ff1423";
    ctx.lineWidth = 1.6 * dpr;
    ctx.strokeRect(px, py, pipW, pipH);

    ctx.beginPath();
    ctx.rect(px + 2 * dpr, py + 22 * dpr, pipW - 4 * dpr, pipH - 24 * dpr);
    ctx.clip();

    const cx = px + pipW * 0.5;
    const cy = py + pipH * 0.54;

    ctx.fillStyle = state.sensorMode === "lwir" ? "#161b24" : state.scenario === "night" ? "#10141c" : "#404650";
    ctx.fillRect(px, py, pipW, pipH);

    // 0.771 mm/px sensor pixel lattice
    ctx.strokeStyle = "rgba(139, 149, 158, 0.16)";
    ctx.lineWidth = 0.7 * dpr;
    const cell = 10 * dpr;
    for (let gx = px; gx < px + pipW; gx += cell) {
      ctx.beginPath(); ctx.moveTo(gx, py); ctx.lineTo(gx, py + pipH); ctx.stroke();
    }
    for (let gy = py; gy < py + pipH; gy += cell) {
      ctx.beginPath(); ctx.moveTo(px, gy); ctx.lineTo(px + pipW, gy); ctx.stroke();
    }

    // Apply smear blur when stabilization is disabled
    const smear = state.gimbalActive ? 0 : Math.min(28, t.fsmSmearPx * 2.2) * dpr;
    if (smear > 0.5) {
      ctx.translate(Math.sin(state.timeS * 58) * smear * 0.45, 0);
    }

    if (locked.kind === "mm") {
      // Magnified millimeter-scale object (6 mm bolt / micro-wire / marker)
      const scale = Math.max(0.45, Math.min(1.6, 0.771 / Math.max(0.25, t.cassGsdMm))) * dpr;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(-0.35);
      // Metallic hex bolt / micro-beacon silhouette with specular glint
      ctx.fillStyle = state.sensorMode === "lwir" ? "#ffad5c" : "#15181e";
      ctx.fillRect(-34 * scale, -10 * scale, 52 * scale, 20 * scale);
      ctx.fillStyle = state.sensorMode === "lwir" ? "#ffe3b3" : "#750014";
      ctx.fillRect(18 * scale, -15 * scale, 16 * scale, 30 * scale);
      // Diffraction Airy ring visual cue
      ctx.strokeStyle = "rgba(255, 20, 35, 0.45)";
      ctx.lineWidth = 1.1 * dpr;
      ctx.strokeRect(-42 * scale, -20 * scale, 84 * scale, 40 * scale);
      ctx.restore();
    } else if (locked.kind === "human") {
      const grad = ctx.createRadialGradient(cx, cy, 4, cx, cy, 48 * dpr);
      grad.addColorStop(0, "rgba(255, 224, 165, 0.94)");
      grad.addColorStop(0.5, "rgba(255, 20, 35, 0.75)");
      grad.addColorStop(1, "rgba(117, 0, 20, 0)");
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(cx, cy, 48 * dpr, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#f2f4f7";
      ctx.beginPath(); ctx.ellipse(cx, cy - 11 * dpr, 10 * dpr, 10 * dpr, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(cx, cy + 12 * dpr, 20 * dpr, 11 * dpr, 0, 0, Math.PI * 2); ctx.fill();
    } else {
      ctx.fillStyle = "#5c6470";
      ctx.fillRect(cx - 52 * dpr, cy - 26 * dpr, 104 * dpr, 52 * dpr);
      ctx.fillStyle = "rgba(255, 20, 35, 0.50)";
      ctx.fillRect(cx - 48 * dpr, cy - 22 * dpr, 40 * dpr, 44 * dpr);
    }

    ctx.strokeStyle = "rgba(255, 20, 35, 0.75)";
    ctx.lineWidth = 1 * dpr;
    ctx.beginPath();
    ctx.moveTo(cx - 18 * dpr, cy); ctx.lineTo(cx - 5 * dpr, cy);
    ctx.moveTo(cx + 5 * dpr, cy); ctx.lineTo(cx + 18 * dpr, cy);
    ctx.moveTo(cx, cy - 18 * dpr); ctx.lineTo(cx, cy - 5 * dpr);
    ctx.moveTo(cx, cy + 5 * dpr); ctx.lineTo(cx, cy + 18 * dpr);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.fillStyle = "#750014";
    ctx.fillRect(px, py, pipW, 22 * dpr);
    ctx.fillStyle = "#ffffff";
    ctx.font = `700 ${9.2 * dpr}px monospace`;
    const title =
      locked.kind === "mm"
        ? `1200mm LOCK: ${locked.sizeMm.toFixed(1)}mm (${t.targetLenPx.toFixed(1)}×${t.targetWidPx.toFixed(1)}px)`
        : locked.kind === "human"
        ? `1200mm LOCK: DELHI TRACK #${locked.id}`
        : `1200mm LOCK: VEHICLE (DS VETO)`;
    ctx.fillText(title, px + 7 * dpr, py + 14 * dpr);

    ctx.fillStyle = "rgba(11, 14, 19, 0.88)";
    ctx.fillRect(px + 2 * dpr, py + pipH - 19 * dpr, pipW - 4 * dpr, 17 * dpr);
    ctx.fillStyle = t.fsmSmearPx <= 0.5 && state.gimbalActive ? "#6ee7b7" : "#ff6b78";
    ctx.font = `600 ${8.5 * dpr}px monospace`;
    ctx.fillText(
      `GSD=${t.cassGsdMm.toFixed(3)}mm/px | Ray=${t.rayleighMm.toFixed(2)}mm | FSM=${t.fsmSmearPx.toFixed(3)}px`,
      px + 7 * dpr,
      py + pipH - 7 * dpr
    );
    ctx.restore();
  }

  function drawDelhiMap(t) {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const W = Math.max(680, Math.floor(rect.width * dpr));
    const H = Math.max(420, Math.floor(rect.height * dpr));
    if (canvas.width !== W || canvas.height !== H) {
      canvas.width = W;
      canvas.height = H;
    }

    ctx.save();
    // Base backdrop
    if (state.sensorMode === "lwir") ctx.fillStyle = "#12151d";
    else if (state.scenario === "night") ctx.fillStyle = state.sensorMode === "rgb" ? "#07090e" : "#121721";
    else ctx.fillStyle = "#1f252e";
    ctx.fillRect(0, 0, W, H);

    const blurOffset = state.gimbalActive ? 0 : Math.min(20, t.fsmSmearPx * 2.0) * dpr;
    if (blurOffset > 0.5) {
      ctx.translate(Math.sin(state.timeS * 50) * blurOffset * 0.35, 0);
    }

    // 1. Yamuna River on Eastern flank
    ctx.fillStyle = state.sensorMode === "lwir" ? "#13202e" : state.scenario === "night" && state.sensorMode === "rgb" ? "#080d14" : "#1f3448";
    ctx.beginPath();
    ctx.moveTo(0.84 * W, 0);
    ctx.quadraticCurveTo(0.89 * W, 0.5 * H, 0.87 * W, H);
    ctx.lineTo(W, H);
    ctx.lineTo(W, 0);
    ctx.closePath();
    ctx.fill();

    // 2. Arterial New Delhi Roads (Kartavya Path, Ring Road, Janpath, ITO Bridge)
    ctx.strokeStyle = state.sensorMode === "lwir" ? "#262d38" : "#3a424e";
    ctx.lineWidth = 14 * dpr;
    ctx.beginPath();
    ctx.moveTo(0.18 * W, 0.53 * H); ctx.lineTo(0.60 * W, 0.53 * H); // Kartavya Path
    ctx.moveTo(0.10 * W, 0.34 * H); ctx.lineTo(0.95 * W, 0.34 * H); // ITO Bridge / Barakhamba axis
    ctx.stroke();

    ctx.lineWidth = 9 * dpr;
    ctx.beginPath();
    ctx.moveTo(0.26 * W, 0.23 * H); ctx.lineTo(0.42 * W, 0.53 * H); // Janpath
    ctx.lineTo(0.48 * W, 0.81 * H); // Lodhi axis
    ctx.stroke();

    // 3. Connaught Place Radial Inner/Outer Circle
    const cpx = 0.26 * W;
    const cpy = 0.23 * H;
    ctx.fillStyle = state.sensorMode === "lwir" ? "#212632" : "#2f3744";
    ctx.beginPath(); ctx.arc(cpx, cpy, 58 * dpr, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "#8b959e";
    ctx.lineWidth = 1.8 * dpr;
    ctx.stroke();
    ctx.fillStyle = state.sensorMode === "lwir" ? "#18241d" : "#24432a";
    ctx.beginPath(); ctx.arc(cpx, cpy, 24 * dpr, 0, Math.PI * 2); ctx.fill();

    // 4. India Gate Radial Hexagram Plaza & Restricted Zone
    const igx = 0.56 * W;
    const igy = 0.53 * H;
    ctx.fillStyle = "rgba(117, 0, 20, 0.16)";
    ctx.strokeStyle = "#ff1423";
    ctx.setLineDash([6 * dpr, 4 * dpr]);
    ctx.lineWidth = 1.6 * dpr;
    ctx.beginPath(); ctx.arc(igx, igy, 44 * dpr, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.setLineDash([]);

    // 5. Barakhamba 20-Floor Glass Towers
    for (let k = 0; k < 4; k++) {
      const bx = (0.34 + k * 0.042) * W;
      const by = (0.24 + (k % 2) * 0.05) * H;
      ctx.fillStyle = "#191d25";
      ctx.fillRect(bx, by, 26 * dpr, 22 * dpr);
      ctx.strokeStyle = "#8b959e";
      ctx.lineWidth = 1 * dpr;
      ctx.strokeRect(bx, by, 26 * dpr, 22 * dpr);
    }

    // Landmark Labels
    ctx.fillStyle = "#d6dbe0";
    ctx.font = `700 ${9.5 * dpr}px monospace`;
    for (const lm of landmarks) {
      ctx.fillText(lm.name, lm.x * W - 45 * dpr, lm.y * H - 30 * dpr);
    }

    // 6. Vehicles
    for (const v of vehicles) {
      const vx = v.x * W;
      const vy = v.y * H;
      const vw = v.w * W;
      const vh = v.h * H;
      if (state.sensorMode === "lwir") {
        ctx.fillStyle = "rgba(255, 20, 35, 0.72)";
        ctx.fillRect(vx, vy, vw, vh);
      } else {
        ctx.fillStyle = "#6c7684";
        ctx.fillRect(vx, vy, vw, vh);
      }
      ctx.strokeStyle = "#8b959e";
      ctx.strokeRect(vx, vy, vw, vh);
    }

    // 7. Millimeter Targets (Click-to-Lock!)
    for (const m of mmTargets) {
      const mx = m.x * W;
      const my = m.y * H;
      const isLock = state.lockedTargetId === m.id;
      ctx.strokeStyle = isLock ? "#ff1423" : "#00e5ff";
      ctx.lineWidth = (isLock ? 2.0 : 1.4) * dpr;
      ctx.beginPath(); ctx.arc(mx, my, 11 * dpr, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(mx - 2 * dpr, my - 2 * dpr, 4 * dpr, 4 * dpr);
      ctx.fillStyle = isLock ? "#ff6b78" : "#00e5ff";
      ctx.font = `700 ${8.8 * dpr}px monospace`;
      ctx.fillText(`${m.sizeMm.toFixed(1)}mm TARGET`, mx + 13 * dpr, my + 3 * dpr);
    }

    // 8. Human Targets
    for (const a of agents) {
      const ax = a.x * W;
      const ay = a.y * H;
      const occluded = canopies.some((c) => Math.hypot(a.x - c.x, a.y - c.y) < c.r * 0.9);
      const nightBlind = state.scenario === "night" && state.sensorMode === "rgb";

      if (state.sensorMode !== "rgb") {
        const tg = ctx.createRadialGradient(ax, ay, 1, ax, ay, 14 * dpr);
        tg.addColorStop(0, "rgba(255, 224, 160, 0.95)");
        tg.addColorStop(0.5, "rgba(255, 20, 35, 0.70)");
        tg.addColorStop(1, "rgba(117, 0, 20, 0)");
        ctx.fillStyle = tg;
        ctx.beginPath(); ctx.arc(ax, ay, 14 * dpr, 0, Math.PI * 2); ctx.fill();
      }

      if (!nightBlind && !(occluded && state.sensorMode === "rgb")) {
        ctx.fillStyle = "#edf1f5";
        ctx.beginPath(); ctx.arc(ax, ay, 4.5 * dpr, 0, Math.PI * 2); ctx.fill();
      }
    }

    // 9. Lodhi Canopy & Trees
    for (const c of canopies) {
      const cx = c.x * W;
      const cy = c.y * H;
      const cr = c.r * Math.min(W, H);
      ctx.beginPath(); ctx.arc(cx, cy, cr, 0, Math.PI * 2);
      if (state.sensorMode === "rgb") {
        ctx.fillStyle = state.scenario === "night" ? "rgba(12, 22, 14, 0.93)" : "rgba(32, 68, 36, 0.88)";
      } else if (state.sensorMode === "lwir") {
        ctx.fillStyle = "rgba(38, 46, 56, 0.25)";
      } else {
        ctx.fillStyle = "rgba(30, 62, 36, 0.40)";
      }
      ctx.fill();
      ctx.strokeStyle = "rgba(139, 149, 158, 0.4)";
      ctx.stroke();
    }

    // 10. Detection Boxes
    for (const a of agents) {
      const ax = a.x * W;
      const ay = a.y * H;
      const occluded = canopies.some((c) => Math.hypot(a.x - c.x, a.y - c.y) < c.r * 0.9);
      const nightBlind = state.scenario === "night" && state.sensorMode === "rgb";
      const detected =
        state.sensorMode === "fused" || state.sensorMode === "tele"
          ? state.gimbalActive || a.id % 2 === 1
          : state.sensorMode === "lwir"
          ? true
          : !nightBlind && !occluded;
      if (!detected) continue;

      const isAlert = (state.scenario === "pursuit" && (a.id === 5 || a.id === 6)) || a.id === 4;
      const boxCol = isAlert ? "#ff1423" : state.lockedTargetId === `agent-${a.id}` ? "#00e5ff" : "#ffffff";
      ctx.strokeStyle = boxCol;
      ctx.lineWidth = (isAlert ? 2.0 : 1.3) * dpr;
      ctx.strokeRect(ax - 9 * dpr, ay - 12 * dpr, 18 * dpr, 24 * dpr);
      ctx.fillStyle = isAlert ? "#ff1423" : "#750014";
      ctx.fillRect(ax - 9 * dpr, ay - 24 * dpr, 62 * dpr, 11 * dpr);
      ctx.fillStyle = "#ffffff";
      ctx.font = `700 ${8.2 * dpr}px monospace`;
      ctx.fillText(isAlert ? `ALERT #${a.id}` : `ID#${a.id} ${a.tempK.toFixed(0)}K`, ax - 7 * dpr, ay - 15 * dpr);
    }

    // 11. Laser Gimbal Beam + BWB UAV
    const locked = getLockedEntity();
    const ux = state.uavX * W;
    const uy = state.uavY * H;
    const lx = (locked.kind === "vehicle" ? locked.x + locked.w * 0.5 : locked.x) * W;
    const ly = (locked.kind === "vehicle" ? locked.y + locked.h * 0.5 : locked.y) * H;
    ctx.save();
    ctx.strokeStyle = "rgba(255, 20, 35, 0.55)";
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    ctx.lineWidth = 1.4 * dpr;
    ctx.beginPath(); ctx.moveTo(ux, uy); ctx.lineTo(lx, ly); ctx.stroke();
    ctx.restore();

    // UAV Racetrack Ghost Path
    ctx.save();
    ctx.strokeStyle = "rgba(139, 149, 158, 0.35)";
    ctx.setLineDash([6 * dpr, 6 * dpr]);
    ctx.lineWidth = 1.2 * dpr;
    ctx.beginPath();
    ctx.ellipse(0.51 * W, 0.50 * H, 0.34 * W, 0.31 * H, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.translate(ux, uy);
    ctx.rotate(((state.uavHeadingDeg - 90) * Math.PI) / 180);
    ctx.fillStyle = "#141619";
    ctx.strokeStyle = "#ff1423";
    ctx.lineWidth = 1.6 * dpr;
    ctx.beginPath();
    ctx.moveTo(15 * dpr, 0);
    ctx.lineTo(-10 * dpr, -17 * dpr);
    ctx.lineTo(-6 * dpr, 0);
    ctx.lineTo(-10 * dpr, 17 * dpr);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    // Top HUD Telemetry Bar
    ctx.fillStyle = "rgba(12, 15, 20, 0.86)";
    ctx.fillRect(0, 0, W, 28 * dpr);
    ctx.strokeStyle = "#750014";
    ctx.lineWidth = 2 * dpr;
    ctx.beginPath(); ctx.moveTo(0, 28 * dpr); ctx.lineTo(W, 28 * dpr); ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.font = `700 ${9.8 * dpr}px monospace`;
    ctx.fillText(
      `NEW DELHI 28.6139°N 77.2090°E  |  HDG ${state.uavHeadingDeg.toFixed(0).padStart(3, "0")}°  |  M${state.mach.toFixed(2)} (${t.v.toFixed(1)} m/s)  |  ${state.altitudeM}m AGL (${t.msl.toFixed(0)}m MSL)  |  1200mm GSD ${t.cassGsdMm.toFixed(3)} mm/px`,
      12 * dpr,
      18 * dpr
    );

    drawCassegrainPip(W, H, dpr, t);
    ctx.restore();
  }

  function applyTourStage(idx) {
    state.tourIdx = (idx + TOUR_STAGES.length) % TOUR_STAGES.length;
    const s = TOUR_STAGES[state.tourIdx];
    state.sensorMode = s.mode;
    state.scenario = s.scenario;
    state.altitudeM = s.alt;
    state.mach = s.mach;
    state.lockedTargetId = s.lock;
    state.gimbalActive = s.gimbal;

    document.getElementById("altSlider").value = String(s.alt);
    document.getElementById("machSlider").value = String(s.mach);
    document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === s.mode));
    document.querySelectorAll("[data-scenario]").forEach((b) => b.classList.toggle("active", b.dataset.scenario === s.scenario));
    document.getElementById("tourText").innerHTML = `<strong>${s.title}:</strong> ${s.desc}`;
  }

  canvas.addEventListener("click", (ev) => {
    const rect = canvas.getBoundingClientRect();
    const nx = (ev.clientX - rect.left) / rect.width;
    const ny = (ev.clientY - rect.top) / rect.height;
    let bestId = mmTargets[0].id;
    let bestD = 999;

    for (const m of mmTargets) {
      const d = Math.hypot(nx - m.x, ny - m.y);
      if (d < bestD) { bestD = d; bestId = m.id; }
    }
    for (const a of agents) {
      const d = Math.hypot(nx - a.x, ny - a.y);
      if (d < bestD) { bestD = d; bestId = `agent-${a.id}`; }
    }
    for (const v of vehicles) {
      const d = Math.hypot(nx - (v.x + v.w * 0.5), ny - (v.y + v.h * 0.5));
      if (d < bestD) { bestD = d; bestId = v.id; }
    }
    state.lockedTargetId = bestId;
  });

  document.getElementById("machSlider").addEventListener("input", (e) => { state.mach = parseFloat(e.target.value); });
  document.getElementById("altSlider").addEventListener("input", (e) => { state.altitudeM = parseFloat(e.target.value); });
  document.getElementById("phiSlider").addEventListener("input", (e) => { state.offNadirDeg = parseFloat(e.target.value); });

  document.querySelectorAll("[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-mode]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.sensorMode = btn.dataset.mode;
    });
  });

  document.querySelectorAll("[data-scenario]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-scenario]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.scenario = btn.dataset.scenario;
      if (state.scenario === "mm500") state.lockedTargetId = "DEL-MM-01";
      else if (state.scenario === "pursuit") state.lockedTargetId = "agent-5";
      else if (state.scenario === "foliage") state.lockedTargetId = "agent-1";
    });
  });

  const btnGimbal = document.getElementById("btnGimbal");
  btnGimbal.addEventListener("click", () => {
    state.gimbalActive = !state.gimbalActive;
    btnGimbal.textContent = state.gimbalActive ? "Coarse + Piezo FSM: ACTIVE" : "STABILIZATION: OFF (BLUR)";
    btnGimbal.classList.toggle("active", state.gimbalActive);
    btnGimbal.classList.toggle("btn-alert", !state.gimbalActive);
  });

  document.getElementById("btnPreset500").addEventListener("click", () => {
    state.altitudeM = 500;
    state.mach = 0.50;
    state.offNadirDeg = 0;
    state.gimbalActive = true;
    document.getElementById("altSlider").value = "500";
    document.getElementById("machSlider").value = "0.50";
    document.getElementById("phiSlider").value = "0";
  });

  document.getElementById("btnPreset65").addEventListener("click", () => {
    state.altitudeM = 65;
    state.mach = 0.50;
    state.offNadirDeg = 0;
    state.gimbalActive = true;
    document.getElementById("altSlider").value = "65";
    document.getElementById("machSlider").value = "0.50";
    document.getElementById("phiSlider").value = "0";
  });

  const btnPlay = document.getElementById("btnPlay");
  btnPlay.addEventListener("click", () => {
    state.playing = !state.playing;
    btnPlay.textContent = state.playing ? "LIVE" : "PAUSED";
    btnPlay.classList.toggle("active", state.playing);
  });

  const btnSpeed = document.getElementById("btnSpeed");
  btnSpeed.addEventListener("click", () => {
    state.speedMult = state.speedMult === 1.0 ? 2.0 : state.speedMult === 2.0 ? 0.5 : 1.0;
    btnSpeed.textContent = `${state.speedMult.toFixed(1)}×`;
  });

  const btnAudio = document.getElementById("btnAudio");
  btnAudio.addEventListener("click", () => {
    state.audioOn = !state.audioOn;
    btnAudio.textContent = state.audioOn ? "Audio: ON" : "Audio: OFF";
    btnAudio.classList.toggle("active", state.audioOn);
  });

  const theaterShell = document.getElementById("theaterShell");
  const btnFullscreen = document.getElementById("btnFullscreen");
  btnFullscreen.addEventListener("click", () => {
    const fs = theaterShell.classList.toggle("fullscreen");
    btnFullscreen.textContent = fs ? "Exit Fullscreen" : "Fullscreen";
    btnFullscreen.classList.toggle("active", fs);
  });

  document.getElementById("btnTourPrev").addEventListener("click", () => applyTourStage(state.tourIdx - 1));
  document.getElementById("btnTourNext").addEventListener("click", () => applyTourStage(state.tourIdx + 1));

  let lastTs = performance.now();
  function loop(now) {
    const dt = Math.min(0.05, (now - lastTs) / 1000.0);
    lastTs = now;
    if (state.playing) stepAgents(dt);
    const t = computeTelemetry();
    updateReadout(t);
    drawDelhiMap(t);
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();
