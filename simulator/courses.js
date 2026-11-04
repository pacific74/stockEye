// 코스 정의 + 도로 경로(중심선) 계산 유틸
// 좌표계: x-z 평면, y 위쪽. 진행방향 각 θ 일 때 전방 f=(sinθ, cosθ), 우측 r=(-cosθ, sinθ)

export const CAR_COURSES = {
  '2종보통': {
    title: '제2종 보통 장내기능시험', vehicle: 'sedan', manual: false,
    hw: 1.75, radius: 9, timeLimit: 300,
    pts: [[0, -6], [0, 80], [-60, 80], [-60, -10], [-2, -10]],
    start: [0, 0],
    slope: { at: [0, 30] },
    parking: { at: [-30, 80] },
    signal: { at: [-60, 32] },
    accel: { from: [-48, -10], to: [-16, -10] },
    finish: [-8, -10],
  },
  '1종보통': {
    title: '제1종 보통 장내기능시험 (수동변속)', vehicle: 'sedan', manual: true,
    hw: 1.75, radius: 9, timeLimit: 300,
    pts: [[0, -6], [0, 80], [-60, 80], [-60, -10], [-2, -10]],
    start: [0, 0],
    slope: { at: [0, 30] },
    parking: { at: [-30, 80] },
    signal: { at: [-60, 32] },
    accel: { from: [-48, -10], to: [-16, -10] },
    finish: [-8, -10],
  },
  '1종대형': {
    title: '제1종 대형 장내기능시험 (버스)', vehicle: 'bus', manual: true,
    hw: 3.5, radius: 13, timeLimit: 420,
    pts: [[0, -12], [0, 50], [-26, 50], [-26, 80], [0, 80], [0, 104], [-14, 122], [0, 140], [-14, 158], [0, 176], [0, 200], [-82, 200], [-82, -16], [-4, -16]],
    start: [0, 0],
    crank: { from: [0, 36], to: [0, 92] },
    scurve: { from: [0, 100], to: [0, 182] },
    slope: { at: [-82, 150] },
    signal: { at: [-82, 70] },
    accel: { from: [-66, -16], to: [-24, -16] },
    finish: [-12, -16],
  },
};

const sub = (a, b) => ({ x: a.x - b.x, z: a.z - b.z });
const len = (v) => Math.hypot(v.x, v.z);
const norm = (v) => { const l = len(v) || 1; return { x: v.x / l, z: v.z / l }; };
export const rightOf = (d) => ({ x: -d.z, z: d.x });

// 꼭짓점을 원호로 둥글게 만든 촘촘한 중심선을 만든다
export function buildPath(rawPts, radius, step = 0.5) {
  const P = rawPts.map(([x, z]) => ({ x, z }));
  const out = [];
  const cornerIdx = [];
  const push = (p) => out.push({ x: p.x, z: p.z });
  const addLine = (a, b) => {
    const L = len(sub(b, a)); const n = Math.max(1, Math.ceil(L / step));
    for (let i = 1; i <= n; i++) push({ x: a.x + (b.x - a.x) * i / n, z: a.z + (b.z - a.z) * i / n });
  };
  push(P[0]);
  let cur = P[0];
  for (let i = 1; i < P.length - 1; i++) {
    const a = P[i - 1], b = P[i], c = P[i + 1];
    const d1 = norm(sub(b, a)), d2 = norm(sub(c, b));
    const dot = Math.max(-1, Math.min(1, d1.x * d2.x + d1.z * d2.z));
    const ang = Math.acos(dot);
    if (ang < 1e-3) { addLine(cur, b); cur = b; continue; }
    let t = radius * Math.tan(ang / 2);
    t = Math.min(t, 0.45 * len(sub(b, a)), 0.45 * len(sub(c, b)));
    const rr = t / Math.tan(ang / 2);
    const p1 = { x: b.x - d1.x * t, z: b.z - d1.z * t };
    const p2 = { x: b.x + d2.x * t, z: b.z + d2.z * t };
    addLine(cur, p1);
    const r1 = rightOf(d1);
    const isRight = (d2.x * r1.x + d2.z * r1.z) > 0;
    const sgn = isRight ? 1 : -1;
    const center = { x: p1.x + r1.x * rr * sgn, z: p1.z + r1.z * rr * sgn };
    const v = sub(p1, center);
    // 회전 방향 결정: φ=0 에서 접선이 d1 과 같아야 함
    const rotSign = ((-v.z) * d1.x + (v.x) * d1.z) > 0 ? 1 : -1;
    const startIdx = out.length - 1;
    const n = Math.max(2, Math.ceil(rr * ang / step));
    for (let k = 1; k <= n; k++) {
      const ph = rotSign * ang * k / n;
      const cs = Math.cos(ph), sn = Math.sin(ph);
      push({ x: center.x + v.x * cs - v.z * sn, z: center.z + v.x * sn + v.z * cs });
    }
    cornerIdx.push({ i0: startIdx, i1: out.length - 1, dir: isRight ? 'R' : 'L', angle: ang });
    cur = p2;
  }
  addLine(cur, P[P.length - 1]);
  // 누적 거리
  let s = 0; out[0].s = 0;
  for (let i = 1; i < out.length; i++) { s += len(sub(out[i], out[i - 1])); out[i].s = s; }
  const corners = cornerIdx.map(c => ({ sStart: out[c.i0].s, sEnd: out[c.i1].s, dir: c.dir, angle: c.angle }));
  return new RoadPath(out, corners);
}

export class RoadPath {
  constructor(pts, corners) { this.pts = pts; this.corners = corners; this.length = pts[pts.length - 1].s; }
  // 가장 가까운 중심선 위치 {d, s, tx, tz, lat}
  nearest(x, z) {
    const P = this.pts;
    let best = { d: 1e9, s: 0, tx: 0, tz: 1, lat: 0 };
    for (let i = 0; i < P.length - 1; i++) {
      const a = P[i], b = P[i + 1];
      const ex = b.x - a.x, ez = b.z - a.z; const L2 = ex * ex + ez * ez || 1e-9;
      let t = ((x - a.x) * ex + (z - a.z) * ez) / L2; t = t < 0 ? 0 : t > 1 ? 1 : t;
      const px = a.x + ex * t, pz = a.z + ez * t;
      const d = Math.hypot(x - px, z - pz);
      if (d < best.d) {
        const L = Math.sqrt(L2);
        const tx = ex / L, tz = ez / L;
        // 우측 = (-tz, tx)
        const lat = (x - px) * (-tz) + (z - pz) * tx;
        best = { d, s: a.s + (b.s - a.s) * t, tx, tz, lat };
      }
    }
    return best;
  }
  pointAt(s) {
    const P = this.pts;
    s = Math.max(0, Math.min(this.length, s));
    let lo = 0, hi = P.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (P[m].s <= s) lo = m; else hi = m; }
    const a = P[lo], b = P[hi]; const k = (s - a.s) / ((b.s - a.s) || 1);
    const tx = b.x - a.x, tz = b.z - a.z; const L = Math.hypot(tx, tz) || 1;
    return { x: a.x + tx * k, z: a.z + tz * k, tx: tx / L, tz: tz / L };
  }
  sAt(x, z) { return this.nearest(x, z).s; }
}

// 직사각형 판정: c 중심, u 단위벡터(길이 방향), hu/hv 반길이
export function makeRect(cx, cz, ux, uz, hu, hv) { return { cx, cz, ux, uz, hu, hv }; }
export function inRect(r, x, z, margin = 0) {
  const dx = x - r.cx, dz = z - r.cz;
  const a = dx * r.ux + dz * r.uz;
  const b = dx * (-r.uz) + dz * r.ux;
  return Math.abs(a) <= r.hu + margin && Math.abs(b) <= r.hv + margin;
}

// ===================== 드론 실기 코스 =====================
// 조종자 위치 (0,0). 앞쪽 +z. 조종자 기준 왼쪽 = +x, 오른쪽 = -x.
// H: 이착륙장, C: 중앙 기준점(E), A: 왼쪽, B: 오른쪽, EM: 비상착륙장
export function droneLayout(cls) {
  const big = cls === 1;
  const D = big ? 15 : 12.5;              // 좌우 기준점 거리
  const H = { x: 0, z: 15 };
  const C = { x: 0, z: 15 + D };
  return {
    H, C, D,
    A: { x: D, z: C.z }, B: { x: -D, z: C.z },
    EM: { x: 9, z: 12 },
    alt: 3, top: big ? 7.5 : 6,
    circleR: big ? 7.5 : 6,
    padR: 1.0,
  };
}

// 실기 항목 정의(연습용 단순화 버전). 각 step: kind arm|goto|yaw|land|disarm
export function droneItems(cls) {
  const L = droneLayout(cls);
  const a = L.alt;
  const P = (p, y) => [p.x, y, p.z];
  const items = [];
  items.push({ name: '이륙비행', limit: 60, start: 'ground_H', steps: [
    { kind: 'arm', text: '시동을 거세요 (시동 버튼)' },
    { kind: 'goto', text: `수직으로 ${a}m 까지 이륙 후 5초 정지`, target: P(L.H, a), hold: 5, heading: 0 },
  ] });
  items.push({ name: '공중 정지비행(호버링)', limit: 100, start: 'hover_H', steps: [
    { kind: 'goto', text: '중앙(E) 기준점으로 전진 후 5초 정지', target: P(L.C, a), hold: 5, heading: 0 },
    { kind: 'yaw', text: '기수를 왼쪽 90°로 돌려 5초 정지', heading: 90, hold: 5, target: P(L.C, a) },
    { kind: 'yaw', text: '기수를 오른쪽 90°로 돌려 5초 정지', heading: -90, hold: 5, target: P(L.C, a) },
    { kind: 'yaw', text: '기수를 정면으로 돌리세요', heading: 0, hold: 2, target: P(L.C, a) },
  ] });
  items.push({ name: '직진 및 후진 수평비행', limit: 100, start: 'hover_C', steps: [
    { kind: 'yaw', text: '기수를 A 지점(왼쪽)으로 향하세요', heading: 90, hold: 2, target: P(L.C, a) },
    { kind: 'goto', text: 'A 지점까지 직진 후 정지', target: P(L.A, a), hold: 3, heading: 90, strictHead: true },
    { kind: 'goto', text: '중앙(E)까지 후진 후 정지', target: P(L.C, a), hold: 3, heading: 90, strictHead: true },
    { kind: 'yaw', text: '기수를 정면으로 돌리세요', heading: 0, hold: 2, target: P(L.C, a) },
  ] });
  items.push({ name: '삼각비행', limit: 120, start: 'hover_C', steps: [
    { kind: 'goto', text: 'B 지점(오른쪽)으로 수평 이동 후 정지', target: P(L.B, a), hold: 3, heading: 0 },
    { kind: 'goto', text: `대각선으로 상승하여 중앙 ${L.top}m 상공으로`, target: P(L.C, L.top), hold: 2, heading: 0 },
    { kind: 'goto', text: '대각선으로 하강하여 A 지점(왼쪽)으로', target: P(L.A, a), hold: 3, heading: 0 },
    { kind: 'goto', text: '중앙(E)으로 수평 이동 후 정지', target: P(L.C, a), hold: 3, heading: 0 },
  ] });
  // 원주비행: 중앙(E)에서 시작해 앞쪽 원을 한 바퀴 (기수는 진행방향)
  const R = L.circleR; const cz = L.C.z + R;
  const circ = [];
  for (let k = 1; k <= 8; k++) {
    const ph = (Math.PI / 4) * k;
    const x = R * Math.sin(ph), z = cz - R * Math.cos(ph);
    const hd = 90 - (ph * 180 / Math.PI);
    circ.push({ kind: 'goto', text: `원주비행 ${k}/8 — 기수를 진행방향으로 유지`, target: [x, a, z], hold: 0, tol: 1.6, heading: k === 8 ? null : wrapDeg(hd), headTol: 35, circle: { cx: 0, cz, R } });
  }
  items.push({ name: '원주비행(러더턴)', limit: 120, start: 'hover_C', steps: [
    { kind: 'yaw', text: '기수를 왼쪽(진행방향)으로 돌리세요', heading: 90, hold: 1, target: P(L.C, a) },
    ...circ,
    { kind: 'yaw', text: '중앙(E)에서 기수를 정면으로 하고 정지', heading: 0, hold: 3, target: P(L.C, a) },
  ] });
  items.push({ name: '비상조작', limit: 60, start: 'hover_C', emergency: true, steps: [
    { kind: 'goto', text: '중앙(E) 고도 5m 까지 상승', target: P(L.C, 5), hold: 2, heading: 0 },
    { kind: 'land', text: '⚠ 비상! 비상착륙장으로 신속히 이동하여 착륙', pad: [L.EM.x, L.EM.z], radius: 1.5, timeLimit: 25 },
  ] });
  items.push({ name: '정상접근 및 착륙', limit: 90, start: 'hover_C', steps: [
    { kind: 'goto', text: '이착륙장(H) 상공 3m 로 접근 후 정지', target: P(L.H, a), hold: 3, heading: 0 },
    { kind: 'land', text: '수직으로 강하하여 이착륙장에 착륙', pad: [L.H.x, L.H.z], radius: L.padR },
  ] });
  items.push({ name: '측풍접근 및 착륙', limit: 110, start: 'hover_side', crosswind: true, steps: [
    { kind: 'goto', text: '측풍 대기 지점(오른쪽 8m)에서 기수 왼쪽 90°로 정지', target: [L.H.x - 8, a, L.H.z], hold: 3, heading: 90 },
    { kind: 'goto', text: '측풍을 받으며 이착륙장(H) 상공으로 접근', target: P(L.H, a), hold: 3, heading: 90, strictHead: true },
    { kind: 'land', text: '이착륙장에 착륙', pad: [L.H.x, L.H.z], radius: L.padR },
  ] });
  return { layout: L, items };
}

export function wrapDeg(d) { d = ((d + 180) % 360 + 360) % 360 - 180; return d; }
