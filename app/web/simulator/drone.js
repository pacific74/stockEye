// 드론(무인멀티콥터) 1종 / 2종 실기시험 시뮬레이터
import * as THREE from 'three';
import { droneItems, wrapDeg } from './courses.js';
import { makeLabel, fmt } from './car.js';

const DEG = Math.PI / 180;
const SPEC = {
  1: { title: '무인멀티콥터 1종 실기 (25kg 초과)', span: 1.9, arms: 6, maxTilt: 22, drag: 0.30, yawRate: 75, climb: 2.5, descend: 2.0, color: 0x2b2f36 },
  2: { title: '무인멀티콥터 2종 실기 (7~25kg)', span: 1.3, arms: 4, maxTilt: 25, drag: 0.38, yawRate: 90, climb: 3.0, descend: 2.3, color: 0x3a3f48 },
};

export class DroneSim {
  constructor(variant, mode, hud) {
    this.kind = 'drone';
    this.cls = variant === '드론1종' ? 1 : 2;
    this.variant = variant === '드론1종' ? '드론1종' : '드론2종';
    this.mode = mode === 'exam' ? 'exam' : 'practice';
    this.hud = hud;
    this.P = SPEC[this.cls];
    const def = droneItems(this.cls);
    this.L = def.layout; this.items = def.items;
    this.input = { thr: 0, yaw: 0, pit: 0, rol: 0 };
    this.camMode = 'pilot';
    this.flightMode = 'ATTI';
    this.windLevel = 1;
    this.windDir = Math.random() * Math.PI * 2;
    this.t = 0;
    this._buildScene();
    this.reset();
  }

  _buildScene() {
    const S = this.scene = new THREE.Scene();
    const L = this.L;
    S.background = skyTexture();
    S.fog = new THREE.Fog(0xcfe6fb, 160, 520);
    this.camera = new THREE.PerspectiveCamera(55, 16 / 9, 0.05, 1200);
    S.add(new THREE.HemisphereLight(0xffffff, 0x5a7a3a, 1.15));
    const sun = new THREE.DirectionalLight(0xffffff, 1.35); sun.position.set(-60, 120, 80); S.add(sun);
    // 바깥 흙/잔디
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(1400, 1400), new THREE.MeshLambertMaterial({ color: 0x7a9a55 }));
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.02; S.add(ground);
    // 시험장 35×80m (줄무늬 잔디)
    const F = L.field;
    const stripes = [[0, 15, 0x8fc56a], [15, 30, 0xa9d488], [30, 72.5, 0x8fc56a], [72.5, 80, 0xa9d488]];
    for (const [z0, z1, c] of stripes) {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(F.w, z1 - z0), new THREE.MeshLambertMaterial({ color: c }));
      m.rotation.x = -Math.PI / 2; m.position.set(0, 0.004, (z0 + z1) / 2); S.add(m);
    }
    const white = new THREE.MeshBasicMaterial({ color: 0xffffff });
    const line = (x0, z0, x1, z1, w = 0.12, mat = white) => { const Lh = Math.hypot(x1 - x0, z1 - z0); const m = new THREE.Mesh(new THREE.PlaneGeometry(Lh, w), mat); m.rotation.set(-Math.PI / 2, 0, -Math.atan2(z1 - z0, x1 - x0)); m.position.set((x0 + x1) / 2, 0.012, (z0 + z1) / 2); S.add(m); };
    line(-F.w / 2, 0, F.w / 2, 0); line(-F.w / 2, F.len, F.w / 2, F.len); line(-F.w / 2, 0, -F.w / 2, F.len); line(F.w / 2, 0, F.w / 2, F.len);
    // 점선 안내선 (P → B·A·D)
    const dash = new THREE.MeshBasicMaterial({ color: 0x5a7d2a });
    for (const x of [L.B.x, 0, L.D.x]) for (let z = 1; z < L.A.z - 0.5; z += 1.2) line(x, z, x, Math.min(z + 0.6, L.A.z), 0.1, dash);
    // 원주비행 원 (지름 15m)
    const ring = new THREE.Mesh(new THREE.RingGeometry(L.R - 0.12, L.R + 0.12, 96), new THREE.MeshBasicMaterial({ color: 0x1b1b1b }));
    ring.rotation.x = -Math.PI / 2; ring.position.set(L.A.x, 0.015, L.A.z); S.add(ring);
    // 조종자 P
    S.add(this._pad(L.P.x, L.P.z + 0.2, 0x2aa7e6, 'P', 1.6, 0xffffff, '#ffffff'));
    const pilot = new THREE.Group();
    const fig = this.pilotFig = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.3, 1.6, 10), new THREE.MeshLambertMaterial({ color: 0x1f2f4a })); fig.position.y = 0.8; pilot.add(fig);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.2, 12, 10), new THREE.MeshLambertMaterial({ color: 0xffffff })); head.position.y = 1.78; pilot.add(head); this.pilotHead = head;
    pilot.position.set(0, 0, -0.6); S.add(pilot);
    // 안전 펜스 (조종자 뒤)
    const fenceM = new THREE.MeshLambertMaterial({ color: 0x2e7d32, transparent: true, opacity: 0.55, side: THREE.DoubleSide });
    const fence = new THREE.Mesh(new THREE.PlaneGeometry(F.w + 10, 1.8), fenceM); fence.position.set(0, 0.9, -3); S.add(fence);
    // 이착륙장 H (파란 H, 2×2m 녹색 매트), 비상착륙장 F
    S.add(this._pad(L.H.x, L.H.z, 0x2e6b3a, 'H', 2, 0xffffff, '#1f3fd1', true));
    S.add(this._pad(L.F.x, L.F.z, 0x2e6b3a, 'F', 2, 0xffffff, '#3f5f1f', true));
    // 호버링 포인트 A~E: 라바콘 + 수술
    this.cones = [];
    for (const k of ['A', 'B', 'C', 'D', 'E']) this.cones.push(this._cone(L[k].x, L[k].z, k));
    // 윈드삭 (주황·흰 줄무늬)
    this.sock = new THREE.Group();
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 6), new THREE.MeshLambertMaterial({ color: 0xdddddd })); pole.position.y = 3; this.sock.add(pole);
    const st = document.createElement('canvas'); st.width = 256; st.height = 16; const sg = st.getContext('2d');
    for (let i = 0; i < 5; i++) { sg.fillStyle = i % 2 ? '#ffffff' : '#ff6a13'; sg.fillRect(i * 256 / 5, 0, 256 / 5, 16); }
    const stTex = new THREE.CanvasTexture(st); stTex.colorSpace = THREE.SRGBColorSpace;
    const sockGeo = new THREE.CylinderGeometry(0.22, 0.42, 2.2, 16, 1, true); sockGeo.rotateX(Math.PI / 2); sockGeo.translate(0, 0, 1.1);
    // 줄무늬가 길이 방향으로 나오도록 UV 회전
    const uv = sockGeo.attributes.uv; for (let i = 0; i < uv.count; i++) { const u = uv.getX(i), v = uv.getY(i); uv.setXY(i, v, u); }
    this.sockCone = new THREE.Mesh(sockGeo, new THREE.MeshLambertMaterial({ map: stTex, side: THREE.DoubleSide }));
    this.sockPivot = new THREE.Group(); this.sockPivot.position.y = 5.8; this.sockPivot.add(this.sockCone); this.sock.add(this.sockPivot);
    this.sock.position.set(F.w / 2 + 3, 0, 6); S.add(this.sock);
    // 체크무늬 현수막
    const ck = document.createElement('canvas'); ck.width = 512; ck.height = 64; const cg = ck.getContext('2d');
    for (let i = 0; i < 32; i++) for (let j = 0; j < 4; j++) { cg.fillStyle = (i + j) % 2 ? '#ffffff' : '#1b2a6b'; cg.fillRect(i * 16, j * 16, 16, 16); }
    const ckTex = new THREE.CanvasTexture(ck); ckTex.colorSpace = THREE.SRGBColorSpace;
    const banner = new THREE.Mesh(new THREE.PlaneGeometry(14, 1.6), new THREE.MeshLambertMaterial({ map: ckTex, side: THREE.DoubleSide }));
    banner.position.set(-F.w / 2 - 4, 0.9, 40); banner.rotation.y = Math.PI / 2; S.add(banner);
    const banner2 = banner.clone(); banner2.position.set(10, 0.9, F.len + 6); banner2.rotation.y = 0; S.add(banner2);
    this._scenery();
    // 목표 표시 (연습모드)
    this.ghost = new THREE.Group();
    const gs = new THREE.Mesh(new THREE.SphereGeometry(0.35, 16, 12), new THREE.MeshBasicMaterial({ color: 0x00ffaa, transparent: true, opacity: 0.6 }));
    this.ghost.add(gs);
    const gr = new THREE.Mesh(new THREE.RingGeometry(0.95, 1.05, 40), new THREE.MeshBasicMaterial({ color: 0x00ffaa, transparent: true, opacity: 0.8, side: THREE.DoubleSide }));
    gr.rotation.x = -Math.PI / 2; this.ghost.add(gr);
    this.ghostLine = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 1), new THREE.MeshBasicMaterial({ color: 0x00ffaa, transparent: true, opacity: 0.4 }));
    S.add(this.ghost); S.add(this.ghostLine);
    // 그림자 표시(고도 감각)
    this.shadow = new THREE.Mesh(new THREE.CircleGeometry(this.P.span * 0.45, 24), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35 }));
    this.shadow.rotation.x = -Math.PI / 2; S.add(this.shadow);
    this.drone = this._buildDrone();
    S.add(this.drone.group);
  }

  // 주변 배경: 산, 아파트 단지, 나무, 구름
  _scenery() {
    const S = this.scene, rnd = mulberry(11);
    // 산 (낮은 언덕들)
    const hillM = [0x3f7a3a, 0x4d8a42, 0x2f6a33].map(c => new THREE.MeshLambertMaterial({ color: c }));
    for (let i = 0; i < 14; i++) {
      const a = -0.9 + (i / 13) * 1.8 + (rnd() - 0.5) * 0.1;
      const r = 300 + rnd() * 120;
      const h = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), hillM[i % 3]);
      h.scale.set(60 + rnd() * 70, 25 + rnd() * 45, 50 + rnd() * 40);
      h.position.set(Math.sin(a) * r, -2, 40 + Math.cos(a) * r); S.add(h);
    }
    // 아파트 단지 (하얀 고층)
    const win = document.createElement('canvas'); win.width = 64; win.height = 128; const wg = win.getContext('2d');
    wg.fillStyle = '#e9ecef'; wg.fillRect(0, 0, 64, 128); wg.fillStyle = '#9fb3c8';
    for (let y = 4; y < 128; y += 8) for (let x = 4; x < 64; x += 12) wg.fillRect(x, y, 7, 4);
    const wTex = new THREE.CanvasTexture(win); wTex.colorSpace = THREE.SRGBColorSpace; wTex.wrapS = wTex.wrapT = THREE.RepeatWrapping;
    for (let i = 0; i < 26; i++) {
      const a = -1.1 + rnd() * 1.0;
      const r = 230 + rnd() * 60;
      const hgt = 30 + rnd() * 35;
      const t = wTex.clone(); t.needsUpdate = true; t.repeat.set(2, hgt / 12);
      const b = new THREE.Mesh(new THREE.BoxGeometry(14, hgt, 10), new THREE.MeshLambertMaterial({ map: t }));
      b.position.set(Math.sin(a) * r, hgt / 2, 40 + Math.cos(a) * r); b.rotation.y = rnd() * 0.5; S.add(b);
    }
    // 나무 (시험장 주변)
    const leaf = [0x2f6b2f, 0x3c7d34, 0x285c2a].map(c => new THREE.MeshLambertMaterial({ color: c }));
    const trunk = new THREE.MeshLambertMaterial({ color: 0x6b4a2b });
    for (let i = 0; i < 90; i++) {
      const g = new THREE.Group();
      const round = rnd() < 0.5;
      const top = round ? new THREE.Mesh(new THREE.SphereGeometry(2 + rnd() * 1.5, 8, 6), leaf[i % 3]) : new THREE.Mesh(new THREE.ConeGeometry(2, 6 + rnd() * 3, 7), leaf[i % 3]);
      top.position.y = round ? 4.5 : 5; g.add(top);
      const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.3, 3), trunk); tr.position.y = 1.5; g.add(tr);
      let x, z;
      const side = i % 3;
      if (side === 0) { x = 30 + rnd() * 40; z = -10 + rnd() * 110; }
      else if (side === 1) { x = -30 - rnd() * 40; z = -10 + rnd() * 110; }
      else { x = -60 + rnd() * 120; z = 95 + rnd() * 40; }
      g.position.set(x, 0, z); g.scale.setScalar(0.8 + rnd() * 0.6); S.add(g);
    }
    // 구름
    const cloudTex = cloudTexture();
    for (let i = 0; i < 18; i++) {
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: cloudTex, transparent: true, opacity: 0.9, depthWrite: false, fog: false }));
      const a = -1.3 + rnd() * 2.6, r = 380 + rnd() * 200;
      sp.position.set(Math.sin(a) * r, 70 + rnd() * 110, 40 + Math.cos(a) * r);
      const w = 90 + rnd() * 120; sp.scale.set(w, w * 0.4, 1); S.add(sp);
    }
  }

  _pad(x, z, color, text, size, lineColor = 0x222222, textColor = null, mat = false) {
    const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
    const hex = (n) => '#' + n.toString(16).padStart(6, '0');
    g.fillStyle = hex(color); g.fillRect(0, 0, 256, 256);
    if (mat) { // 인조잔디 매트 질감 + 흰 테두리
      for (let i = 0; i < 1600; i++) { g.fillStyle = Math.random() < 0.5 ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.08)'; g.fillRect(Math.random() * 256, Math.random() * 256, 2, 2); }
      g.strokeStyle = hex(lineColor); g.lineWidth = 8; g.strokeRect(14, 14, 228, 228);
      g.fillStyle = textColor || '#fff'; g.fillRect(78, 78, 100, 100);
      g.fillStyle = '#ffffff'; g.font = 'bold 90px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, 128, 134);
    } else {
      g.fillStyle = textColor || hex(lineColor); g.font = 'bold 170px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, 128, 136);
    }
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshLambertMaterial({ map: tex }));
    m.rotation.x = -Math.PI / 2; m.rotation.z = Math.PI; m.position.set(x, 0.03, z); return m;
  }

  // 호버링 포인트 라바콘 (꼭대기에 수술 — 드론 바람에 휘날림)
  _cone(x, z, name) {
    const g = new THREE.Group();
    const base = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.04, 0.42), new THREE.MeshLambertMaterial({ color: 0x222222 })); base.position.y = 0.02; g.add(base);
    const c = document.createElement('canvas'); c.width = 64; c.height = 64; const cg = c.getContext('2d');
    cg.fillStyle = '#ff5a14'; cg.fillRect(0, 0, 64, 64); cg.fillStyle = '#ffffff'; cg.fillRect(0, 22, 64, 10); cg.fillRect(0, 40, 64, 7);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.17, 0.7, 20, 1, true), new THREE.MeshLambertMaterial({ map: tex })); cone.position.y = 0.39; g.add(cone);
    // 수술: 가는 띠 여러 개
    const tassel = new THREE.Group(); tassel.position.y = 0.76; g.add(tassel);
    const strips = [];
    const cols = [0xff9ab0, 0xffffff, 0xffc2d1, 0xff7f9a];
    for (let i = 0; i < 22; i++) {
      const piv = new THREE.Group();
      const len = 0.3 + Math.random() * 0.15;
      const sGeo = new THREE.PlaneGeometry(0.035, len); sGeo.translate(0, len / 2, 0);
      const m = new THREE.Mesh(sGeo, new THREE.MeshLambertMaterial({ color: cols[i % 4], side: THREE.DoubleSide }));
      piv.add(m); piv.rotation.y = (i / 22) * Math.PI * 2;
      piv.userData = { ph: Math.random() * 6.28, f: 5 + Math.random() * 6, base: 0.25 + Math.random() * 0.35 };
      tassel.add(piv); strips.push(piv);
    }
    const lb = makeLabel(name, '#ff3b30'); lb.position.y = 2.1; lb.scale.multiplyScalar(0.38); g.add(lb);
    g.position.set(x, 0, z); this.scene.add(g);
    return { x, z, strips, g };
  }

  _buildDrone() {
    const P = this.P; const g = new THREE.Group(); const body = new THREE.Group(); g.add(body);
    const dark = new THREE.MeshLambertMaterial({ color: P.color });
    const core = new THREE.Mesh(new THREE.CylinderGeometry(P.span * 0.16, P.span * 0.18, P.span * 0.12, 16), dark); core.position.y = 0.35; body.add(core);
    if (this.cls === 1) { const tank = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.35, 0.5), new THREE.MeshLambertMaterial({ color: 0xeeeeee })); tank.position.y = 0.12; body.add(tank); }
    const props = [];
    for (let i = 0; i < P.arms; i++) {
      const a = (i + 0.5) / P.arms * Math.PI * 2; // 기수(+z) 기준 대칭 배치
      const r = P.span / 2;
      const ax = Math.sin(a) * r, az = Math.cos(a) * r;
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, r), dark);
      arm.position.set(ax / 2, 0.38, az / 2); arm.rotation.y = a; body.add(arm);
      const front = az > 0;
      const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.09, 10), new THREE.MeshLambertMaterial({ color: front ? 0xd01818 : 0x18a018 }));
      motor.position.set(ax, 0.42, az); body.add(motor);
      const prop = new THREE.Mesh(new THREE.BoxGeometry(P.span * 0.42, 0.01, 0.05), new THREE.MeshLambertMaterial({ color: 0x111111 }));
      prop.position.set(ax, 0.48, az); body.add(prop); props.push(prop);
      const disc = new THREE.Mesh(new THREE.CircleGeometry(P.span * 0.21, 20), new THREE.MeshBasicMaterial({ color: 0x666666, transparent: true, opacity: 0 }));
      disc.rotation.x = -Math.PI / 2; disc.position.set(ax, 0.485, az); body.add(disc); prop.disc = disc;
      // LED (앞 빨강 / 뒤 초록)
      const led = new THREE.Mesh(new THREE.SphereGeometry(0.05, 8, 6), new THREE.MeshBasicMaterial({ color: front ? 0xff2020 : 0x20ff40 }));
      led.position.set(ax, 0.34, az); body.add(led);
    }
    // 기수 표시 화살표
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.08, 0.25, 8), new THREE.MeshBasicMaterial({ color: 0xff3030 }));
    nose.rotation.x = Math.PI / 2; nose.position.set(0, 0.36, P.span * 0.2); body.add(nose);
    // 다리
    for (const sx of [-1, 1]) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.03, P.span * 0.5), dark); leg.position.set(sx * P.span * 0.15, 0.02, 0); body.add(leg);
      const st = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.3, 0.03), dark); st.position.set(sx * P.span * 0.12, 0.17, 0); body.add(st);
    }
    return { group: g, body, props };
  }

  // ---------- 상태 ----------
  reset() {
    this.battery = 100;
    this.ex = { idx: 0, results: this.items.map(() => null), faults: this.items.map(() => []), done: false, time: 0 };
    this._placeFor(this.items[0].start);
    this._beginItem(0);
    this.hud.clearLog(); this.hud.hideResult();
  }

  _placeFor(start) {
    const L = this.L;
    const st = this.st = { pos: new THREE.Vector3(L.H.x, 0, L.H.z), vel: new THREE.Vector3(), yaw: 0, pitch: 0, roll: 0, armed: false, onGround: true, propSpin: 0, crashT: 0, lowThrT: 0 };
    const hover = (p) => { st.pos.set(p.x, L.alt, p.z); st.armed = true; st.onGround = false; };
    if (start === 'hover_H') hover(L.H);
    if (start === 'hover_A') hover(L.A);
    if (start === 'ground_F') st.pos.set(L.F.x, 0, L.F.z);
  }

  _beginItem(i) {
    const E = this.ex; E.idx = i; E.itemT = 0; E.timeFault = false;
    const item = this.items[i];
    let steps = item.steps.map(s => ({ ...s }));
    if (steps[0].kind !== 'arm' && (this.st.onGround || !this.st.armed)) {
      const p = this.st.pos;
      steps = [
        { kind: 'arm', text: '시동을 거세요 (다음 항목 준비)', free: true },
        { kind: 'goto', text: `${this.L.alt}m 까지 이륙하세요 (준비)`, target: [p.x, this.L.alt, p.z], hold: 1.5, free: true },
        ...steps,
      ];
    }
    E.steps = steps; E.si = -1;
    this.hud.log(`▶ ${i + 1}. ${item.name}`, 'info');
    this._nextStep();
  }

  _nextStep() {
    const E = this.ex; E.si++;
    const st = E.steps[E.si];
    if (!st) { this._endItem(); return; }
    st.t = 0; st.holdT = 0; st.arrived = false; st.from = this.st.pos.clone(); st.faults = new Set();
    const item = this.items[E.idx];
    this.hud.instruction(`${E.idx + 1}. ${item.name} — ${st.text}`, st.kind === 'land' && item.emergency ? 'bad' : 'task');
    if (item.emergency && st.kind === 'land') this.event('warn', '비상!');
  }

  _fault(text) {
    const E = this.ex; const st = E.steps[E.si];
    if (st && st.free) return;
    if (st && st.faults.has(text)) return;
    st && st.faults.add(text);
    E.faults[E.idx].push(text);
    this.hud.log(`✗ ${text}`, 'bad'); this.event('penalty', text);
  }

  _endItem() {
    const E = this.ex; const ok = E.faults[E.idx].length === 0;
    E.results[E.idx] = ok ? 'S' : 'U';
    this.hud.log(`${this.items[E.idx].name}: ${ok ? 'S (만족)' : 'U (불만족)'}`, ok ? 'ok' : 'bad');
    if (this.mode === 'exam' && !ok) { this._finish(); return; }
    if (E.idx + 1 < this.items.length) this._beginItem(E.idx + 1);
    else this._finish();
  }

  _finish() {
    const E = this.ex; E.done = true;
    const pass = E.results.every(r => r === 'S');
    const rows = this.items.map((it, i) => `${i + 1}. ${it.name} — <b class="${E.results[i] === 'S' ? 'good' : 'bad'}">${E.results[i] || '-'}</b>${E.faults[i].length ? ` <small>(${E.faults[i].join(', ')})</small>` : ''}`).join('<br>');
    this.hud.showResult(pass ? '합격!' : '불합격', `${rows}<br><br>총 비행시간 ${fmt(E.time)}`, pass);
    this.hud.instruction('실기 종료 — 휴대폰 메뉴에서 다시 시작', pass ? 'go' : 'bad');
    this.event(pass ? 'pass' : 'fail', pass ? '합격' : '불합격');
  }

  // ---------- 입력/명령 ----------
  setInput(d) { Object.assign(this.input, d); this.lastInput = performance.now(); }
  command(c, arg) {
    const s = this.st;
    switch (c) {
      case 'arm':
        if (s.armed) { if (s.onGround) { s.armed = false; this.hud.toast('시동 끔'); } else this.hud.toast('비행 중에는 시동을 끌 수 없습니다 (착륙 후)'); }
        else if (s.onGround) { if (this.input.thr > 0.2) { this.hud.toast('스로틀을 내리고 시동을 거세요'); break; } s.armed = true; this.hud.toast('시동 켜짐 (모터 회전)'); }
        break;
      case 'fmode': this.flightMode = this.flightMode === 'ATTI' ? 'GPS' : 'ATTI'; this.hud.toast(`비행모드: ${this.flightMode === 'ATTI' ? 'ATTI(자세모드·시험모드)' : 'GPS(위치고정)'}`); break;
      case 'wind': this.windLevel = (this.windLevel + 1) % 3; this.hud.toast(`바람: ${['없음', '약함', '강함'][this.windLevel]}`); break;
      case 'camera': this.camMode = { pilot: 'chase', chase: 'top', top: 'pilot' }[this.camMode]; break;
      case 'restart': this.reset(); break;
      case 'jump': this.jump(Number(arg)); break;
    }
  }
  jumpList() { return this.items.map((it, i) => ({ id: String(i), name: `${i + 1}. ${it.name}` })); }
  jump(i) {
    if (this.mode === 'exam') { this.hud.toast('시험 모드에서는 항목 이동을 할 수 없습니다'); return; }
    if (!(i >= 0 && i < this.items.length)) return;
    this.reset();
    const E = this.ex; for (let k = 0; k < i; k++) E.results[k] = null;
    this._placeFor(this.items[i].start);
    this.hud.clearLog();
    this._beginItem(i);
  }

  // ---------- 물리 ----------
  update(dt) {
    this.t += dt;
    if (this.lastInput && performance.now() - this.lastInput > 700) Object.assign(this.input, { thr: 0, yaw: 0, pit: 0, rol: 0 });
    this._physics(dt);
    if (!this.ex.done) this._exam(dt);
    this._visuals(dt);
    this._camera(dt);
  }

  wind() {
    const item = this.items[this.ex.idx];
    let mag = [0, 1.4, 3.0][this.windLevel];
    let dir = this.windDir;
    if (item && item.crosswind && !this.ex.done) { mag = Math.max(mag, 2.2); dir = -Math.PI / 2; } // 측풍: D(오른쪽) → B(왼쪽) 방향으로 붐
    const gust = 1 + 0.35 * Math.sin(this.t * 0.7) + 0.2 * Math.sin(this.t * 2.3 + 1);
    // dir: 바람이 불어오는 방향 (0 = 앞쪽에서 조종자 쪽으로). -90° = 오른쪽(D)에서 왼쪽(B)으로
    return new THREE.Vector3(-Math.sin(dir) * mag * gust, 0, -Math.cos(dir) * mag * gust);
  }

  _physics(dt) {
    const s = this.st, P = this.P, I = this.input;
    if (s.crashT > 0) { s.crashT -= dt; if (s.crashT <= 0) this._afterCrash(); return; }
    const wind = this.wind(); this._windNow = wind;
    const f = new THREE.Vector3(Math.sin(s.yaw), 0, Math.cos(s.yaw));
    const r = new THREE.Vector3(-Math.cos(s.yaw), 0, Math.sin(s.yaw));
    const acc = new THREE.Vector3();
    if (s.armed) {
      s.yaw -= I.yaw * P.yawRate * DEG * dt;
      if (this.flightMode === 'ATTI') {
        const tp = I.pit * P.maxTilt * DEG, tr = I.rol * P.maxTilt * DEG;
        const k = Math.min(1, dt / 0.18);
        s.pitch += (tp - s.pitch) * k; s.roll += (tr - s.roll) * k;
        if (!s.onGround) {
          acc.addScaledVector(f, 9.8 * Math.tan(s.pitch)).addScaledVector(r, 9.8 * Math.tan(s.roll));
          const rel = s.vel.clone().sub(wind); rel.y = 0;
          acc.addScaledVector(rel, -P.drag);
        }
      } else {
        const tv = f.clone().multiplyScalar(I.pit * 5).addScaledVector(r, I.rol * 5);
        const dv = tv.sub(new THREE.Vector3(s.vel.x, 0, s.vel.z));
        if (!s.onGround) acc.addScaledVector(dv, 2.2);
        const local = f.dot(dv), lat = r.dot(dv);
        s.pitch += (Math.atan(local * 0.2) - s.pitch) * Math.min(1, dt * 6);
        s.roll += (Math.atan(lat * 0.2) - s.roll) * Math.min(1, dt * 6);
      }
      // 고도: 스로틀 중앙 = 고도 유지
      const vyT = I.thr >= 0 ? I.thr * P.climb : I.thr * P.descend;
      acc.y = (vyT - s.vel.y) * 3.5;
      if (s.onGround && I.thr > 0.15) { s.onGround = false; }
      if (s.onGround && I.thr < -0.7) { s.lowThrT += dt; if (s.lowThrT > 2 && !this._autoDisarmLock) { /* 스로틀 내린 채 2초 → 모터 정지 */ s.armed = false; this.hud.toast('시동 꺼짐 (스로틀 최저 2초)'); } } else s.lowThrT = 0;
    } else {
      s.pitch *= 0.9; s.roll *= 0.9;
      if (!s.onGround) acc.y = -9.8;
    }
    s.vel.addScaledVector(acc, dt);
    if (s.onGround) { s.vel.x *= 0.7; s.vel.z *= 0.7; if (s.vel.y < 0) s.vel.y = 0; }
    s.pos.addScaledVector(s.vel, dt);
    if (s.pos.y > 0.05) s.onGround = false;
    if (s.pos.y <= 0) {
      const impact = -s.vel.y, hsp = Math.hypot(s.vel.x, s.vel.z);
      s.pos.y = 0;
      if (!s.onGround) {
        this._touch = { impact, hsp };
        if (impact > 3.2 || hsp > 3.0 || Math.abs(s.pitch) > 30 * DEG || Math.abs(s.roll) > 30 * DEG) { this._crash(impact > 3.2 ? '추락 (강한 충돌)' : '착륙 중 전복'); return; }
      }
      s.onGround = true; s.vel.y = 0;
    }
    if (s.pos.y > 60 || Math.hypot(s.pos.x, s.pos.z - 20) > 90) { this._crash('비행구역 이탈'); }
    s.propSpin += (s.armed ? 60 : 0) * dt;
    if (s.armed) this.battery = Math.max(5, this.battery - dt * (s.onGround ? 0.02 : 0.12));
  }

  _crash(why) {
    const s = this.st; if (s.crashT > 0) return;
    s.crashT = 2.0; s.armed = false;
    this.hud.log(`💥 ${why}`, 'fail'); this.event('fail', why);
    this.hud.instruction(`💥 ${why}`, 'bad');
    const E = this.ex; if (!E.done) E.faults[E.idx].push(why);
  }
  _afterCrash() {
    const E = this.ex;
    if (this.mode === 'exam') { E.results[E.idx] = 'U'; this._finish(); return; }
    // 연습: 현재 항목 다시
    const i = E.idx; E.faults[i] = [];
    this._placeFor(this.items[i].start); this._beginItem(i);
  }

  // ---------- 채점 ----------
  _exam(dt) {
    const E = this.ex, s = this.st; if (this.st.crashT > 0) return;
    E.time += dt; E.itemT += dt;
    const item = this.items[E.idx]; const st = E.steps[E.si]; if (!st) return;
    st.t += dt;
    if (E.itemT > item.limit && !E.timeFault) { E.timeFault = true; if (!st.free) this._fault(`제한시간(${item.limit}초) 초과`); }
    const yawDeg = wrapDeg(s.yaw / DEG); // 기수 방향(도), 0=정면, +90=왼쪽
    this._dev = null;
    if (st.kind === 'arm') { if (s.armed) this._nextStep(); return; }
    if (st.kind === 'goto' || st.kind === 'yaw') {
      const T = new THREE.Vector3(...st.target);
      const dh = Math.hypot(s.pos.x - T.x, s.pos.z - T.z), dv = Math.abs(s.pos.y - T.y);
      const tol = st.tol || 1.0, vtol = st.vtol || 0.8;
      this._dev = { dh, dv, tol };
      let wantHd = st.heading;
    if (st.circle && st.heading != null) { // 원의 접선 방향 (H → D → C → B → H)
      const rx = s.pos.x - st.circle.cx, rz = s.pos.z - st.circle.cz;
      wantHd = wrapDeg(Math.atan2(rz, -rx) / DEG);
    }
    st.wantHd = wantHd;
    const hdErr = wantHd == null ? 0 : Math.abs(wrapDeg(yawDeg - wantHd));
      if (st.kind === 'yaw') {
        if (st.t > 2.5 && (dh > 1.6 || dv > 1.3)) this._fault('기수 회전 중 위치 이탈');
        if (hdErr < 8) { st.holdT += dt; if (st.holdT >= st.hold) this._nextStep(); } else st.holdT = 0;
        return;
      }
      // 이동 중 경로 이탈
      if (!st.arrived) {
        if (st.circle) {
          const rr = Math.hypot(s.pos.x - st.circle.cx, s.pos.z - st.circle.cz);
          if (Math.abs(rr - st.circle.R) > 2.2) this._fault('원주 경로 이탈');
          if (dv > 1.5) this._fault('원주비행 고도 유지 불량');
        } else if (st.from) {
          const d = segDist(s.pos, st.from, T);
          if (d.h > (st.pathTol || 2.2)) this._fault(st.pathTol ? `비행 경로 이탈(좌우 ${st.pathTol}m 초과)` : '비행 경로 이탈(수평)');
          if (d.v > (st.vPathTol || 1.6)) this._fault(st.vPathTol ? `고도 편차 ${st.vPathTol}m 초과` : '비행 경로 이탈(고도)');
        }
        if ((st.circle || st.strictHead) && wantHd != null && st.t > 2 && hdErr > (st.headTol || 30)) this._fault('기수 방향 유지 불량');
        if (dh <= tol && dv <= vtol) { st.arrived = true; st.holdT = 0; if (!st.hold) { this._nextStep(); return; } }
      } else {
        st.holdT += dt;
        if (dh > tol * 1.6 || dv > vtol * 1.6) this._fault('정지비행 위치 이탈');
        if (st.heading != null && hdErr > 20) this._fault('정지비행 기수 방향 불량');
        if (st.holdT >= st.hold) this._nextStep();
      }
      return;
    }
    if (st.kind === 'land') {
      const dh = Math.hypot(s.pos.x - st.pad[0], s.pos.z - st.pad[1]);
      this._dev = { dh, dv: s.pos.y, tol: st.radius, land: true };
      if (st.timeLimit && st.t > st.timeLimit) this._fault(`착륙 제한시간(${st.timeLimit}초) 초과`);
      if (s.onGround && Math.hypot(s.vel.x, s.vel.z) < 0.3) {
        st.groundT = (st.groundT || 0) + dt;
        if (st.groundT > 0.8) {
          if (this._touch && this._touch.impact > 1.6) this._fault('강한 착지(하강 속도 과다)');
          if (dh > st.radius) this._fault(`착륙 위치 이탈 (중심에서 ${dh.toFixed(1)}m)`);
          else this.hud.log(`착륙 ✓ 중심에서 ${dh.toFixed(2)}m`, 'ok');
          s.armed = false; this.hud.toast('착륙 완료 — 시동 꺼짐');
          this._nextStep();
        }
      } else st.groundT = 0;
    }
  }

  // ---------- 그래픽 ----------
  _visuals(dt) {
    const s = this.st, D = this.drone;
    D.group.position.copy(s.pos);
    D.group.rotation.set(0, s.yaw, 0);
    D.body.rotation.set(s.pitch, 0, s.roll, 'YXZ');
    D.props.forEach((p, i) => { p.rotation.y = s.propSpin * (i % 2 ? 1 : -1); p.disc.material.opacity = s.armed ? 0.25 : 0; });
    this.shadow.position.set(s.pos.x, 0.03, s.pos.z);
    this.shadow.material.opacity = Math.max(0.08, 0.4 - s.pos.y * 0.03);
    // 목표 표시
    const st = this.ex.steps && this.ex.steps[this.ex.si];
    const showGhost = !this.ex.done && st && (st.target || st.pad) && (this.mode === 'practice' || st.free);
    this.ghost.visible = this.ghostLine.visible = !!showGhost;
    if (showGhost) {
      const T = st.target ? new THREE.Vector3(...st.target) : new THREE.Vector3(st.pad[0], 0.1, st.pad[1]);
      this.ghost.position.copy(T);
      this.ghostLine.position.set(T.x, T.y / 2, T.z); this.ghostLine.scale.y = Math.max(0.01, T.y);
      this.ghost.children[1].scale.setScalar(st.tol || st.radius || 1);
    }
    const w = this._windNow || new THREE.Vector3();
    const wm = Math.hypot(w.x, w.z);
    this.sockPivot.rotation.y = Math.atan2(w.x, w.z);
    this.sockCone.rotation.x = Math.max(0, 1.25 - wm * 0.38) + Math.sin(this.t * 3.1) * 0.04;
    // 라바콘 수술: 바람 + 드론 하강풍(가까울수록 세게)
    const t = this.t;
    for (const c of this.cones) {
      const dx = c.x - s.pos.x, dz = c.z - s.pos.z, dh = Math.hypot(dx, dz);
      const down = s.armed && !s.onGround ? Math.max(0, 1 - dh / (this.P.span * 2.2)) * Math.max(0, 1 - s.pos.y / 9) : 0;
      const dirW = Math.atan2(w.x, w.z), dirD = Math.atan2(dx, dz);
      const strength = Math.min(1.4, wm * 0.12 + down * 1.6);
      c.flutter = down;
      for (const p of c.strips) {
        const u = p.userData;
        const amp = 0.06 + strength * 0.9;
        const lean = Math.min(1.35, u.base * 0.4 + strength);
        // 띠 바깥쪽으로 퍼짐 + 펄럭임
        p.children[0].rotation.x = -(lean + Math.sin(t * u.f * (1 + strength) + u.ph) * amp);
        void dirW; void dirD;
      }
    }
  }

  _camera(dt) {
    const s = this.st, cam = this.camera; cam.up.set(0, 1, 0);
    this.pilotFig.visible = this.pilotHead.visible = this.camMode !== 'pilot';
    if (this.camMode === 'pilot') {
      cam.position.set(0, 1.7, -1.0);
      const look = this._look || (this._look = s.pos.clone());
      look.lerp(new THREE.Vector3(s.pos.x, s.pos.y + 0.3, s.pos.z), Math.min(1, dt * 4));
      const dist = cam.position.distanceTo(look);
      cam.fov = Math.max(11, Math.min(60, 2 * Math.atan(7 / dist) / DEG));
      cam.lookAt(look);
    } else if (this.camMode === 'chase') {
      const f = new THREE.Vector3(Math.sin(s.yaw), 0, Math.cos(s.yaw));
      const want = s.pos.clone().addScaledVector(f, -6).add(new THREE.Vector3(0, 2.5, 0));
      if (want.y < 0.5) want.y = 0.5;
      if (!this._cp) this._cp = want.clone();
      this._cp.lerp(want, Math.min(1, dt * 3)); cam.position.copy(this._cp); cam.fov = 60;
      cam.lookAt(s.pos.x + f.x * 3, s.pos.y, s.pos.z + f.z * 3);
      return cam.updateProjectionMatrix();
    } else {
      cam.position.set(0, 95, 38); cam.up.set(0, 0, 1); cam.fov = 50;
      cam.lookAt(0, 0, 38);
    }
    this._cp = null;
    cam.updateProjectionMatrix();
  }

  // ---------- HUD ----------
  hudPanel() {
    const s = this.st; const hd = ((wrapDeg(s.yaw / DEG)) + 360) % 360;
    const w = this._windNow || { x: 0, z: 0 }; const wm = Math.hypot(w.x, w.z);
    const dev = this._dev;
    const dtxt = dev ? (dev.land ? `패드 중심까지 <b>${dev.dh.toFixed(1)}m</b> (허용 ${dev.tol}m)` : `목표 오차 수평 <b class="${dev.dh <= dev.tol ? 'good' : 'bad'}">${dev.dh.toFixed(1)}m</b> · 고도 <b class="${dev.dv <= 0.8 ? 'good' : 'bad'}">${dev.dv.toFixed(1)}m</b>`) : '';
    return `
      <div class="speed">${s.pos.y.toFixed(1)}<small>m 고도</small></div>
      <div class="gear">${this.flightMode}<small>${s.armed ? '모터 ON' : '모터 OFF'}</small></div>
      <div class="inds"><span class="ind on">기수 ${hd.toFixed(0)}°</span><span class="ind">속도 ${Math.hypot(s.vel.x, s.vel.z).toFixed(1)}m/s</span><span class="ind ${wm > 2 ? 'amber' : ''}">바람 ${wm.toFixed(1)}m/s</span></div>
      <div class="pedals">${dtxt}</div>`;
  }
  hudTop() {
    const E = this.ex;
    const list = this.items.map((it, i) => `<span class="chip ${E.results[i] === 'S' ? 'good' : E.results[i] === 'U' ? 'bad' : i === E.idx && !E.done ? 'cur' : ''}">${i + 1}</span>`).join('');
    return `<b>${this.P.title}</b> · ${this.mode === 'exam' ? '시험모드' : '연습모드'}<br>${list} · 비행 ${fmt(E.time)}`;
  }
  drawMinimap(ctx, w, h) { drawDroneMap(ctx, w, h, this.L, { x: this.st.pos.x, z: this.st.pos.z, hd: this.st.yaw / DEG }); }
  phoneState() {
    const s = this.st, E = this.ex;
    const w = this._windNow || { x: 0, z: 0 };
    const stp = E.steps && E.steps[E.si];
    const tgt = !E.done && stp ? (stp.target ? [stp.target[0], stp.target[2]] : stp.pad ? [stp.pad[0], stp.pad[1]] : null) : null;
    const dev = this._dev ? { dh: +this._dev.dh.toFixed(2), dv: +this._dev.dv.toFixed(2), tol: this._dev.tol, land: !!this._dev.land } : null;
    return {
      kind: 'drone', variant: this.variant, mode: this.mode, alt: +s.pos.y.toFixed(1), armed: s.armed, fmode: this.flightMode, wind: this.windLevel, cam: this.camMode,
      item: E.done ? '실기 종료' : `${E.idx + 1}. ${this.items[E.idx].name}`, instr: this.hud.currentInstr,
      x: +s.pos.x.toFixed(2), z: +s.pos.z.toFixed(2), hd: +(((wrapDeg(s.yaw / DEG)) + 360) % 360).toFixed(0),
      hs: +Math.hypot(s.vel.x, s.vel.z).toFixed(1), vs: +s.vel.y.toFixed(1), dist: +Math.hypot(s.pos.x, s.pos.z).toFixed(1),
      ws: +Math.hypot(w.x, w.z).toFixed(1), bat: +this.battery.toFixed(0), results: E.results, idx: E.done ? -1 : E.idx, dev, tgt,
    };
  }
  event(kind, text) { this.onEvent && this.onEvent(kind, text); }
}

function segDist(p, a, b) {
  const ab = b.clone().sub(a); const L2 = ab.lengthSq() || 1e-9;
  let t = p.clone().sub(a).dot(ab) / L2; t = Math.max(0, Math.min(1, t));
  const q = a.clone().addScaledVector(ab, t);
  return { h: Math.hypot(p.x - q.x, p.z - q.z), v: Math.abs(p.y - q.y) };
}

// 위에서 본 시험장 지도 (TV 미니맵·휴대폰 액정 공용 로직은 phone.js 에 동일)
function drawDroneMap(ctx, w, h, L, me) {
  const F = L.field; const sc = Math.min((w - 12) / F.w, (h - 12) / F.len);
  const X = x => w / 2 - x * sc, Y = z => h / 2 + (F.len / 2 - z) * sc;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(110,170,80,.35)'; ctx.fillRect(X(F.w / 2), Y(F.len), F.w * sc, F.len * sc);
  ctx.strokeStyle = 'rgba(255,255,255,.6)'; ctx.lineWidth = 1; ctx.strokeRect(X(F.w / 2), Y(F.len), F.w * sc, F.len * sc);
  ctx.beginPath(); ctx.arc(X(L.A.x), Y(L.A.z), L.R * sc, 0, 7); ctx.stroke();
  const pt = (p, c, t, sq) => { ctx.fillStyle = c; if (sq) ctx.fillRect(X(p.x) - 4, Y(p.z) - 4, 8, 8); else { ctx.beginPath(); ctx.moveTo(X(p.x), Y(p.z) - 5); ctx.lineTo(X(p.x) + 4, Y(p.z) + 3); ctx.lineTo(X(p.x) - 4, Y(p.z) + 3); ctx.fill(); } ctx.fillStyle = '#fff'; ctx.font = '11px sans-serif'; ctx.fillText(t, X(p.x) + 6, Y(p.z) + 4); };
  pt(L.P, '#2aa7e6', 'P', 1); pt(L.H, '#1f3fd1', 'H', 1); pt(L.F, '#3f5f1f', 'F', 1);
  for (const k of ['A', 'B', 'C', 'D', 'E']) pt(L[k], '#ff3b30', k);
  ctx.save(); ctx.translate(X(me.x), Y(me.z)); ctx.rotate(-me.hd * Math.PI / 180);
  ctx.fillStyle = '#ffd60a'; ctx.beginPath(); ctx.moveTo(0, -8); ctx.lineTo(6, 6); ctx.lineTo(0, 3); ctx.lineTo(-6, 6); ctx.closePath(); ctx.fill(); ctx.restore();
}
function skyTexture() {
  const c = document.createElement('canvas'); c.width = 4; c.height = 256; const g = c.getContext('2d');
  const gr = g.createLinearGradient(0, 0, 0, 256); gr.addColorStop(0, '#2f7fe0'); gr.addColorStop(0.55, '#7db8f0'); gr.addColorStop(1, '#d7ecfb');
  g.fillStyle = gr; g.fillRect(0, 0, 4, 256);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
function cloudTexture() {
  const c = document.createElement('canvas'); c.width = 256; c.height = 128; const g = c.getContext('2d');
  const blob = (x, y, r) => { const gr = g.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, 'rgba(255,255,255,.95)'); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill(); };
  [[70, 75, 45], [120, 60, 55], [175, 75, 45], [100, 85, 40], [150, 88, 40], [210, 85, 30], [40, 88, 28]].forEach(b => blob(...b));
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
function mulberry(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
