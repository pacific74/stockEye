// 자동차 장내기능시험 시뮬레이터 (1종보통 / 2종보통 / 1종대형)
import * as THREE from 'three';
import { CAR_COURSES, buildPath, makeRect, inRect, rightOf } from './courses.js';

const DEG = Math.PI / 180;
const VEH = {
  sedan: { len: 4.7, wid: 1.85, h: 1.45, wb: 2.7, fo: 0.95, ro: 1.05, maxSteer: 36 * DEG, accel: 3.0, vmax: 60, color: 0xeef1f4, camDist: 8, camH: 3.2, seatH: 1.15 },
  bus:   { len: 11.0, wid: 2.5, h: 3.1, wb: 6.0, fo: 2.4, ro: 2.6, maxSteer: 42 * DEG, accel: 1.6, vmax: 50, color: 0xf2b705, camDist: 17, camH: 6.5, seatH: 2.2 },
};
// 수동변속: 단별 가속력과 최고속도(km/h), 시동꺼짐 속도
const GEARS = {
  '1': { a: 2.8, vmax: 20, stall: 0 }, '2': { a: 1.9, vmax: 38, stall: 7 }, '3': { a: 1.3, vmax: 58, stall: 15 },
  'R': { a: -2.2, vmax: 12, stall: 0 },
};
const CLR = { line: 0xffffff, yellow: 0xffcc00, road: 0x3d4148, ground: 0x6f8f4e };

export class CarSim {
  constructor(variant, mode, hud) {
    this.kind = 'car';
    this.variant = CAR_COURSES[variant] ? variant : '2종보통';
    this.course = CAR_COURSES[this.variant];
    this.mode = mode === 'exam' ? 'exam' : 'practice';
    this.hud = hud;
    this.V = VEH[this.course.vehicle];
    this.path = buildPath(this.course.pts, this.course.radius);
    this.hw = this.course.hw;
    this.camMode = 'chase';
    this.input = { steer: 0, thr: 0, brk: 0, clu: 0 };
    this.t = 0;
    this._setupZones();
    this._buildScene();
    this.reset();
  }

  // ---------- 코스 구간 계산 ----------
  _setupZones() {
    const c = this.course, P = this.path;
    const Z = this.zones = {};
    if (c.slope) {
      const sc = P.sAt(...c.slope.at);
      Z.slope = { s0: sc - 18, up: 16, flat: 4, down: 16, h: 1.6 };
      Z.slope.stop0 = Z.slope.s0 + 9; Z.slope.stop1 = Z.slope.s0 + 15.5; // 정지구간(앞범퍼 기준)
    }
    if (c.parking) {
      const s = P.sAt(...c.parking.at); const p = P.pointAt(s);
      const r = rightOf({ x: p.tx, z: p.tz });
      const depth = 5.6, width = 2.9;
      const bc = { x: p.x + r.x * (this.hw + depth / 2), z: p.z + r.z * (this.hw + depth / 2) };
      Z.parking = {
        s, p, r, depth, width,
        bay: makeRect(bc.x, bc.z, r.x, r.z, depth / 2, width / 2),
        apron: makeRect(p.x - r.x * (this.hw + 1.6), p.z - r.z * (this.hw + 1.6), p.tx, p.tz, 13, 1.6),
      };
    }
    if (c.signal) {
      const sc = P.sAt(...c.signal.at);
      Z.signal = { sc, stop: sc - 9, p: P.pointAt(sc), ps: P.pointAt(sc - 9) };
    }
    if (c.accel) Z.accel = { s0: P.sAt(...c.accel.from), s1: P.sAt(...c.accel.to) };
    if (c.crank) Z.crank = { s0: P.sAt(...c.crank.from), s1: P.sAt(...c.crank.to) };
    if (c.scurve) Z.scurve = { s0: P.sAt(...c.scurve.from), s1: P.sAt(...c.scurve.to) };
    Z.finish = P.sAt(...c.finish);
    Z.startS = P.sAt(...c.start);
  }

  heightAt(s) {
    const z = this.zones.slope; if (!z) return 0;
    const a = s - z.s0;
    if (a <= 0) return 0;
    if (a < z.up) return z.h * a / z.up;
    if (a < z.up + z.flat) return z.h;
    if (a < z.up + z.flat + z.down) return z.h * (1 - (a - z.up - z.flat) / z.down);
    return 0;
  }
  gradeAt(s) { return (this.heightAt(s + 0.25) - this.heightAt(s - 0.25)) / 0.5; }

  // ---------- 장면 구성 ----------
  _buildScene() {
    const S = this.scene = new THREE.Scene();
    S.background = new THREE.Color(0x9cc8ec);
    S.fog = new THREE.Fog(0x9cc8ec, 120, 420);
    this.camera = new THREE.PerspectiveCamera(60, 16 / 9, 0.1, 1000);
    S.add(new THREE.HemisphereLight(0xffffff, 0x556644, 1.0));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(60, 120, 40); S.add(sun);

    const ground = new THREE.Mesh(new THREE.PlaneGeometry(1200, 1200), new THREE.MeshLambertMaterial({ color: CLR.ground }));
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.02; S.add(ground);
    // 시험장 바닥(아스팔트 패드)
    const box = this._bounds();
    const pad = new THREE.Mesh(new THREE.PlaneGeometry(box.w + 40, box.h + 40), new THREE.MeshLambertMaterial({ color: 0x8a8f86 }));
    pad.rotation.x = -Math.PI / 2; pad.position.set(box.cx, -0.01, box.cz); S.add(pad);

    // 도로 리본 + 차선(검지선)
    S.add(this._ribbon(-this.hw, this.hw, 0.0, CLR.road));
    S.add(this._ribbon(-this.hw - 0.08, -this.hw + 0.08, 0.012, CLR.line));
    S.add(this._ribbon(this.hw - 0.08, this.hw + 0.08, 0.012, CLR.line));
    this._skirt();

    const Z = this.zones;
    const label = (txt, s, side = -1, color = '#ffffff') => {
      const p = this.path.pointAt(s); const r = rightOf({ x: p.tx, z: p.tz });
      const sp = makeLabel(txt, color); sp.position.set(p.x + r.x * side * (this.hw + 3), this.heightAt(s) + 3.2, p.z + r.z * side * (this.hw + 3)); S.add(sp);
    };
    // 출발/종료선
    this._crossLine(Z.startS + this.V.wb + this.V.fo + 0.4, 0xffffff, 0.3); label('출발', Z.startS + 14);
    this._crossLine(Z.finish, 0x00d26a, 0.5); label('종료', Z.finish, -1, '#7dffb0');
    if (Z.slope) {
      this._crossLine(Z.slope.stop0, CLR.yellow, 0.25); this._crossLine(Z.slope.stop1, CLR.yellow, 0.25);
      label('경사로', Z.slope.s0 + 10, -1, '#ffd84a');
    }
    if (Z.parking) this._buildParking();
    if (Z.signal) this._buildSignal();
    if (Z.accel) { this._crossLine(Z.accel.s0, 0x33aaff, 0.3); this._crossLine(Z.accel.s1, 0x33aaff, 0.3); label('가속구간 20km/h↑', (Z.accel.s0 + Z.accel.s1) / 2, -1, '#8fd3ff'); }
    if (Z.crank) label('굴절코스', Z.crank.s0 + 6);
    if (Z.scurve) label('곡선(S자)코스', Z.scurve.s0 + 8);
    this._scenery(box);
    this.car = this._buildCar();
    S.add(this.car.group);
  }

  _bounds() {
    let x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9;
    for (const p of this.path.pts) { x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); z0 = Math.min(z0, p.z); z1 = Math.max(z1, p.z); }
    return { x0, x1, z0, z1, w: x1 - x0, h: z1 - z0, cx: (x0 + x1) / 2, cz: (z0 + z1) / 2 };
  }

  _ribbon(o0, o1, lift, color) {
    const P = this.path.pts, pos = [], idx = [];
    for (let i = 0; i < P.length; i++) {
      const a = P[Math.max(0, i - 1)], b = P[Math.min(P.length - 1, i + 1)];
      const t = { x: b.x - a.x, z: b.z - a.z }; const L = Math.hypot(t.x, t.z) || 1;
      const r = { x: -t.z / L, z: t.x / L };
      const y = this.heightAt(P[i].s) + lift + 0.005;
      pos.push(P[i].x + r.x * o0, y, P[i].z + r.z * o0, P[i].x + r.x * o1, y, P[i].z + r.z * o1);
      if (i > 0) { const k = i * 2; idx.push(k - 2, k - 1, k, k - 1, k + 1, k); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
    return new THREE.Mesh(g, new THREE.MeshLambertMaterial({ color, side: THREE.DoubleSide }));
  }

  _skirt() {
    const z = this.zones.slope; if (!z) return;
    const P = this.path.pts.filter(p => p.s >= z.s0 - 0.5 && p.s <= z.s0 + z.up + z.flat + z.down + 0.5);
    const pos = [], idx = [];
    for (const side of [-1, 1]) {
      const base = pos.length / 3;
      P.forEach((p, i) => {
        const pp = this.path.pointAt(p.s); const r = rightOf({ x: pp.tx, z: pp.tz });
        const x = p.x + r.x * side * this.hw, zz = p.z + r.z * side * this.hw;
        pos.push(x, this.heightAt(p.s), zz, x, -0.01, zz);
        if (i > 0) { const k = base + i * 2; idx.push(k - 2, k - 1, k, k - 1, k + 1, k); }
      });
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
    this.scene.add(new THREE.Mesh(g, new THREE.MeshLambertMaterial({ color: 0x9a9a92, side: THREE.DoubleSide })));
  }

  _crossLine(s, color, width) {
    const p = this.path.pointAt(s); const r = rightOf({ x: p.tx, z: p.tz });
    const m = new THREE.Mesh(new THREE.PlaneGeometry(this.hw * 2, width), new THREE.MeshBasicMaterial({ color }));
    m.position.set(p.x, this.heightAt(s) + 0.03, p.z);
    m.rotation.set(-Math.PI / 2, 0, -Math.atan2(r.z, r.x));
    this.scene.add(m);
    return m;
  }

  _rectMesh(rect, color, y = 0.006, lineColor = null) {
    const g = new THREE.Group();
    const ang = Math.atan2(rect.uz, rect.ux);
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(rect.hu * 2, rect.hv * 2), new THREE.MeshLambertMaterial({ color }));
    plane.rotation.set(-Math.PI / 2, 0, -ang); plane.position.set(rect.cx, y, rect.cz); g.add(plane);
    if (lineColor !== null) {
      const ux = rect.ux, uz = rect.uz, vx = -uz, vz = ux;
      const corner = (a, b) => [rect.cx + ux * a + vx * b, rect.cz + uz * a + vz * b];
      const pts = [corner(-rect.hu, -rect.hv), corner(rect.hu, -rect.hv), corner(rect.hu, rect.hv), corner(-rect.hu, rect.hv)];
      for (let i = 0; i < 4; i++) {
        if (i === 3) continue; // 도로 쪽(입구) 변은 선 없음
        const [x0, z0] = pts[i], [x1, z1] = pts[i + 1];
        const L = Math.hypot(x1 - x0, z1 - z0);
        const m = new THREE.Mesh(new THREE.PlaneGeometry(L, 0.15), new THREE.MeshBasicMaterial({ color: lineColor }));
        m.rotation.set(-Math.PI / 2, 0, -Math.atan2(z1 - z0, x1 - x0)); m.position.set((x0 + x1) / 2, y + 0.006, (z0 + z1) / 2); g.add(m);
      }
    }
    this.scene.add(g);
  }

  _buildParking() {
    const Z = this.zones.parking;
    // 주차구역: 입구(도로 쪽 변) 제외 3면 검지선
    const bay = { ...Z.bay };
    // 입구 변이 index 3 이 되도록 u 축을 도로 반대 방향으로(이미 r 방향) 둠 → corner(-hu,...) 쪽이 도로
    this._rectMesh(bay, 0x4a4f57, 0.004, CLR.line);
    this._rectMesh(Z.apron, CLR.road, 0.003, null);
    // 확장도로 바깥 선
    const ap = Z.apron; const vx = -ap.uz, vz = ap.ux;
    const ox = ap.cx - Z.r.x * ap.hv, oz = ap.cz - Z.r.z * ap.hv;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(ap.hu * 2, 0.15), new THREE.MeshBasicMaterial({ color: CLR.line }));
    m.rotation.set(-Math.PI / 2, 0, -Math.atan2(ap.uz, ap.ux)); m.position.set(ox, 0.012, oz); this.scene.add(m);
    void vx; void vz;
    const sp = makeLabel('직각주차(T)', '#ffffff');
    sp.position.set(Z.bay.cx + Z.r.x * 4, 3.5, Z.bay.cz + Z.r.z * 4); this.scene.add(sp);
  }

  _buildSignal() {
    const Z = this.zones.signal; const p = Z.p;
    const r = rightOf({ x: p.tx, z: p.tz });
    // 교차 도로
    const cross = new THREE.Mesh(new THREE.PlaneGeometry(60, 7), new THREE.MeshLambertMaterial({ color: CLR.road }));
    cross.rotation.set(-Math.PI / 2, 0, -Math.atan2(r.z, r.x)); cross.position.set(p.x + r.x * 0, -0.003, p.z); this.scene.add(cross);
    // 정지선
    this._crossLine(Z.stop, 0xffffff, 0.45);
    // 신호등 (진행방향 오른쪽 앞)
    const pole = new THREE.Group();
    const ps = this.path.pointAt(Z.stop + 4);
    pole.position.set(ps.x + r.x * (this.hw + 1.2), 0, ps.z + r.z * (this.hw + 1.2));
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 5), new THREE.MeshLambertMaterial({ color: 0x333333 }));
    post.position.y = 2.5; pole.add(post);
    const head = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.6, 0.5), new THREE.MeshLambertMaterial({ color: 0x111111 }));
    head.position.y = 5.2; pole.add(head);
    const mk = (x, c) => { const l = new THREE.Mesh(new THREE.CircleGeometry(0.2, 16), new THREE.MeshBasicMaterial({ color: c })); l.position.set(x, 5.2, -0.26); l.rotation.y = Math.PI; pole.add(l); return l; };
    this.lamps = { red: mk(0.45, 0x330000), yellow: mk(0, 0x332a00), green: mk(-0.45, 0x003300) };
    pole.rotation.y = Math.atan2(p.tx, p.tz);
    this.scene.add(pole);
    const sp = makeLabel('신호교차로', '#ffffff'); sp.position.set(p.x - r.x * (this.hw + 3), 3.4, p.z - r.z * (this.hw + 3)); this.scene.add(sp);
  }

  _scenery(box) {
    const mat = [0xc9ccd1, 0xb7b0a3, 0xd8d2c4].map(c => new THREE.MeshLambertMaterial({ color: c }));
    const rnd = mulberry(7);
    for (let i = 0; i < 26; i++) {
      const side = i % 4;
      const w = 8 + rnd() * 14, h = 6 + rnd() * 18, d = 8 + rnd() * 12;
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat[i % 3]);
      let x, z;
      if (side === 0) { x = box.x0 - 45 - rnd() * 40; z = box.z0 + rnd() * box.h; }
      else if (side === 1) { x = box.x1 + 45 + rnd() * 40; z = box.z0 + rnd() * box.h; }
      else if (side === 2) { z = box.z0 - 45 - rnd() * 40; x = box.x0 + rnd() * box.w; }
      else { z = box.z1 + 45 + rnd() * 40; x = box.x0 + rnd() * box.w; }
      b.position.set(x, h / 2, z); this.scene.add(b);
    }
    const tm = new THREE.MeshLambertMaterial({ color: 0x2f6b2f }), trunk = new THREE.MeshLambertMaterial({ color: 0x6b4a2b });
    for (let i = 0; i < 40; i++) {
      const t = new THREE.Group();
      const c = new THREE.Mesh(new THREE.ConeGeometry(1.6, 4, 7), tm); c.position.y = 3.5; t.add(c);
      const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.25, 1.6), trunk); tr.position.y = 0.8; t.add(tr);
      const a = rnd() * Math.PI * 2;
      t.position.set(box.cx + Math.cos(a) * (box.w / 2 + 25 + rnd() * 10), 0, box.cz + Math.sin(a) * (box.h / 2 + 25 + rnd() * 10));
      this.scene.add(t);
    }
  }

  _buildCar() {
    const V = this.V; const g = new THREE.Group();
    const body = new THREE.Group(); g.add(body);
    const cz = (V.wb + V.fo - V.ro) / 2;
    const paint = new THREE.MeshLambertMaterial({ color: V.color });
    const glass = new THREE.MeshLambertMaterial({ color: 0x223344 });
    if (this.course.vehicle === 'bus') {
      const b = new THREE.Mesh(new THREE.BoxGeometry(V.wid, V.h - 0.4, V.len), paint); b.position.set(0, 0.4 + (V.h - 0.4) / 2, cz); body.add(b);
      for (const sx of [-1, 1]) { const w = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.9, V.len - 1.4), glass); w.position.set(sx * (V.wid / 2 + 0.01), 2.3, cz - 0.3); body.add(w); }
      const ws = new THREE.Mesh(new THREE.BoxGeometry(V.wid - 0.2, 1.3, 0.05), glass); ws.position.set(0, 2.1, V.wb + V.fo + 0.01); body.add(ws);
    } else {
      const b = new THREE.Mesh(new THREE.BoxGeometry(V.wid, 0.65, V.len), paint); b.position.set(0, 0.55, cz); body.add(b);
      const cab = new THREE.Mesh(new THREE.BoxGeometry(V.wid - 0.2, 0.55, V.len * 0.5), glass); cab.position.set(0, 1.15, cz - 0.15); body.add(cab);
      const roof = new THREE.Mesh(new THREE.BoxGeometry(V.wid - 0.25, 0.06, V.len * 0.46), paint); roof.position.set(0, 1.45, cz - 0.15); body.add(roof);
      // 시험차 표시 지붕등
      const sign = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.25, 0.3), new THREE.MeshLambertMaterial({ color: 0x1f6feb })); sign.position.set(0, 1.6, cz - 0.1); body.add(sign);
    }
    // 바퀴
    const wr = this.course.vehicle === 'bus' ? 0.52 : 0.33;
    const wGeo = new THREE.CylinderGeometry(wr, wr, 0.28, 16); wGeo.rotateZ(Math.PI / 2);
    const wMat = new THREE.MeshLambertMaterial({ color: 0x151515 });
    const wheels = [];
    for (const [x, z, front] of [[1, V.wb, 1], [-1, V.wb, 1], [1, 0, 0], [-1, 0, 0]]) {
      const holder = new THREE.Group(); holder.position.set(x * (V.wid / 2 - 0.15), wr, z);
      const w = new THREE.Mesh(wGeo, wMat); holder.add(w); g.add(holder); wheels.push({ holder, w, front });
    }
    // 등화
    const lamp = (c, x, y, z, sx = 0.35, sy = 0.15) => { const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, 0.05), new THREE.MeshBasicMaterial({ color: c })); m.position.set(x, y, z); g.add(m); return m; };
    const fz = V.wb + V.fo + 0.02, rz = -V.ro - 0.02, ly = this.course.vehicle === 'bus' ? 0.9 : 0.6;
    const head = [lamp(0x555544, 0.55 * V.wid / 1.85, ly, fz), lamp(0x555544, -0.55 * V.wid / 1.85, ly, fz)];
    const brake = [lamp(0x440000, 0.6 * V.wid / 1.85, ly + 0.1, rz), lamp(0x440000, -0.6 * V.wid / 1.85, ly + 0.1, rz)];
    // 좌(+x) / 우(-x) 깜빡이
    const blinkL = [lamp(0x442200, V.wid / 2 - 0.05, ly, fz, 0.2), lamp(0x442200, V.wid / 2 - 0.05, ly + 0.1, rz, 0.2)];
    const blinkR = [lamp(0x442200, -V.wid / 2 + 0.05, ly, fz, 0.2), lamp(0x442200, -V.wid / 2 + 0.05, ly + 0.1, rz, 0.2)];
    // 헤드라이트 빛
    const spot = new THREE.SpotLight(0xfff3c4, 0, 40, 0.5, 0.5); spot.position.set(0, ly, fz); spot.target.position.set(0, 0, fz + 12); g.add(spot); g.add(spot.target);
    return { group: g, body, wheels, wr, head, brake, blinkL, blinkR, spot };
  }

  // ---------- 상태 초기화 ----------
  reset() {
    const P = this.path, Z = this.zones;
    const p = P.pointAt(Z.startS);
    this.st = {
      x: p.x, z: p.z, th: Math.atan2(p.tx, p.tz), v: 0, delta: 0, y: 0, pitch: 0,
      engine: false, gear: this.course.manual ? 'N' : 'P', belt: false, pbrake: true,
      signal: null, hazard: false, lights: false, wiper: false, wheelRot: 0,
      stallTimer: 0, lowKTime: 0, sigTh: 0,
    };
    this.ex = {
      phase: 'prep', score: 100, fails: [], log: [], time: 0, driveTime: 0, done: false,
      prepStep: 0, prepTasks: this._makePrepTasks(), taskT: 0,
      touching: false, touchCD: 0,
      slope: { stopped: false, stopS: 0, stopT: 0, rolled: false, passed: false, pen: false },
      park: { state: Z.parking ? 'pending' : 'none', t0: 0, stillT: 0, timeoutPen: false },
      corners: this.path.corners.map(c => ({ ...c, ok: false, judged: false })),
      sig: { phase: 'off', t: 0, crossed: false },
      accel: { max: 0, judged: false },
      stallCount: 0,
    };
    this.hud.clearLog();
    this.hud.hideResult();
    this._instr('시동을 걸고 안전띠를 매세요', 'info');
  }

  _makePrepTasks() {
    const man = this.course.manual;
    const pool = [
      { text: '전조등을 켜세요', check: s => s.lights },
      { text: '와이퍼를 작동하세요', check: s => s.wiper },
      { text: '좌측 방향지시등을 켜세요', check: s => s.signal === 'L' },
      { text: '우측 방향지시등을 켜세요', check: s => s.signal === 'R' },
      man ? { text: '기어를 2단에 넣으세요 (클러치)', check: s => s.gear === '2' } : { text: '기어를 N(중립)으로 변속하세요', check: s => s.gear === 'N' },
    ];
    const pick = pool.sort(() => Math.random() - 0.5).slice(0, 4);
    return pick;
  }

  // ---------- 입력/명령 ----------
  setInput(d) { Object.assign(this.input, d); this.lastInput = performance.now(); }

  command(c, arg) {
    const s = this.st, I = this.input, man = this.course.manual;
    switch (c) {
      case 'engine':
        if (s.engine) { s.engine = false; this._msg('시동 끔'); break; }
        if (!man && !(s.gear === 'P' || s.gear === 'N')) { this._msg('P 또는 N 에서 시동을 거세요'); break; }
        if (!man && I.brk < 0.3) { this._msg('브레이크를 밟고 시동을 거세요'); break; }
        if (man && s.gear !== 'N' && I.clu < 0.5) { this._msg('클러치를 밟고 시동을 거세요'); break; }
        s.engine = true; s.stallTimer = 0; this._msg('시동 켜짐'); break;
      case 'gear': {
        const g = String(arg);
        if (man) {
          if (!['N', '1', '2', '3', 'R'].includes(g)) break;
          if (I.clu < 0.5) { this._msg('클러치를 끝까지 밟고 변속하세요'); this.event('warn'); break; }
          if (g === 'R' && s.v > 0.5) { this._msg('정지 후 후진 기어를 넣으세요'); break; }
        } else {
          if (!['P', 'R', 'N', 'D'].includes(g)) break;
          if ((g === 'P' || g === 'R' || s.gear === 'P') && I.brk < 0.3) { this._msg('브레이크를 밟고 변속하세요'); this.event('warn'); break; }
          if ((g === 'P' || g === 'R') && Math.abs(s.v) > 0.6) { this._msg('완전히 정지한 뒤 변속하세요'); break; }
        }
        s.gear = g; break;
      }
      case 'signal': s.signal = s.signal === arg ? null : arg; s.sigTh = s.th; break;
      case 'hazard': s.hazard = !s.hazard; break;
      case 'lights': s.lights = !s.lights; break;
      case 'wiper': s.wiper = !s.wiper; break;
      case 'belt': s.belt = !s.belt; break;
      case 'pbrake': s.pbrake = !s.pbrake; break;
      case 'camera': this.camMode = { chase: 'cockpit', cockpit: 'top', top: 'chase' }[this.camMode]; break;
      case 'restart': this.reset(); break;
      case 'jump': this.jump(arg); break;
    }
  }

  jumpList() {
    const Z = this.zones, L = [{ id: 'start', name: '출발점(처음부터)' }];
    if (Z.crank) L.push({ id: 'crank', name: '굴절코스' });
    if (Z.scurve) L.push({ id: 'scurve', name: '곡선(S자)코스' });
    if (Z.slope) L.push({ id: 'slope', name: '경사로' });
    if (Z.parking) L.push({ id: 'parking', name: '직각주차' });
    if (Z.signal) L.push({ id: 'signal', name: '신호교차로' });
    if (Z.accel) L.push({ id: 'accel', name: '가속구간' });
    return L;
  }

  jump(id) {
    if (this.mode === 'exam') { this._msg('시험 모드에서는 구간 이동을 할 수 없습니다'); return; }
    if (id === 'start') { this.reset(); return; }
    const Z = this.zones; const map = { crank: Z.crank?.s0 - 6, scurve: Z.scurve?.s0 - 6, slope: Z.slope?.s0 - 12, parking: Z.parking?.s - 22, signal: Z.signal?.stop - 30, accel: Z.accel?.s0 - 12 };
    const s0 = map[id]; if (s0 == null || isNaN(s0)) return;
    this.reset();
    const p = this.path.pointAt(Math.max(0, s0));
    Object.assign(this.st, { x: p.x, z: p.z, th: Math.atan2(p.tx, p.tz), v: 0, engine: true, belt: true, pbrake: false, gear: this.course.manual ? 'N' : 'D' });
    const E = this.ex; E.phase = 'drive'; E.prepStep = 99;
    const sNow = this.path.sAt(p.x, p.z);
    E.corners.forEach(c => { if (c.sStart < sNow + 1) c.judged = true; });
    if (Z.slope && sNow > Z.slope.s0) E.slope.passed = true;
    if (Z.parking && sNow > Z.parking.s + 10) E.park.state = 'done';
    if (Z.signal && sNow > Z.signal.stop) E.sig.crossed = true;
    if (Z.accel && sNow > Z.accel.s1) E.accel.judged = true;
    this._instr(`[연습] ${this.jumpList().find(j => j.id === id)?.name} 구간 — 출발하세요`, 'info');
  }

  // ---------- 메인 업데이트 ----------
  update(dt) {
    this.t += dt;
    // 휴대폰 신호 끊김 → 페달 해제(안전)
    if (this.lastInput && performance.now() - this.lastInput > 700) { this.input.thr = 0; this.input.brk = 0.6; }
    this._physics(dt);
    this._exam(dt);
    this._visuals(dt);
    this._camera(dt);
  }

  _physics(dt) {
    const s = this.st, V = this.V, I = this.input, man = this.course.manual;
    // 조향
    const target = Math.max(-1, Math.min(1, I.steer)) * V.maxSteer;
    const rate = 2.5 * dt; s.delta += Math.max(-rate, Math.min(rate, target - s.delta));

    const near = this.path.nearest(s.x + Math.sin(s.th) * V.wb / 2, s.z + Math.cos(s.th) * V.wb / 2);
    s.sMid = near.s;
    const align = Math.sin(s.th) * near.tx + Math.cos(s.th) * near.tz;
    const grade = this.gradeAt(near.s) * align;
    const aGrav = -9.8 * grade / Math.sqrt(1 + grade * grade);

    let aDrive = 0; let k = 0;
    const kmh = s.v * 3.6;
    if (s.engine) {
      if (!man) {
        const thr = I.thr;
        if (s.gear === 'D') aDrive = thr * V.accel * Math.max(0, 1 - Math.max(0, kmh) / V.vmax) + (I.brk < 0.1 && s.v < 1.8 ? (1.8 - s.v) * 1.0 : 0);
        if (s.gear === 'R') aDrive = -(thr * 2.0 * Math.max(0, 1 - Math.abs(Math.min(0, kmh)) / 15) + (I.brk < 0.1 && s.v > -1.3 ? (1.3 + s.v) * 1.0 : 0));
      } else if (s.gear !== 'N') {
        const G = GEARS[s.gear];
        k = Math.max(0, Math.min(1, (0.85 - I.clu) / 0.55)); // 클러치 연결 정도
        const fwd = s.gear !== 'R';
        const vAbs = fwd ? kmh : -kmh;
        let a = I.thr * Math.abs(G.a) * Math.max(0, 1 - Math.max(0, vAbs) / G.vmax);
        if (vAbs > G.vmax) a -= 1.2; // 엔진브레이크
        if (s.gear === '1' || s.gear === 'R') a += Math.max(0, (6 - vAbs) / 3.6) * 0.9; // 아이들 크립
        aDrive = (fwd ? a : -a) * k;
        // 시동 꺼짐 판정
        if (k < 0.4) s.lowKTime = this.t;
        let stall = false;
        if (k > 0.9) {
          if (G.stall > 0 && Math.abs(kmh) < G.stall) s.stallTimer += dt;
          else if ((s.gear === '1' || s.gear === 'R') && Math.abs(kmh) < 2 && I.brk > 0.35 && I.thr < 0.15) s.stallTimer += dt;
          else if (fwd ? kmh < -1 : kmh > 1) s.stallTimer += dt;
          else s.stallTimer = Math.max(0, s.stallTimer - dt);
          if (this.t - s.lowKTime < 0.22 && Math.abs(kmh) < 1 && I.thr < 0.2 && this._prevK < 0.9) stall = true; // 클러치를 급히 뗌
          if (s.stallTimer > 0.5) stall = true;
        } else s.stallTimer = 0;
        if (stall) this._stall();
      }
    }
    this._prevK = k;
    let resist = I.brk * 7.5 + (s.pbrake ? 4 : 0) + 0.12;
    if (s.gear === 'P') resist = 50;
    resist += 0.0005 * s.v * s.v;
    const net = aDrive + aGrav;
    if (Math.abs(s.v) < 0.03) {
      if (Math.abs(net) <= resist) s.v = 0;
      else s.v += (net - Math.sign(net) * resist) * dt;
    } else {
      const nv = s.v + (net - Math.sign(s.v) * resist) * dt;
      s.v = (Math.sign(nv) !== Math.sign(s.v) && Math.abs(net) < resist) ? 0 : nv;
    }
    // 이동 (후륜축 기준 자전거 모델)
    s.th -= (s.v / V.wb) * Math.tan(s.delta) * dt;
    s.x += Math.sin(s.th) * s.v * dt; s.z += Math.cos(s.th) * s.v * dt;
    s.y = this.heightAt(near.s);
    s.pitch = -Math.atan(grade);
    s.wheelRot += s.v * dt / this.car.wr;
    s.kmh = s.v * 3.6;
    // 방향지시등 자동 해제
    if (s.signal && Math.abs(angDiff(s.th, s.sigTh)) > 50 * DEG && Math.abs(I.steer) < 0.15) s.signal = null;
  }

  _stall() {
    const s = this.st; if (!s.engine) return;
    s.engine = false; s.stallTimer = 0;
    this.ex.stallCount++;
    this._penalty(5, '시동 꺼짐 (엔진 정지)');
  }

  corners() {
    const s = this.st, V = this.V;
    const f = { x: Math.sin(s.th), z: Math.cos(s.th) }, r = rightOf(f);
    const fr = V.wb + V.fo, rr = -V.ro, hw = V.wid / 2;
    return [[fr, hw], [fr, -hw], [rr, hw], [rr, -hw]].map(([a, b]) => ({ x: s.x + f.x * a + r.x * b, z: s.z + f.z * a + r.z * b }));
  }
  frontS() {
    const s = this.st, V = this.V; const d = V.wb + V.fo;
    return this.path.nearest(s.x + Math.sin(s.th) * d, s.z + Math.cos(s.th) * d).s;
  }

  // ---------- 채점 ----------
  _exam(dt) {
    const E = this.ex, s = this.st, I = this.input, Z = this.zones;
    if (E.done) return;
    E.time += dt;
    const moving = Math.abs(s.v) > 0.3;

    if (E.phase === 'prep') {
      if (moving && !s.belt) this._fail('안전띠 미착용 상태로 출발');
      if (moving && E.prepStep <= E.prepTasks.length && !E.earlyPen) { E.earlyPen = true; this._penalty(5, '기기조작 완료 전 출발'); E.prepStep = E.prepTasks.length + 1; }
      if (E.prepStep === 0) {
        if (s.engine && s.belt) { E.prepStep = 1; E.taskT = 0; this._instr(E.prepTasks[0].text, 'task'); }
      } else if (E.prepStep <= E.prepTasks.length) {
        const task = E.prepTasks[E.prepStep - 1];
        E.taskT += dt;
        if (task.check(s)) { this._ok(`기기조작 ✓ ${task.text}`); this._nextTask(); }
        else if (E.taskT > 5) { this._penalty(5, `기기조작 미이행: ${task.text}`); this._nextTask(); }
      }
      if (moving && E.prepStep > E.prepTasks.length) E.phase = 'drive';
      if (E.prepStep > E.prepTasks.length && !moving && E.phase === 'prep') {
        if (!E.go) { E.go = true; E.goT = 0; this._instr(this.course.manual ? '출발하세요: 클러치→1단→주차브레이크 해제→좌측 깜빡이' : '출발하세요: 브레이크 밟고 D→주차브레이크 해제', 'go'); }
        E.goT += dt;
        if (E.goT > 30) this._fail('출발 지시 후 30초 이내 미출발');
      }
      if (moving && s.pbrake) this._msg('주차브레이크를 해제하세요');
      return;
    }

    E.driveTime += dt;
    if (E.driveTime > this.course.timeLimit) this._fail(`제한시간(${this.course.timeLimit / 60}분) 초과`);
    if (!s.belt) this._fail('주행 중 안전띠 해제');
    if (s.pbrake && moving) { E.pbT = (E.pbT || 0) + dt; if (E.pbT > 2 && !E.pbPen) { E.pbPen = true; this._penalty(5, '주차브레이크를 채운 채 주행'); } }

    // 차로 준수(검지선)
    const pts = this.corners(); let touch = false; let nearBay = false;
    for (const p of pts) {
      const n = this.path.nearest(p.x, p.z);
      let ok = n.d <= this.hw;
      if (Z.parking) {
        if (inRect(Z.parking.bay, p.x, p.z)) ok = true;
        if (inRect(Z.parking.apron, p.x, p.z)) ok = true;
        if (Math.hypot(p.x - Z.parking.bay.cx, p.z - Z.parking.bay.cz) < 12) nearBay = true;
      }
      if (n.d > this.hw + 6) this._fail('코스 이탈');
      if (!ok) touch = true;
    }
    E.touchCD -= dt;
    if (touch && !E.touching && E.touchCD <= 0) {
      if (nearBay && E.park.state === 'active') this._penalty(10, '직각주차 검지선 접촉');
      else this._penalty(15, '차로 준수 위반 (검지선 접촉)');
      E.touchCD = 1.5;
    }
    E.touching = touch;

    const fS = this.frontS(); const mid = s.sMid;
    // 방향지시등 (회전 전 30m 구간)
    for (const c of E.corners) {
      if (c.judged || c.angle < 50 * DEG) { continue; }
      if (mid > c.sStart - 30 && mid < c.sStart + 2) {
        if (s.signal === c.dir) c.ok = true;
        if (!c.warned && mid > c.sStart - 25) { c.warned = true; if (this.mode === 'practice' && !c.ok) this._msg(`${c.dir === 'L' ? '좌' : '우'}회전 — ${c.dir === 'L' ? '좌측' : '우측'} 방향지시등!`); }
      }
      if (mid >= c.sStart + 2) { c.judged = true; if (!c.ok) this._penalty(5, `${c.dir === 'L' ? '좌' : '우'}회전 방향지시등 미작동`); }
    }

    // 경사로
    if (Z.slope && !E.slope.passed) {
      const S = E.slope, z = Z.slope;
      if (!S.stopped && fS >= z.stop0 && fS <= z.stop1) {
        this._hint('경사로 정지구간 — 완전히 정지하세요');
        if (Math.abs(s.v) < 0.02) { S.stopT0 = (S.stopT0 || 0) + dt; if (S.stopT0 > 1.0) { S.stopped = true; S.stopS = fS; S.stopT = E.time; this._ok('경사로 정지 ✓ — 30초 이내 출발'); } }
        else S.stopT0 = 0;
      }
      if (S.stopped) {
        if (!S.rolled && S.stopS - fS > 1.0) { S.rolled = true; this._fail('경사로에서 1m 이상 뒤로 밀림'); }
        else if (!S.rolled && S.stopS - fS > 0.5 && !S.pen) { S.pen = true; this._penalty(10, '경사로 뒤로 밀림(50cm 이상)'); }
        if (fS < z.s0 + z.up + 1 && E.time - S.stopT > 30) this._fail('경사로 정지 후 30초 이내 미통과');
      }
      if (fS > z.stop1 + 0.5 && !S.stopped && !S.missed) { S.missed = true; this._penalty(10, '경사로 정지구간 정지 불이행'); }
      if (fS > z.s0 + z.up + z.flat) S.passed = true;
    }

    // 직각주차
    if (Z.parking && E.park.state !== 'none' && E.park.state !== 'done') {
      const K = E.park, zp = Z.parking;
      if (K.state === 'pending' && mid > zp.s - 14) { K.state = 'active'; K.t0 = E.time; this._instr('직각주차: 주차구역에 차를 완전히 넣고 정지 후 출차', 'task'); }
      if (K.state === 'active' || K.state === 'parked') {
        if (E.time - K.t0 > 120 && !K.timeoutPen) { K.timeoutPen = true; this._penalty(10, '직각주차 제한시간(2분) 초과'); }
      }
      if (K.state === 'active') {
        const inside = pts.every(p => inRect(zp.bay, p.x, p.z));
        if (inside && Math.abs(s.v) < 0.05) { K.stillT += dt; if (K.stillT > 1) { K.state = 'parked'; this._ok('주차 완료 ✓ — 출차하세요'); } }
        else K.stillT = 0;
        if (mid > zp.s + 14) { K.state = 'done'; this._penalty(10, '직각주차 미이행'); }
      } else if (K.state === 'parked') {
        if (mid > zp.s + 8 && pts.every(p => !inRect(zp.bay, p.x, p.z))) { K.state = 'done'; this._instr('계속 주행하세요', 'info'); }
      }
    }

    // 신호교차로
    if (Z.signal) {
      const G = E.sig, z = Z.signal;
      if (G.phase === 'off' && mid > z.stop - 60) { G.phase = 'green'; G.t = Math.random() < 0.5 ? 0 : 4; }
      if (G.phase !== 'off') {
        G.t += dt;
        const dur = { green: 6, yellow: 3, red: 12 };
        if (G.t > dur[G.phase]) { G.t = 0; G.phase = { green: 'yellow', yellow: 'red', red: 'green' }[G.phase]; }
      }
      if (!G.crossed && fS >= z.stop) {
        G.crossed = true;
        if (G.phase === 'red') this._fail('신호 위반 (적색 신호에 정지선 통과)');
        else this._ok('신호교차로 통과 ✓');
      }
      if (!G.crossed && mid > z.stop - 30 && G.phase === 'red') this._hint('적색 신호 — 정지선 앞에 정지하세요');
    }

    // 가속구간
    if (Z.accel && !E.accel.judged) {
      if (mid > Z.accel.s0 && mid < Z.accel.s1) { E.accel.max = Math.max(E.accel.max, s.kmh); this._hint(`가속구간: 20km/h 이상! (현재 ${s.kmh.toFixed(0)})`); }
      if (mid >= Z.accel.s1) { E.accel.judged = true; if (E.accel.max < 20) this._penalty(10, `가속구간 20km/h 미달 (최고 ${E.accel.max.toFixed(0)}km/h)`); else this._ok(`가속구간 ✓ 최고 ${E.accel.max.toFixed(0)}km/h`); }
    }

    // 종료
    if (fS >= Z.finish) this._finish();
  }

  _nextTask() {
    const E = this.ex; E.prepStep++; E.taskT = 0;
    if (E.prepStep <= E.prepTasks.length) this._instr(E.prepTasks[E.prepStep - 1].text, 'task');
  }

  _penalty(pts, text) {
    const E = this.ex; if (E.done) return;
    E.score -= pts;
    this.hud.log(`−${pts} ${text}`, 'bad');
    this.event('penalty', `−${pts} ${text}`);
    if (this.mode === 'exam' && E.score < 80 && !E.under) { E.under = true; this.hud.log('합격 기준(80점) 미만', 'bad'); }
  }
  _fail(text) {
    const E = this.ex; if (E.done) return;
    if (this.mode === 'practice') {
      if (E.lastFail === text && E.time - (E.lastFailT || 0) < 5) return;
      E.lastFail = text; E.lastFailT = E.time;
      E.fails.push(text);
      this.hud.log(`실격 사유: ${text} (연습모드 계속)`, 'fail'); this.event('fail', text);
      return;
    }
    E.fails.push(text); E.done = true;
    this.hud.log(`실격: ${text}`, 'fail'); this.event('fail', text);
    this.hud.showResult('불합격 (실격)', `${text}<br><br>점수 ${E.score}점 · 주행시간 ${fmt(E.driveTime)}`, false);
    this._instr('시험 종료 — 휴대폰 메뉴에서 다시 시작', 'bad');
  }
  _finish() {
    const E = this.ex; if (E.done) return; E.done = true;
    const pass = E.score >= 80 && (this.mode === 'exam' ? E.fails.length === 0 : true);
    const extra = E.fails.length ? `<br>연습 중 실격 사유 ${E.fails.length}건: ${E.fails.join(', ')}` : '';
    this.hud.showResult(pass && !E.fails.length ? '합격!' : '불합격', `점수 ${E.score}점 (합격 80점 이상)<br>주행시간 ${fmt(E.driveTime)}${extra}`, pass && !E.fails.length);
    this.event(pass ? 'pass' : 'fail', `점수 ${E.score}`);
    this._instr('종료 지점 통과 — 수고하셨습니다', 'go');
  }
  _ok(t) { this.hud.log(t, 'ok'); }
  _msg(t) { this.hud.toast(t); }
  _hint(t) { this.hud.hint(t); }
  _instr(t, kind) { this.hud.instruction(t, kind); }
  event(kind, text) { this.onEvent && this.onEvent(kind, text); }

  // ---------- 그래픽 ----------
  _visuals() {
    const s = this.st, C = this.car, t = this.t;
    C.group.position.set(s.x, s.y, s.z);
    C.group.rotation.set(0, s.th, 0);
    C.body.rotation.x = s.pitch * 0.9;
    for (const w of C.wheels) { if (w.front) w.holder.rotation.y = -s.delta; w.w.rotation.x = s.wheelRot; }
    const blink = Math.floor(t * 3) % 2 === 0;
    const L = (s.signal === 'L' || s.hazard) && blink, R = (s.signal === 'R' || s.hazard) && blink;
    C.blinkL.forEach(m => m.material.color.setHex(L ? 0xffa000 : 0x442200));
    C.blinkR.forEach(m => m.material.color.setHex(R ? 0xffa000 : 0x442200));
    C.head.forEach(m => m.material.color.setHex(s.lights ? 0xffffdd : 0x555544));
    C.spot.intensity = s.lights ? 40 : 0;
    C.brake.forEach(m => m.material.color.setHex(this.input.brk > 0.1 ? 0xff2020 : (s.lights ? 0x881111 : 0x440000)));
    if (this.lamps) {
      const ph = this.ex.sig.phase;
      this.lamps.red.material.color.setHex(ph === 'red' ? 0xff2a2a : 0x330000);
      this.lamps.yellow.material.color.setHex(ph === 'yellow' ? 0xffcc00 : 0x332a00);
      this.lamps.green.material.color.setHex(ph === 'green' || ph === 'off' ? 0x22ff66 : 0x003300);
    }
  }

  _camera(dt) {
    const s = this.st, V = this.V, cam = this.camera;
    const f = { x: Math.sin(s.th), z: Math.cos(s.th) };
    const mid = { x: s.x + f.x * V.wb / 2, z: s.z + f.z * V.wb / 2 };
    cam.up.set(0, 1, 0);
    if (this.camMode === 'chase') {
      const back = s.v < -0.3 ? -0.6 : 1;
      const want = new THREE.Vector3(mid.x - f.x * V.camDist * back, s.y + V.camH, mid.z - f.z * V.camDist * back);
      if (!this._cp) this._cp = want.clone();
      this._cp.lerp(want, Math.min(1, dt * 3));
      cam.position.copy(this._cp); cam.fov = 60;
      cam.lookAt(mid.x + f.x * 4, s.y + 0.8, mid.z + f.z * 4);
    } else if (this.camMode === 'cockpit') {
      const r = rightOf(f); const fwd = this.course.vehicle === 'bus' ? V.wb + V.fo - 1.2 : V.wb * 0.42;
      cam.position.set(s.x + f.x * fwd - r.x * V.wid * 0.22, s.y + V.seatH, s.z + f.z * fwd - r.z * V.wid * 0.22);
      cam.fov = 75;
      cam.lookAt(cam.position.x + f.x * 10, s.y + V.seatH - 0.9 + Math.sin(s.pitch) * -10, cam.position.z + f.z * 10);
      this._cp = null;
    } else {
      cam.position.set(mid.x, s.y + (this.course.vehicle === 'bus' ? 48 : 30), mid.z);
      cam.up.set(f.x, 0, f.z); cam.fov = 55;
      cam.lookAt(mid.x, s.y, mid.z);
      this._cp = null;
    }
    cam.updateProjectionMatrix();
  }

  // ---------- HUD / 휴대폰 상태 ----------
  hudPanel() {
    const s = this.st, E = this.ex;
    const ind = (on, txt, cls = 'on') => `<span class="ind ${on ? cls : ''}">${txt}</span>`;
    const blink = Math.floor(this.t * 3) % 2 === 0;
    return `
      <div class="speed">${Math.abs(s.kmh || 0).toFixed(0)}<small>km/h</small></div>
      <div class="gear">${s.gear}${this.course.manual ? '<small>수동</small>' : '<small>자동</small>'}</div>
      <div class="inds">
        ${ind((s.signal === 'L' || s.hazard) && blink, '◀', 'amber')}
        ${ind(s.engine, '시동')}${ind(s.belt, '안전띠')}${ind(s.pbrake, 'P브레이크', 'red')}
        ${ind(s.lights, '전조등')}${ind(s.wiper, '와이퍼')}
        ${ind((s.signal === 'R' || s.hazard) && blink, '▶', 'amber')}
      </div>
      <div class="pedals">핸들 ${(this.input.steer * 100).toFixed(0)}% · 가속 ${(this.input.thr * 100).toFixed(0)} · 브레이크 ${(this.input.brk * 100).toFixed(0)}${this.course.manual ? ' · 클러치 ' + (this.input.clu * 100).toFixed(0) : ''}</div>`;
  }
  hudTop() {
    const E = this.ex;
    return `<b>${this.course.title}</b> · ${this.mode === 'exam' ? '시험모드' : '연습모드'}<br>
      점수 <b class="${E.score >= 80 ? 'good' : 'bad'}">${E.score}</b>/100 · 주행 ${fmt(E.driveTime)} / ${fmt(this.course.timeLimit)}`;
  }
  drawMinimap(ctx, w, h) {
    const b = this._mb || (this._mb = this._bounds());
    const sc = Math.min((w - 20) / b.w, (h - 20) / b.h);
    const X = x => w / 2 - (x - b.cx) * sc, Y = z => h / 2 - (z - b.cz) * sc; // x 반전: 위에서 본 모습(+z 위쪽)
    ctx.clearRect(0, 0, w, h);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(255,255,255,.85)'; ctx.lineWidth = Math.max(3, this.hw * 2 * sc);
    ctx.beginPath(); this.path.pts.forEach((p, i) => i ? ctx.lineTo(X(p.x), Y(p.z)) : ctx.moveTo(X(p.x), Y(p.z))); ctx.stroke();
    const dot = (s, c) => { const p = this.path.pointAt(s); ctx.fillStyle = c; ctx.beginPath(); ctx.arc(X(p.x), Y(p.z), 4, 0, 7); ctx.fill(); };
    const Z = this.zones;
    if (Z.slope) dot(Z.slope.s0 + 12, '#ffd84a');
    if (Z.parking) { ctx.fillStyle = '#9ad'; ctx.fillRect(X(Z.parking.bay.cx) - 4, Y(Z.parking.bay.cz) - 4, 8, 8); }
    if (Z.signal) dot(Z.signal.sc, this.ex.sig.phase === 'red' ? '#f33' : this.ex.sig.phase === 'yellow' ? '#fc0' : '#2f6');
    dot(Z.finish, '#2f6');
    const s = this.st;
    ctx.save(); ctx.translate(X(s.x), Y(s.z)); ctx.rotate(-s.th);
    ctx.fillStyle = '#ff3b30'; ctx.beginPath(); ctx.moveTo(0, -9); ctx.lineTo(6, 7); ctx.lineTo(-6, 7); ctx.closePath(); ctx.fill();
    ctx.restore();
  }
  phoneState() {
    const s = this.st;
    return { kind: 'car', variant: this.variant, mode: this.mode, manual: this.course.manual, kmh: Math.round(s.kmh || 0), gear: s.gear, engine: s.engine, belt: s.belt, pbrake: s.pbrake, signal: s.signal, hazard: s.hazard, lights: s.lights, wiper: s.wiper, score: this.ex.score, cam: this.camMode, instr: this.hud.currentInstr };
  }
}

export function makeLabel(text, color = '#fff') {
  const c = document.createElement('canvas'); const ctx = c.getContext('2d');
  ctx.font = 'bold 44px "Malgun Gothic", "Apple SD Gothic Neo", sans-serif';
  const w = Math.ceil(ctx.measureText(text).width) + 40; c.width = w; c.height = 72;
  ctx.font = 'bold 44px "Malgun Gothic", "Apple SD Gothic Neo", sans-serif';
  ctx.fillStyle = 'rgba(20,24,32,.78)'; roundRect(ctx, 0, 0, w, 72, 14); ctx.fill();
  ctx.fillStyle = color; ctx.textBaseline = 'middle'; ctx.fillText(text, 20, 38);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: true }));
  sp.scale.set(w / 72 * 1.4, 1.4, 1);
  return sp;
}
function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
export function fmt(sec) { sec = Math.max(0, Math.floor(sec)); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`; }
function angDiff(a, b) { let d = a - b; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; }
function mulberry(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
