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
    S.background = new THREE.Color(0xa9d3f5);
    S.fog = new THREE.Fog(0xa9d3f5, 90, 320);
    this.camera = new THREE.PerspectiveCamera(55, 16 / 9, 0.05, 800);
    S.add(new THREE.HemisphereLight(0xffffff, 0x5a7a3a, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.3); sun.position.set(-40, 80, 60); S.add(sun);
    const grass = new THREE.Mesh(new THREE.PlaneGeometry(800, 800), new THREE.MeshLambertMaterial({ color: 0x6aa04a }));
    grass.rotation.x = -Math.PI / 2; S.add(grass);
    // 비행장 잔디 구획선
    const L = this.L;
    const field = new THREE.Mesh(new THREE.PlaneGeometry(L.D * 2 + 24, L.C.z + 26), new THREE.MeshLambertMaterial({ color: 0x7cb85a }));
    field.rotation.x = -Math.PI / 2; field.position.set(0, 0.005, (L.C.z + 26) / 2 - 4); S.add(field);
    // 조종자 위치
    const pilot = new THREE.Group();
    const box = new THREE.Mesh(new THREE.BoxGeometry(2, 0.05, 2), new THREE.MeshLambertMaterial({ color: 0xdddddd })); box.position.y = 0.03; pilot.add(box);
    const fig = this.pilotFig = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.3, 1.6, 10), new THREE.MeshLambertMaterial({ color: 0x1f4e9a })); fig.position.y = 0.8; pilot.add(fig);
    S.add(pilot);
    const pl = makeLabel('조종자', '#fff'); pl.position.set(0, 2.6, -0.5); pl.scale.multiplyScalar(0.7); S.add(pl);
    // 이착륙장 H
    S.add(this._pad(L.H.x, L.H.z, 0xf5f5f5, 'H', L.padR * 2 + 0.6));
    // 비상착륙장
    S.add(this._pad(L.EM.x, L.EM.z, 0xffe4e4, '비상', 3.4, 0xd02020));
    // 기준점 깃발: E(중앙) A(왼) B(오른)
    for (const [p, n, c] of [[L.C, 'E', '#ffd84a'], [L.A, 'A', '#8fd3ff'], [L.B, 'B', '#ffb0b0']]) {
      S.add(this._flag(p.x, p.z, n, c));
    }
    // 원주비행 원 표시
    const ring = new THREE.Mesh(new THREE.RingGeometry(L.circleR - 0.08, L.circleR + 0.08, 64), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35 }));
    ring.rotation.x = -Math.PI / 2; ring.position.set(0, 0.02, L.C.z + L.circleR); S.add(ring);
    // 기준선
    const line = (x0, z0, x1, z1) => { const L2 = Math.hypot(x1 - x0, z1 - z0); const m = new THREE.Mesh(new THREE.PlaneGeometry(L2, 0.1), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.5 })); m.rotation.set(-Math.PI / 2, 0, -Math.atan2(z1 - z0, x1 - x0)); m.position.set((x0 + x1) / 2, 0.02, (z0 + z1) / 2); S.add(m); };
    line(L.A.x, L.A.z, L.B.x, L.B.z); line(0, 0, 0, L.C.z);
    // 풍향 깃발(윈드삭)
    this.sock = new THREE.Group();
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 4), new THREE.MeshLambertMaterial({ color: 0xcccccc })); pole.position.y = 2; this.sock.add(pole);
    this.sockCone = new THREE.Mesh(new THREE.ConeGeometry(0.35, 1.6, 12, 1, true), new THREE.MeshLambertMaterial({ color: 0xff6a00, side: THREE.DoubleSide }));
    this.sockCone.rotation.x = -Math.PI / 2; this.sockCone.position.set(0, 3.8, 0.8);
    this.sockPivot = new THREE.Group(); this.sockPivot.add(this.sockCone); this.sock.add(this.sockPivot);
    this.sock.position.set(-L.D - 5, 0, 8); S.add(this.sock);
    // 주변 나무
    const tm = new THREE.MeshLambertMaterial({ color: 0x2f6b2f });
    for (let i = 0; i < 50; i++) {
      const a = (i / 50) * Math.PI * 2; const r = 70 + (i * 37 % 30);
      const t = new THREE.Mesh(new THREE.ConeGeometry(2.2, 7, 7), tm); t.position.set(Math.cos(a) * r, 3.5, 20 + Math.sin(a) * r); S.add(t);
    }
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

  _pad(x, z, color, text, size, lineColor = 0x222222) {
    const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
    g.fillStyle = '#' + color.toString(16).padStart(6, '0'); g.fillRect(0, 0, 256, 256);
    g.strokeStyle = '#' + lineColor.toString(16).padStart(6, '0'); g.lineWidth = 14; g.strokeRect(7, 7, 242, 242);
    g.fillStyle = g.strokeStyle; g.font = `bold ${text.length > 1 ? 80 : 170}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, 128, 136);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshLambertMaterial({ map: tex }));
    m.rotation.x = -Math.PI / 2; m.rotation.z = Math.PI; m.position.set(x, 0.03, z); return m;
  }
  _flag(x, z, name, color) {
    const g = new THREE.Group();
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 2), new THREE.MeshLambertMaterial({ color: 0xffffff })); pole.position.y = 1; g.add(pole);
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.4, 0.7, 12), new THREE.MeshLambertMaterial({ color: new THREE.Color(color) })); cone.position.y = 0.35; g.add(cone);
    const lb = makeLabel(name, color); lb.position.y = 2.6; lb.scale.multiplyScalar(0.8); g.add(lb);
    g.position.set(x, 0, z); return g;
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
    if (start === 'hover_H') { st.pos.set(L.H.x, L.alt, L.H.z); st.armed = true; st.onGround = false; }
    if (start === 'hover_C') { st.pos.set(L.C.x, L.alt, L.C.z); st.armed = true; st.onGround = false; }
    if (start === 'hover_side') { st.pos.set(L.H.x, L.alt, L.H.z); st.armed = true; st.onGround = false; }
  }

  _beginItem(i) {
    const E = this.ex; E.idx = i; E.itemT = 0; E.timeFault = false;
    const item = this.items[i];
    let steps = item.steps.map(s => ({ ...s }));
    if (item.start !== 'ground_H' && (this.st.onGround || !this.st.armed)) {
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
    if (item && item.crosswind && !this.ex.done) { mag = Math.max(mag, 2.2); dir = 0; } // 측풍(앞쪽→조종자 방향)
    const gust = 1 + 0.35 * Math.sin(this.t * 0.7) + 0.2 * Math.sin(this.t * 2.3 + 1);
    return new THREE.Vector3(Math.sin(dir) * mag * gust, 0, -Math.cos(dir) * mag * gust * (item && item.crosswind ? 1 : 1));
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
      const tol = st.tol || 1.0, vtol = 0.8;
      this._dev = { dh, dv, tol };
      let wantHd = st.heading;
    if (st.circle && st.heading != null) { const ph = Math.atan2(s.pos.x - st.circle.cx, st.circle.cz + 0 - s.pos.z + 0) ; wantHd = wrapDeg(90 - (Math.atan2(s.pos.x, (st.circle.cz - s.pos.z)) * 180 / Math.PI)); void ph; }
    st.wantHd = wantHd;
    const hdErr = wantHd == null ? 0 : Math.abs(wrapDeg(yawDeg - wantHd));
      if (st.kind === 'yaw') {
        if (dh > 1.6 || dv > 1.3) this._fault('기수 회전 중 위치 이탈');
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
          if (d.h > 2.2) this._fault('비행 경로 이탈(수평)');
          if (d.v > 1.6) this._fault('비행 경로 이탈(고도)');
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
    this.sockCone.rotation.x = -Math.PI / 2 + Math.max(0, 1.2 - wm * 0.4);
  }

  _camera(dt) {
    const s = this.st, cam = this.camera; cam.up.set(0, 1, 0);
    this.pilotFig.visible = this.camMode !== 'pilot';
    if (this.camMode === 'pilot') {
      cam.position.set(0, 1.7, -1.0);
      const look = this._look || (this._look = s.pos.clone());
      look.lerp(new THREE.Vector3(s.pos.x, s.pos.y + 0.3, s.pos.z), Math.min(1, dt * 4));
      const dist = cam.position.distanceTo(look);
      cam.fov = Math.max(24, Math.min(60, 2 * Math.atan(7 / dist) / DEG));
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
      cam.position.set(0, 55, this.L.C.z * 0.55); cam.up.set(0, 0, 1); cam.fov = 50;
      cam.lookAt(0, 0, this.L.C.z * 0.55);
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
  drawMinimap(ctx, w, h) {
    const L = this.L; const span = Math.max(L.D * 2 + 20, L.C.z + 20);
    const sc = Math.min(w, h) / span;
    const X = x => w / 2 - x * sc, Y = z => h - 10 - z * sc;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(255,255,255,.4)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(X(0), Y(L.C.z + L.circleR), L.circleR * sc, 0, 7); ctx.stroke();
    const pt = (p, c, t) => { ctx.fillStyle = c; ctx.fillRect(X(p.x) - 4, Y(p.z) - 4, 8, 8); ctx.fillStyle = '#fff'; ctx.font = '11px sans-serif'; ctx.fillText(t, X(p.x) + 6, Y(p.z) + 4); };
    pt({ x: 0, z: 0 }, '#4af', '조종자'); pt(L.H, '#fff', 'H'); pt(L.EM, '#f55', '비상'); pt(L.C, '#fd4', 'E'); pt(L.A, '#8df', 'A'); pt(L.B, '#fbb', 'B');
    const s = this.st;
    ctx.save(); ctx.translate(X(s.pos.x), Y(s.pos.z)); ctx.rotate(-s.yaw);
    ctx.fillStyle = '#ff3b30'; ctx.beginPath(); ctx.moveTo(0, -9); ctx.lineTo(6, 7); ctx.lineTo(-6, 7); ctx.closePath(); ctx.fill(); ctx.restore();
  }
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
