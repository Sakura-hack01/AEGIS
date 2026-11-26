/**
 * AEGIS-0.5M Military-Grade C4ISR Interactive Digital Twin
 * - Wide 16mm (0.98 cm/px @ 65m) + Co-Axial 220mm Telephoto Loupe (0.71 mm/px @ 65m)
 * - Exact Prandtl-Glauert + 220N Micro-Turbojet Fuel Burn + 2-Axis Gimbal FMC
 * - Click-to-Lock Targets (including 6 mm courtyard ant/micro-marker!)
 * - Optional synthesized Web Audio tactical threat alert tone
 */
(() => {
  const canvas = document.getElementById("twinCanvas");
  const ctx = canvas.getContext("2d");

  const state = {
    mach: 0.50,
    altitudeM: 65.0,
    offNadirDeg: 0.0,
    sensorMode: "fused", // "rgb" | "lwir" | "fused" | "tele"
    gimbalActive: true,
    playing: true,
    speedMult: 1.0,
    audioOn: false,
    scenario: "foliage", // "foliage" | "night" | "pursuit" | "ant"
    timeS: 0,
    uavX: 0.16,
    uavY: 0.14,
    uavHeadingDeg: 90,
    lockedTargetId: "ant-micro", // default shows both wide view + PiP lock or user click
    alertLog: [],
    lastAlertSimT: -10,
    audioCtx: null,
  };

  const CFG = {
    massKg: 14.5,
    wingAreaM2: 0.48,
    cd0: 0.0185,
    kInd: 0.05614,
    rho: 1.2174,
    a0: 343.0,
    g: 9.80665,
    maxThrustN: 220.0,
    tsfc: 0.128,
    fuelMassKg: 3.8,
    sensorWmm: 13.2,
    wideFocalMm: 16.0,
    teleFocalMm: 220.0,
    widthPx: 5472,
    wideExposureS: 2.5e-4,
    teleExposureS: 8.0e-5,
    servoResidual: 0.0045,
    imuJitter: 0.008,
    humanWm: 0.50,
    humanHm: 1.70,
    humanCritM: 0.75,
    antLenMm: 6.0,
    antWidMm: 2.0,
  };

  const canopies = [
    { x: 0.27, y: 0.36, r: 0.075 },
    { x: 0.55, y: 0.62, r: 0.088 },
    { x: 0.73, y: 0.30, r: 0.070 },
    { x: 0.39, y: 0.72, r: 0.062 },
  ];

  const vehicles = [
    { id: "veh-1", x: 0.16, y: 0.79, w: 0.085, h: 0.048, tempK: 307.2, label: "Sedan (307 K Hood)" },
    { id: "veh-2", x: 0.81, y: 0.78, w: 0.085, h: 0.048, tempK: 305.8, label: "Utility Van (306 K)" },
  ];

  // Floor-level 6 mm micro-target ("Ant / Micro-FOD Reference") on courtyard concrete
  const microTarget = {
    id: "ant-micro",
    x: 0.49,
    y: 0.51,
    vx: 0.0018,
    vy: 0.0010,
    tempK: 294.2,
    label: "6 mm Floor Ant / Micro-Ref",
  };

  const agents = [
    { id: 1, x: 0.27, y: 0.37, vx: 0.012, vy: 0.004, tempK: 308.4, role: "Under-Canopy Pedestrian", status: "normal" },
    { id: 2, x: 0.56, y: 0.61, vx: -0.011, vy: 0.006, tempK: 307.9, role: "Corridor Pedestrian", status: "normal" },
    { id: 3, x: 0.44, y: 0.45, vx: 0.015, vy: -0.004, tempK: 308.2, role: "Student Commuter", status: "normal" },
    { id: 4, x: 0.73, y: 0.30, vx: 0.002, vy: 0.002, tempK: 309.1, role: "Perimeter Loiterer", status: "loiter" },
    { id: 5, x: 0.33, y: 0.49, vx: 0.036, vy: -0.005, tempK: 309.4, role: "Pursuit Vector", status: "pursuit" },
    { id: 6, x: 0.62, y: 0.47, vx: -0.008, vy: 0.005, tempK: 308.8, role: "Distress Pose Subject", status: "distress" },
  ];

  function playAlertTone() {
    if (!state.audioOn) return;
    try {
      if (!state.audioCtx) state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const ac = state.audioCtx;
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(880, ac.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1240, ac.currentTime + 0.08);
      gain.gain.setValueAtTime(0.05, ac.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.14);
      osc.connect(gain);
      gain.connect(ac.destination);
      osc.start();
      osc.stop(ac.currentTime + 0.14);
    } catch (_) {}
  }

  function johnsonTtpf(cycles, n50) {
    if (cycles <= 0) return 0;
    const r = cycles / n50;
    const e = 2.7 + 0.7 * r;
    const p = Math.pow(r, e);
    return p / (1 + p);
  }

  function computeTelemetry() {
    const M = state.mach;
    const H = state.altitudeM;
    const phi = (state.offNadirDeg * Math.PI) / 180.0;
    const cosPhi = Math.cos(phi);
    const v = M * CFG.a0;
    const beta = Math.sqrt(1 - M * M);
    const q = 0.5 * CFG.rho * v * v;
    const cl = (CFG.massKg * CFG.g) / (q * CFG.wingAreaM2);
    const cd = CFG.cd0 / beta + CFG.kInd * cl * cl;
    const thrust = q * CFG.wingAreaM2 * cd;
    const marginPct = ((CFG.maxThrustN - thrust) / CFG.maxThrustN) * 100.0;
    const fuelBurn = CFG.tsfc * thrust;
    const endurMin = (CFG.fuelMassKg / Math.max(fuelBurn, 0.1)) * 60.0;

    // Wide 16mm Optics
    const gsdWideNadirCm = ((H * CFG.sensorWmm) / (CFG.wideFocalMm * CFG.widthPx)) * 100.0;
    const gsdWideMeanCm = Math.sqrt((gsdWideNadirCm / cosPhi) * (gsdWideNadirCm / (cosPhi * cosPhi)));
    const gsdWideM = gsdWideMeanCm / 100.0;

    // Co-Axial 220mm Telephoto Micro-Optics
    const gsdTeleCm = ((H * CFG.sensorWmm) / (CFG.teleFocalMm * CFG.widthPx)) * 100.0 / Math.pow(cosPhi, 1.5);
    const gsdTeleMm = gsdTeleCm * 10.0;

    // Gimbal FMC Kinematics
    const gimbalRateRad = (v * cosPhi * cosPhi) / H;
    const gimbalRateDeg = (gimbalRateRad * 180.0) / Math.PI;
    const uncompWidePx = (v * CFG.wideExposureS) / gsdWideM;
    const resWideErr = CFG.servoResidual * gimbalRateRad + CFG.imuJitter;
    const stabWidePx = ((H * resWideErr * CFG.wideExposureS) / (cosPhi * cosPhi)) / gsdWideM;
    const wideSmearPx = state.gimbalActive ? stabWidePx : uncompWidePx;

    const uncompTelePx = ((v * CFG.teleExposureS) * 1000.0) / gsdTeleMm;
    const resTeleErr = 0.0006 * gimbalRateRad + 0.0012;
    const stabTelePx = (((H * resTeleErr * CFG.teleExposureS) / (cosPhi * cosPhi)) * 1000.0) / gsdTeleMm;
    const teleSmearPx = state.gimbalActive ? stabTelePx : uncompTelePx;

    const smearFactor = Math.sqrt(1 + Math.pow(wideSmearPx / 0.5, 2));
    const gsdEffM = gsdWideM * (smearFactor / 0.70);
    const cycles = CFG.humanCritM / (2.0 * gsdEffM);
    const pId = johnsonTtpf(cycles, 6.4) * 100.0;

    const humanW = CFG.humanWm / gsdWideM;
    const humanH = CFG.humanHm / gsdWideM;
    const antLenPx = CFG.antLenMm / gsdTeleMm;
    const antWidPx = CFG.antWidMm / gsdTeleMm;

    // Dempster-Shafer diagnostic belief on current regime & mode
    let dsBelief = 0.93;
    let dsUncert = 0.05;
    let dsConflict = 0.04;
    if (state.sensorMode === "rgb") {
      dsBelief = state.scenario === "night" ? 0.06 : state.scenario === "foliage" ? 0.44 : 0.89;
      dsUncert = state.scenario === "night" ? 0.72 : 0.14;
      dsConflict = 0.02;
    } else if (state.sensorMode === "lwir") {
      dsBelief = 0.91;
      dsUncert = 0.07;
      dsConflict = 0.05;
    } else {
      dsBelief = state.gimbalActive ? 0.94 : 0.68;
      dsUncert = state.gimbalActive ? 0.04 : 0.18;
      dsConflict = state.scenario === "foliage" || state.scenario === "night" ? 0.14 : 0.03;
    }

    return {
      v, beta, q, cd, thrust, marginPct, fuelBurn, endurMin,
      gimbalRateDeg, wideSmearPx, teleSmearPx, gsdWideMeanCm, gsdTeleMm,
      humanW, humanH, antLenPx, antWidPx, pId, dsBelief, dsUncert, dsConflict,
      slantRangeM: H / cosPhi,
    };
  }

  function updateReadout(t) {
    document.getElementById("machVal").textContent = `M ${state.mach.toFixed(2)} (${t.v.toFixed(1)} m/s)`;
    const floors = Math.round(state.altitudeM / 3.25);
    document.getElementById("altVal").textContent = `${state.altitudeM.toFixed(0)} m (~${floors} floors)`;
    document.getElementById("phiVal").textContent = `${state.offNadirDeg.toFixed(0)} deg`;

    document.getElementById("teleCd").textContent = t.cd.toFixed(4);
    document.getElementById("teleThrust").textContent = `${t.thrust.toFixed(1)} N (${t.marginPct.toFixed(1)}%)`;
    document.getElementById("teleFuel").textContent = `${t.fuelBurn.toFixed(1)} kg/h · ${t.endurMin.toFixed(1)}m`;
    document.getElementById("teleGimbal").textContent = `${t.gimbalRateDeg.toFixed(1)} deg/s`;

    const smearEl = document.getElementById("teleSmear");
    smearEl.textContent = `${t.wideSmearPx.toFixed(3)} / ${t.teleSmearPx.toFixed(3)} px`;
    smearEl.className = "tele-v " + (t.wideSmearPx <= 0.5 ? "ok" : "warn");

    document.getElementById("teleGsd").textContent = `${t.gsdWideMeanCm.toFixed(2)} cm / ${t.gsdTeleMm.toFixed(2)} mm`;
    document.getElementById("teleHuman").textContent = `${Math.round(t.humanW)} × ${Math.round(t.humanH)} px`;

    const antEl = document.getElementById("teleAnt");
    antEl.textContent = `${t.antLenPx.toFixed(1)} × ${t.antWidPx.toFixed(1)} px`;
    antEl.className = "tele-v " + (t.antLenPx >= 4.0 && state.gimbalActive ? "ok" : "warn");

    const pidEl = document.getElementById("telePid");
    pidEl.textContent = `${t.pId.toFixed(2)}%`;
    pidEl.className = "tele-v " + (t.pId >= 95 ? "ok" : "warn");

    document.getElementById("dsBeliefBar").style.width = `${Math.round(t.dsBelief * 100)}%`;
    document.getElementById("dsBeliefVal").textContent = t.dsBelief.toFixed(2);
    document.getElementById("dsUncertBar").style.width = `${Math.round(t.dsUncert * 100)}%`;
    document.getElementById("dsUncertVal").textContent = t.dsUncert.toFixed(2);
    document.getElementById("dsConflictBar").style.width = `${Math.round(t.dsConflict * 100)}%`;
    document.getElementById("dsConflictVal").textContent = t.dsConflict.toFixed(2);
  }

  function pushAlert(type, label, score) {
    const hash = Math.abs(Math.sin(state.timeS * 73.1 + score * 41.9) * 0xffffff)
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

  function isUnderCanopy(nx, ny) {
    return canopies.some((c) => Math.hypot(nx - c.x, ny - c.y) < c.r * 0.90);
  }

  function stepAgents(dt) {
    const sdt = dt * state.speedMult;
    state.timeS += sdt;

    // Smooth figure-8 / racetrack corridor overflight path
    const orbitAngle = state.timeS * (0.14 + state.mach * 0.45);
    const prevX = state.uavX;
    const prevY = state.uavY;
    state.uavX = 0.50 + 0.36 * Math.cos(orbitAngle);
    state.uavY = 0.22 + 0.10 * Math.sin(orbitAngle * 2.0);
    state.uavHeadingDeg = ((Math.atan2(state.uavY - prevY, state.uavX - prevX) * 180) / Math.PI + 450) % 360;

    // Micro ant crawling slowly across courtyard pavement
    microTarget.x += microTarget.vx * sdt;
    microTarget.y += microTarget.vy * sdt;
    if (microTarget.x < 0.45 || microTarget.x > 0.54) microTarget.vx *= -1;
    if (microTarget.y < 0.46 || microTarget.y > 0.56) microTarget.vy *= -1;

    for (const a of agents) {
      if (state.scenario === "pursuit" && a.id === 5) {
        const tgt = agents[2];
        const dx = tgt.x - a.x;
        const dy = tgt.y - a.y;
        const d = Math.hypot(dx, dy);
        if (d > 0.028) {
          a.x += (dx / d) * sdt * 0.088;
          a.y += (dy / d) * sdt * 0.088;
        } else {
          a.x = 0.20;
          a.y = 0.54;
        }
      } else if (a.id === 4) {
        a.x = 0.73 + 0.015 * Math.cos(state.timeS * 1.4);
        a.y = 0.30 + 0.015 * Math.sin(state.timeS * 1.4);
      } else {
        a.x += a.vx * sdt;
        a.y += a.vy * sdt;
        if (a.x < 0.07 || a.x > 0.93) a.vx *= -1;
        if (a.y < 0.14 || a.y > 0.88) a.vy *= -1;
      }
    }

    if (state.timeS - state.lastAlertSimT > 2.6) {
      state.lastAlertSimT = state.timeS;
      if (state.scenario === "pursuit") {
        pushAlert("PURSUIT_CONVERGENCE", "Track #5 -> #3", 0.91);
      } else if (state.scenario === "ant") {
        pushAlert("MICRO_OPTIC_LOCK", "6mm Ant (8.4x2.8px @ 65m)", 0.96);
      } else {
        pushAlert("PERIMETER_LOITERING", "Track #4 (Restricted)", 0.78);
      }
    }
  }

  function getLockedEntity() {
    if (state.lockedTargetId === "ant-micro") {
      return { kind: "ant", ...microTarget };
    }
    const foundAgent = agents.find((a) => `agent-${a.id}` === state.lockedTargetId);
    if (foundAgent) return { kind: "human", ...foundAgent };
    const foundVeh = vehicles.find((v) => v.id === state.lockedTargetId);
    if (foundVeh) return { kind: "vehicle", ...foundVeh };
    return { kind: "ant", ...microTarget };
  }

  function drawTelephotoPipLoupe(W, H, dpr, t) {
    const pipW = Math.min(275 * dpr, W * 0.31);
    const pipH = Math.min(200 * dpr, H * 0.34);
    const px = W - pipW - 14 * dpr;
    const py = H - pipH - 14 * dpr;

    const locked = getLockedEntity();

    ctx.save();
    // Frame & Backdrop
    ctx.fillStyle = "#0b0e13";
    ctx.fillRect(px, py, pipW, pipH);
    ctx.strokeStyle = "#ff1423";
    ctx.lineWidth = 1.6 * dpr;
    ctx.strokeRect(px, py, pipW, pipH);

    // Clip inner telephoto aperture
    ctx.beginPath();
    ctx.rect(px + 2 * dpr, py + 22 * dpr, pipW - 4 * dpr, pipH - 24 * dpr);
    ctx.clip();

    const cx = px + pipW * 0.5;
    const cy = py + pipH * 0.55;

    // Pavement / micro texture inside 220 mm telephoto FOV
    ctx.fillStyle = state.sensorMode === "lwir" ? "#161b24" : state.scenario === "night" ? "#11151c" : "#3a3f47";
    ctx.fillRect(px, py, pipW, pipH);

    // Pixel Grid Overlay representing 0.713 mm/px sensor sampling lattice
    ctx.strokeStyle = "rgba(139, 149, 158, 0.16)";
    ctx.lineWidth = 0.7 * dpr;
    const cell = 11 * dpr;
    for (let gx = px; gx < px + pipW; gx += cell) {
      ctx.beginPath(); ctx.moveTo(gx, py); ctx.lineTo(gx, py + pipH); ctx.stroke();
    }
    for (let gy = py; gy < py + pipH; gy += cell) {
      ctx.beginPath(); ctx.moveTo(px, gy); ctx.lineTo(px + pipW, gy); ctx.stroke();
    }

    // Apply smear blur when FMC is disabled
    const smear = state.gimbalActive ? 0 : Math.min(26, t.teleSmearPx * 1.4) * dpr;
    if (smear > 0.5) {
      ctx.translate(Math.sin(state.timeS * 55) * smear * 0.45, 0);
    }

    if (locked.kind === "ant") {
      // Render magnified 6 mm ant across ~8.4 x 2.8 px lattice!
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(Math.atan2(microTarget.vy, microTarget.vx));
      const scale = Math.max(0.55, Math.min(1.8, 0.713 / Math.max(0.25, t.gsdTeleMm))) * dpr;
      ctx.fillStyle = state.sensorMode === "lwir" ? "#ff9f43" : "#121316";
      // 3-segmented ant thorax/abdomen/head + 6 articulated legs
      ctx.beginPath(); ctx.ellipse(-18 * scale, 0, 12 * scale, 7 * scale, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(0, 0, 8 * scale, 5 * scale, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(14 * scale, 0, 6.5 * scale, 5.5 * scale, 0, 0, Math.PI * 2); ctx.fill();

      ctx.strokeStyle = state.sensorMode === "lwir" ? "#ffd28a" : "#181a1f";
      ctx.lineWidth = 1.8 * scale;
      for (const lx of [-6, 0, 7]) {
        ctx.beginPath();
        ctx.moveTo(lx * scale, 0); ctx.lineTo((lx - 4) * scale, -14 * scale);
        ctx.moveTo(lx * scale, 0); ctx.lineTo((lx - 4) * scale, 14 * scale);
        ctx.stroke();
      }
      // Antennae
      ctx.beginPath();
      ctx.moveTo(19 * scale, -2 * scale); ctx.lineTo(28 * scale, -8 * scale);
      ctx.moveTo(19 * scale, 2 * scale); ctx.lineTo(28 * scale, 8 * scale);
      ctx.stroke();

      // Highlight resolved 8.4 x 2.8 px bounding box
      ctx.strokeStyle = "#ff1423";
      ctx.lineWidth = 1.4 * dpr;
      ctx.strokeRect(-33 * scale, -17 * scale, 66 * scale, 34 * scale);
      ctx.restore();
    } else if (locked.kind === "human") {
      // Magnified thermal + optical human pose lock
      const grad = ctx.createRadialGradient(cx, cy, 4, cx, cy, 48 * dpr);
      grad.addColorStop(0, "rgba(255, 224, 165, 0.92)");
      grad.addColorStop(0.5, "rgba(255, 20, 35, 0.72)");
      grad.addColorStop(1, "rgba(117, 0, 20, 0)");
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(cx, cy, 48 * dpr, 0, Math.PI * 2); ctx.fill();

      // Head + shoulders + distress/normal arms
      ctx.fillStyle = "#f2f4f7";
      ctx.beginPath(); ctx.ellipse(cx, cy - 12 * dpr, 11 * dpr, 11 * dpr, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(cx, cy + 12 * dpr, 22 * dpr, 12 * dpr, 0, 0, Math.PI * 2); ctx.fill();

      // Pose skeleton overlay
      ctx.strokeStyle = "#00e5ff";
      ctx.lineWidth = 1.6 * dpr;
      ctx.beginPath();
      ctx.moveTo(cx - 22 * dpr, cy + 10 * dpr);
      ctx.lineTo(cx, cy + 6 * dpr);
      ctx.lineTo(cx + 22 * dpr, cy + 10 * dpr);
      if (locked.status === "distress" || state.scenario === "pursuit") {
        ctx.moveTo(cx - 20 * dpr, cy + 8 * dpr); ctx.lineTo(cx - 32 * dpr, cy - 22 * dpr);
        ctx.moveTo(cx + 20 * dpr, cy + 8 * dpr); ctx.lineTo(cx + 32 * dpr, cy - 22 * dpr);
      }
      ctx.stroke();
    } else {
      // Vehicle hood thermal rejection view
      ctx.fillStyle = "#5c6470";
      ctx.fillRect(cx - 55 * dpr, cy - 28 * dpr, 110 * dpr, 56 * dpr);
      ctx.strokeStyle = "#8b959e";
      ctx.lineWidth = 1.5 * dpr;
      ctx.strokeRect(cx - 55 * dpr, cy - 28 * dpr, 110 * dpr, 56 * dpr);
      ctx.fillStyle = "rgba(255, 20, 35, 0.55)";
      ctx.fillRect(cx - 52 * dpr, cy - 24 * dpr, 44 * dpr, 48 * dpr);
    }

    // Crosshair reticle inside PiP
    ctx.strokeStyle = "rgba(255, 20, 35, 0.7)";
    ctx.lineWidth = 1 * dpr;
    ctx.beginPath();
    ctx.moveTo(cx - 18 * dpr, cy); ctx.lineTo(cx - 5 * dpr, cy);
    ctx.moveTo(cx + 5 * dpr, cy); ctx.lineTo(cx + 18 * dpr, cy);
    ctx.moveTo(cx, cy - 18 * dpr); ctx.lineTo(cx, cy - 5 * dpr);
    ctx.moveTo(cx, cy + 5 * dpr); ctx.lineTo(cx, cy + 18 * dpr);
    ctx.stroke();

    ctx.restore();

    // PiP Header Bar
    ctx.save();
    ctx.fillStyle = "#750014";
    ctx.fillRect(px, py, pipW, 22 * dpr);
    ctx.fillStyle = "#ffffff";
    ctx.font = `700 ${9.5 * dpr}px monospace`;
    const title =
      locked.kind === "ant"
        ? `220mm LOCK: 6mm ANT (${t.antLenPx.toFixed(1)}×${t.antWidPx.toFixed(1)} px)`
        : locked.kind === "human"
        ? `220mm LOCK: HUMAN #${locked.id} (${locked.tempK.toFixed(1)}K)`
        : `220mm LOCK: VEHICLE (DS VETO)`;
    ctx.fillText(title, px + 7 * dpr, py + 14 * dpr);

    ctx.fillStyle = "rgba(11, 14, 19, 0.85)";
    ctx.fillRect(px + 2 * dpr, py + pipH - 19 * dpr, pipW - 4 * dpr, 17 * dpr);
    ctx.fillStyle = t.teleSmearPx <= 0.5 && state.gimbalActive ? "#6ee7b7" : "#ff6b78";
    ctx.font = `600 ${8.8 * dpr}px monospace`;
    ctx.fillText(
      `GSD=${t.gsdTeleMm.toFixed(2)}mm/px | Smear=${t.teleSmearPx.toFixed(3)}px | H=${state.altitudeM}m`,
      px + 7 * dpr,
      py + pipH - 7 * dpr
    );
    ctx.restore();
  }

  function drawScene(t) {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const W = Math.max(640, Math.floor(rect.width * dpr));
    const H = Math.max(380, Math.floor(rect.height * dpr));
    if (canvas.width !== W || canvas.height !== H) {
      canvas.width = W;
      canvas.height = H;
    }

    ctx.save();
    // Base backdrop by modality
    if (state.sensorMode === "lwir") {
      ctx.fillStyle = "#12151c";
    } else if (state.scenario === "night") {
      ctx.fillStyle = state.sensorMode === "rgb" ? "#080a0f" : "#121721";
    } else {
      ctx.fillStyle = "#242931";
    }
    ctx.fillRect(0, 0, W, H);

    // Motion blur jitter when FMC is off
    const blurOffset = state.gimbalActive ? 0 : Math.min(20, t.wideSmearPx * 2.4) * dpr;
    if (blurOffset > 0.5) {
      ctx.translate(Math.sin(state.timeS * 48) * blurOffset * 0.35, 0);
    }

    // Roadway along bottom & pedestrian plaza courtyard
    ctx.fillStyle = state.sensorMode === "lwir" ? "#191e27" : state.scenario === "night" && state.sensorMode === "rgb" ? "#0e1118" : "#2f353f";
    ctx.fillRect(0, 0.72 * H, W, 0.19 * H);
    // Dashed road markings
    ctx.strokeStyle = state.sensorMode === "lwir" ? "#2d3440" : "rgba(214, 219, 224, 0.35)";
    ctx.setLineDash([16 * dpr, 14 * dpr]);
    ctx.lineWidth = 1.5 * dpr;
    ctx.beginPath(); ctx.moveTo(0, 0.815 * H); ctx.lineTo(W, 0.815 * H); ctx.stroke();
    ctx.setLineDash([]);

    // Campus courtyard walkway
    ctx.fillStyle = state.sensorMode === "lwir" ? "#1c212b" : state.scenario === "night" && state.sensorMode === "rgb" ? "#11151e" : "#3a404b";
    ctx.fillRect(0.05 * W, 0.34 * H, 0.90 * W, 0.30 * H);

    // Subtle tactical metric coordinate grid
    ctx.strokeStyle = "rgba(139, 149, 158, 0.08)";
    ctx.lineWidth = 1 * dpr;
    for (let i = 1; i < 10; i++) {
      ctx.beginPath(); ctx.moveTo((i / 10) * W, 0); ctx.lineTo((i / 10) * W, H); ctx.stroke();
    }
    for (let j = 1; j < 6; j++) {
      ctx.beginPath(); ctx.moveTo(0, (j / 6) * H); ctx.lineTo(W, (j / 6) * H); ctx.stroke();
    }

    // 20-Floor Building Rooftop Reference
    ctx.fillStyle = state.sensorMode === "lwir" ? "#181c24" : "#1b1f26";
    ctx.fillRect(0.04 * W, 0.08 * H, 0.17 * W, 0.22 * H);
    ctx.strokeStyle = "#8b959e";
    ctx.lineWidth = 1.3 * dpr;
    ctx.strokeRect(0.04 * W, 0.08 * H, 0.17 * W, 0.22 * H);
    ctx.fillStyle = "#d6dbe0";
    ctx.font = `700 ${10 * dpr}px monospace`;
    ctx.fillText("20-FLOOR ROOFTOP (65m)", 0.05 * W, 0.14 * H);

    // Restricted Perimeter Corridor Zone
    ctx.save();
    ctx.strokeStyle = "#ff1423";
    ctx.setLineDash([7 * dpr, 4 * dpr]);
    ctx.lineWidth = 1.6 * dpr;
    ctx.strokeRect(0.64 * W, 0.13 * H, 0.25 * W, 0.28 * H);
    ctx.fillStyle = "rgba(117, 0, 20, 0.16)";
    ctx.fillRect(0.64 * W, 0.13 * H, 0.25 * W, 0.28 * H);
    ctx.fillStyle = "#ffb8be";
    ctx.font = `700 ${10 * dpr}px monospace`;
    ctx.fillText("RESTRICTED SAFETY ZONE", 0.65 * W, 0.17 * H);
    ctx.restore();

    // Draw Vehicles (warm hoods in LWIR vs DS rejection)
    for (const v of vehicles) {
      const vx = v.x * W;
      const vy = v.y * H;
      const vw = v.w * W;
      const vh = v.h * H;
      if (state.sensorMode === "lwir") {
        const g = ctx.createRadialGradient(vx + vw * 0.25, vy + vh * 0.5, 2, vx + vw * 0.3, vy + vh * 0.5, vw * 0.7);
        g.addColorStop(0, "rgba(255, 20, 35, 0.92)");
        g.addColorStop(0.5, "rgba(117, 0, 20, 0.65)");
        g.addColorStop(1, "rgba(35, 40, 48, 0.2)");
        ctx.fillStyle = g;
        ctx.fillRect(vx, vy, vw, vh);
        ctx.strokeStyle = "#8b959e";
        ctx.strokeRect(vx, vy, vw, vh);
        ctx.fillStyle = "#ff9fa6";
        ctx.font = `${9.5 * dpr}px monospace`;
        ctx.fillText(`LWIR FP: ${v.tempK.toFixed(0)}K`, vx, vy - 5 * dpr);
      } else {
        ctx.fillStyle = state.scenario === "night" && state.sensorMode === "rgb" ? "#131720" : "#555e6b";
        ctx.fillRect(vx, vy, vw, vh);
        ctx.strokeStyle = "#8b959e";
        ctx.strokeRect(vx, vy, vw, vh);
        if (state.sensorMode === "fused" || state.sensorMode === "tele") {
          ctx.fillStyle = "#8b959e";
          ctx.font = `${9 * dpr}px monospace`;
          ctx.fillText("VEHICLE VETO (DS)", vx, vy - 5 * dpr);
        }
      }
    }

    // Floor 6 mm Micro-Target Marker ("Ant @ 20 Floors")
    const mx = microTarget.x * W;
    const my = microTarget.y * H;
    ctx.save();
    ctx.strokeStyle = state.lockedTargetId === "ant-micro" ? "#ff1423" : "#00e5ff";
    ctx.lineWidth = 1.4 * dpr;
    ctx.beginPath();
    ctx.arc(mx, my, 9 * dpr, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(mx - 1.5 * dpr, my - 1.5 * dpr, 3 * dpr, 3 * dpr);
    ctx.fillStyle = "#00e5ff";
    ctx.font = `700 ${9.2 * dpr}px monospace`;
    ctx.fillText("6mm ANT MICRO-TARGET (CLICK)", mx + 12 * dpr, my + 3 * dpr);
    ctx.restore();

    // Draw Human Agents
    for (const a of agents) {
      const ax = a.x * W;
      const ay = a.y * H;
      const occluded = state.scenario === "foliage" && isUnderCanopy(a.x, a.y);
      const nightBlind = state.scenario === "night" && state.sensorMode === "rgb";

      if (state.sensorMode !== "rgb") {
        const tg = ctx.createRadialGradient(ax, ay, 1, ax, ay, 18 * dpr);
        tg.addColorStop(0, "rgba(255, 224, 160, 0.96)");
        tg.addColorStop(0.45, "rgba(255, 20, 35, 0.78)");
        tg.addColorStop(1, "rgba(117, 0, 20, 0)");
        ctx.fillStyle = tg;
        ctx.beginPath(); ctx.arc(ax, ay, 18 * dpr, 0, Math.PI * 2); ctx.fill();
      }

      if (!nightBlind && !(occluded && state.sensorMode === "rgb")) {
        ctx.fillStyle = state.sensorMode === "lwir" ? "#ffe3b3" : "#edf1f5";
        ctx.beginPath(); ctx.arc(ax, ay, 5.5 * dpr, 0, Math.PI * 2); ctx.fill();
      }

      if (blurOffset > 1) {
        ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
        ctx.lineWidth = 5 * dpr;
        ctx.beginPath(); ctx.moveTo(ax - blurOffset, ay); ctx.lineTo(ax + blurOffset, ay); ctx.stroke();
      }
    }

    // Tree Canopy Layer
    for (const c of canopies) {
      const cx = c.x * W;
      const cy = c.y * H;
      const cr = c.r * Math.min(W, H);
      ctx.beginPath();
      ctx.arc(cx, cy, cr, 0, Math.PI * 2);
      if (state.sensorMode === "rgb") {
        ctx.fillStyle = state.scenario === "night" ? "rgba(12, 22, 14, 0.94)" : "rgba(34, 70, 38, 0.89)";
      } else if (state.sensorMode === "lwir") {
        ctx.fillStyle = "rgba(38, 46, 56, 0.28)";
      } else {
        ctx.fillStyle = "rgba(32, 62, 38, 0.42)";
      }
      ctx.fill();
      ctx.strokeStyle = "rgba(139, 149, 158, 0.45)";
      ctx.lineWidth = 1 * dpr;
      ctx.stroke();
    }

    // Detection Boxes & Behavioral Tags
    for (const a of agents) {
      const ax = a.x * W;
      const ay = a.y * H;
      const occluded = state.scenario === "foliage" && isUnderCanopy(a.x, a.y);
      const nightBlind = state.scenario === "night" && state.sensorMode === "rgb";

      const detected =
        state.sensorMode === "fused" || state.sensorMode === "tele"
          ? state.gimbalActive || a.id % 2 === 1
          : state.sensorMode === "lwir"
          ? true
          : !nightBlind && !occluded;

      if (!detected) continue;

      const isAlert =
        (state.scenario === "pursuit" && (a.id === 5 || a.id === 6)) || a.id === 4;
      const isLocked = state.lockedTargetId === `agent-${a.id}`;
      const boxCol = isAlert ? "#ff1423" : isLocked ? "#00e5ff" : "#ffffff";

      const bw = 22 * dpr;
      const bh = 30 * dpr;
      ctx.strokeStyle = boxCol;
      ctx.lineWidth = (isAlert || isLocked ? 2.2 : 1.4) * dpr;
      ctx.strokeRect(ax - bw / 2, ay - bh / 2, bw, bh);

      ctx.fillStyle = isAlert ? "#ff1423" : "#750014";
      ctx.fillRect(ax - bw / 2, ay - bh / 2 - 14 * dpr, 76 * dpr, 13 * dpr);
      ctx.fillStyle = "#ffffff";
      ctx.font = `700 ${9 * dpr}px monospace`;
      const tag = isAlert ? `ALERT #${a.id}` : `ID#${a.id} ${a.tempK.toFixed(0)}K`;
      ctx.fillText(tag, ax - bw / 2 + 3 * dpr, ay - bh / 2 - 4 * dpr);
    }

    // Gimbal Laser Designator Beam from UAV to Locked Target
    const locked = getLockedEntity();
    const ux = state.uavX * W;
    const uy = state.uavY * H;
    const lx = (locked.kind === "vehicle" ? locked.x + locked.w * 0.5 : locked.x) * W;
    const ly = (locked.kind === "vehicle" ? locked.y + locked.h * 0.5 : locked.y) * H;

    ctx.save();
    ctx.strokeStyle = "rgba(255, 20, 35, 0.52)";
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    ctx.lineWidth = 1.3 * dpr;
    ctx.beginPath(); ctx.moveTo(ux, uy); ctx.lineTo(lx, ly); ctx.stroke();
    ctx.restore();

    // Blended-Wing-Body UAV Icon Rotating with Heading
    ctx.save();
    ctx.translate(ux, uy);
    ctx.rotate(((state.uavHeadingDeg - 90) * Math.PI) / 180);
    ctx.fillStyle = "#141619";
    ctx.strokeStyle = "#ff1423";
    ctx.lineWidth = 1.6 * dpr;
    ctx.beginPath();
    ctx.moveTo(14 * dpr, 0);
    ctx.lineTo(-10 * dpr, -16 * dpr);
    ctx.lineTo(-6 * dpr, 0);
    ctx.lineTo(-10 * dpr, 16 * dpr);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    // Top Military-Grade HUD Compass & Telemetry Strip inside Canvas
    ctx.fillStyle = "rgba(12, 15, 20, 0.82)";
    ctx.fillRect(0, 0, W, 28 * dpr);
    ctx.strokeStyle = "#750014";
    ctx.lineWidth = 2 * dpr;
    ctx.beginPath(); ctx.moveTo(0, 28 * dpr); ctx.lineTo(W, 28 * dpr); ctx.stroke();

    ctx.fillStyle = "#ffffff";
    ctx.font = `700 ${10 * dpr}px monospace`;
    ctx.fillText(
      `AEGIS-0.5M  |  HDG ${state.uavHeadingDeg.toFixed(0).padStart(3, "0")}°  |  MACH ${state.mach.toFixed(2)} (${t.v.toFixed(1)} m/s)  |  ALT ${state.altitudeM}m  |  SLANT ${t.slantRangeM.toFixed(1)}m  |  GIMBAL ${t.gimbalRateDeg.toFixed(1)}°/s`,
      12 * dpr,
      18 * dpr
    );

    // Draw Live 220mm Telephoto Loupe PiP
    drawTelephotoPipLoupe(W, H, dpr, t);

    ctx.restore();
  }

  // Click on canvas to lock nearest entity (human, vehicle, or 6 mm courtyard ant!)
  canvas.addEventListener("click", (ev) => {
    const rect = canvas.getBoundingClientRect();
    const nx = (ev.clientX - rect.left) / rect.width;
    const ny = (ev.clientY - rect.top) / rect.height;

    let bestId = "ant-micro";
    let bestD = Math.hypot(nx - microTarget.x, ny - microTarget.y);

    for (const a of agents) {
      const d = Math.hypot(nx - a.x, ny - a.y);
      if (d < bestD) {
        bestD = d;
        bestId = `agent-${a.id}`;
      }
    }
    for (const v of vehicles) {
      const d = Math.hypot(nx - (v.x + v.w * 0.5), ny - (v.y + v.h * 0.5));
      if (d < bestD) {
        bestD = d;
        bestId = v.id;
      }
    }
    state.lockedTargetId = bestId;
  });

  // Controls Wiring
  document.getElementById("machSlider").addEventListener("input", (e) => {
    state.mach = parseFloat(e.target.value);
  });
  document.getElementById("altSlider").addEventListener("input", (e) => {
    state.altitudeM = parseFloat(e.target.value);
  });
  document.getElementById("phiSlider").addEventListener("input", (e) => {
    state.offNadirDeg = parseFloat(e.target.value);
  });

  document.querySelectorAll("[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-mode]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.sensorMode = btn.dataset.mode;
      if (state.sensorMode === "tele") {
        state.lockedTargetId = "ant-micro";
      }
    });
  });

  document.querySelectorAll("[data-scenario]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-scenario]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.scenario = btn.dataset.scenario;
      if (state.scenario === "ant") {
        state.lockedTargetId = "ant-micro";
      } else if (state.scenario === "pursuit") {
        state.lockedTargetId = "agent-5";
      }
    });
  });

  const btnGimbal = document.getElementById("btnGimbal");
  btnGimbal.addEventListener("click", () => {
    state.gimbalActive = !state.gimbalActive;
    btnGimbal.textContent = state.gimbalActive ? "Gimbal FMC: ACTIVE" : "Gimbal FMC: OFF (BLUR)";
    btnGimbal.classList.toggle("active", state.gimbalActive);
    btnGimbal.classList.toggle("btn-alert", !state.gimbalActive);
  });

  const btnPlay = document.getElementById("btnPlay");
  btnPlay.addEventListener("click", () => {
    state.playing = !state.playing;
    btnPlay.textContent = state.playing ? "SIM: LIVE" : "SIM: PAUSED";
    btnPlay.classList.toggle("active", state.playing);
  });

  const btnSpeed = document.getElementById("btnSpeed");
  btnSpeed.addEventListener("click", () => {
    state.speedMult = state.speedMult === 1.0 ? 2.0 : state.speedMult === 2.0 ? 0.5 : 1.0;
    btnSpeed.textContent = `${state.speedMult.toFixed(1)}× Speed`;
  });

  const btnAudio = document.getElementById("btnAudio");
  btnAudio.addEventListener("click", () => {
    state.audioOn = !state.audioOn;
    btnAudio.textContent = state.audioOn ? "Audio Alerts: ON" : "Audio Alerts: OFF";
    btnAudio.classList.toggle("active", state.audioOn);
  });

  document.getElementById("btnPreset").addEventListener("click", () => {
    state.mach = 0.50;
    state.altitudeM = 65.0;
    state.offNadirDeg = 0.0;
    state.gimbalActive = true;
    document.getElementById("machSlider").value = "0.50";
    document.getElementById("altSlider").value = "65";
    document.getElementById("phiSlider").value = "0";
    btnGimbal.textContent = "Gimbal FMC: ACTIVE";
    btnGimbal.classList.add("active");
    btnGimbal.classList.remove("btn-alert");
  });

  const theaterShell = document.getElementById("theaterShell");
  const btnFullscreen = document.getElementById("btnFullscreen");
  btnFullscreen.addEventListener("click", () => {
    const fs = theaterShell.classList.toggle("fullscreen");
    btnFullscreen.textContent = fs ? "Exit Fullscreen" : "Fullscreen Theater";
    btnFullscreen.classList.toggle("active", fs);
  });

  let lastTs = performance.now();
  function loop(now) {
    const dt = Math.min(0.05, (now - lastTs) / 1000.0);
    lastTs = now;
    if (state.playing) {
      stepAgents(dt);
    }
    const t = computeTelemetry();
    updateReadout(t);
    drawScene(t);
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();
