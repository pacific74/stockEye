// TV 화면: 3D 렌더링 + HUD + 휴대폰 통신
import * as THREE from 'three';
import { CarSim } from './car.js';
import { DroneSim } from './drone.js';

const $ = (id) => document.getElementById(id);
const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
renderer.outputColorSpace = THREE.SRGBColorSpace;
function resize() {
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  if (sim) { sim.camera.aspect = window.innerWidth / window.innerHeight; sim.camera.updateProjectionMatrix(); }
}
window.addEventListener('resize', resize);

// ---------------- HUD ----------------
let toastTimer = 0, hintTimer = 0;
const hud = {
  currentInstr: '',
  instruction(text, kind = 'info') { this.currentInstr = text; const el = $('instr'); el.textContent = text; el.className = 'hud box ' + kind; send({ t: 'instr', text }); },
  hint(text) { const el = $('hint'); el.textContent = text; el.style.opacity = 1; hintTimer = 0.6; },
  toast(text) { const el = $('toast'); el.textContent = text; el.style.opacity = 1; toastTimer = 2.2; send({ t: 'toast', text }); },
  log(text, kind = 'info') {
    const el = document.createElement('div'); el.className = kind; el.textContent = text;
    const L = $('log'); L.prepend(el); while (L.children.length > 9) L.lastChild.remove();
  },
  clearLog() { $('log').innerHTML = ''; },
  showResult(title, html, ok) {
    const R = $('result'); R.style.display = 'flex';
    R.querySelector('h1').textContent = title; R.querySelector('h1').className = ok ? 'good' : 'bad';
    R.querySelector('.body').innerHTML = html;
    send({ t: 'result', title, ok });
  },
  hideResult() { $('result').style.display = 'none'; },
};

// ---------------- 통신 (PeerJS / WebRTC: 서버 없이 TV ↔ 휴대폰 직접 연결) ----------------
const CFG = window.SIM_CONFIG;
const conns = new Set();
let peer = null, phones = 0, idTries = 0;
let room = (() => { try { return sessionStorage.getItem('sim.room') || ''; } catch { return ''; } })();
const newCode = () => String(1000 + Math.floor(Math.random() * 9000));
function setNet(text, ok) { $('pstat').textContent = text; $('pdot').className = 'dot' + (ok ? ' on' : ''); }
function connect() {
  if (!room) room = newCode();
  setNet('연결 준비 중…', false);
  peer = new Peer(CFG.idPrefix + room, { ...CFG.peer, config: { iceServers: CFG.iceServers }, debug: 0 });
  peer.on('open', () => {
    idTries = 0;
    try { sessionStorage.setItem('sim.room', room); } catch { /* 무시 */ }
    $('code').textContent = room; showConnectInfo(); updatePhones();
  });
  peer.on('connection', (c) => {
    c.on('open', () => { conns.add(c); updatePhones(); if (sim) sendScene(); else c.send({ t: 'scene', kind: null }); });
    c.lastRx = performance.now();
    c.on('data', (m) => { c.lastRx = performance.now(); if (m && typeof m === 'object') onMessage(m); });
    const drop = () => { if (conns.delete(c)) updatePhones(); };
    c.on('close', drop); c.on('error', drop);
  });
  peer.on('disconnected', () => { setNet('중계서버 재연결 중…', false); setTimeout(() => { try { peer.reconnect(); } catch { /* 무시 */ } }, 1500); });
  peer.on('error', (e) => {
    if (e.type === 'unavailable-id') { try { peer.destroy(); } catch { /* 무시 */ } idTries++; if (idTries > 3) { room = newCode(); idTries = 0; } setTimeout(connect, idTries ? 2000 : 0); }
    else if (e.type === 'network' || e.type === 'server-error' || e.type === 'socket-error' || e.type === 'socket-closed') { setNet('인터넷/중계서버 연결 실패 — 재시도 중…', false); setTimeout(() => { try { peer.destroy(); } catch { /* 무시 */ } connect(); }, 3000); }
  });
}
function updatePhones() {
  phones = conns.size;
  setNet(phones ? `휴대폰 ${phones}대 연결됨 — 휴대폰에서 시험을 선택하세요` : '휴대폰 연결 대기 중', phones > 0);
  send({ t: 'status', phones, tvs: 1, room });
}
// 끊긴 휴대폰 정리(신호 5초 없음) + 중계서버 연결 유지
setInterval(() => {
  const now = performance.now();
  for (const c of [...conns]) if (now - (c.lastRx || 0) > 5000) { conns.delete(c); try { c.close(); } catch { /* 무시 */ } updatePhones(); }
  if (peer && !peer.destroyed && peer.disconnected) { try { peer.reconnect(); } catch { /* 무시 */ } }
}, 2000);
function send(m) { for (const c of conns) { if (c.open) { try { c.send(m); } catch { /* 무시 */ } } } }
connect();

function onMessage(m) {
  if (m.t === 'start') startSim(m.kind, m.variant, m.mode);
  if (m.t === 'menu') stopSim();
  if (m.t === 'hello-phone' && sim) sendScene();
  if (!sim) return;
  if (m.t === 'in') { sim.setInput(m.d); keyboardActive = false; }
  if (m.t === 'cmd') sim.command(m.c, m.arg);
}

// ---------------- 시뮬레이터 ----------------
let sim = null;
function startSim(kind, variant, mode) {
  if (sim && sim.scene) disposeScene(sim.scene);
  sim = kind === 'drone' ? new DroneSim(variant, mode, hud) : new CarSim(variant, mode, hud);
  sim.onEvent = (kind2, text) => send({ t: 'event', kind: kind2, text });
  $('connect').style.display = 'none';
  resize();
  sendScene();
}
function stopSim() {
  if (sim && sim.scene) disposeScene(sim.scene);
  sim = null; $('connect').style.display = 'flex'; hud.hideResult(); send({ t: 'scene', kind: null });
}
function sendScene() { if (sim) send({ t: 'scene', kind: sim.kind, variant: sim.variant, mode: sim.mode, jumps: sim.jumpList(), manual: sim.course ? sim.course.manual : false, layout: sim.kind === 'drone' ? sim.L : null }); }
function disposeScene(scene) {
  scene.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) { (Array.isArray(o.material) ? o.material : [o.material]).forEach(mt => { if (mt.map) mt.map.dispose(); mt.dispose(); }); } });
}

// ---------------- 키보드(PC 테스트용) ----------------
const keys = new Set(); let keyboardActive = false; let kbSteer = 0;
window.addEventListener('keydown', (e) => {
  if (!sim) {
    const list = [['car', '1종보통'], ['car', '2종보통'], ['car', '1종대형'], ['drone', '드론1종'], ['drone', '드론2종']];
    const i = Number(e.key) - 1; if (list[i]) startSim(list[i][0], list[i][1], e.shiftKey ? 'exam' : 'practice');
    return;
  }
  keys.add(e.code); keyboardActive = true;
  const k = e.code;
  if (k === 'KeyC') sim.command('camera');
  if (k === 'Escape') stopSim();
  if (k === 'Backspace') sim.command('restart');
  if (sim.kind === 'car') {
    const map = { KeyE: ['engine'], KeyB: ['belt'], Space: ['pbrake'], KeyZ: ['signal', 'L'], KeyX: ['signal', 'R'], KeyL: ['lights'], KeyW: ['wiper'], KeyH: ['hazard'],
      Digit1: ['gear', '1'], Digit2: ['gear', '2'], Digit3: ['gear', '3'], KeyR: ['gear', 'R'], KeyN: ['gear', 'N'], KeyP: ['gear', 'P'], KeyD: ['gear', 'D'] };
    if (map[k]) { e.preventDefault(); sim.command(...map[k]); }
  } else {
    if (k === 'KeyE') sim.command('arm');
    if (k === 'KeyM') sim.command('fmode');
    if (k === 'KeyV') sim.command('wind');
  }
});
window.addEventListener('keyup', (e) => keys.delete(e.code));
function keyboardInput(dt) {
  if (!sim || !keyboardActive) return;
  const k = (c) => keys.has(c) ? 1 : 0;
  if (sim.kind === 'car') {
    const dir = k('ArrowRight') - k('ArrowLeft');
    kbSteer = dir ? Math.max(-1, Math.min(1, kbSteer + dir * dt * 1.4)) : kbSteer * Math.max(0, 1 - dt * 1.5);
    sim.setInput({ steer: kbSteer, thr: k('ArrowUp') * 0.7, brk: k('ArrowDown'), clu: (k('ShiftLeft') || k('ShiftRight')) ? 1 : 0 });
  } else {
    sim.setInput({ thr: k('KeyW') - k('KeyS'), yaw: k('KeyD') - k('KeyA'), pit: k('ArrowUp') - k('ArrowDown'), rol: k('ArrowRight') - k('ArrowLeft') });
  }
}

// ---------------- 접속 안내 ----------------
function showConnectInfo() {
  const base = location.href.split('#')[0].split('?')[0].replace(/[^/]*$/, '');
  const qs = new URLSearchParams({ room });
  const ph = new URLSearchParams(location.search).get('peerhost'); if (ph) qs.set('peerhost', ph);
  const url = `${base}phone.html?${qs}`;
  $('url').textContent = url.replace(/^https?:\/\//, '');
  try { const q = qrcode(0, 'M'); q.addData(url); q.make(); $('qr').src = q.createDataURL(8, 2); } catch { /* QR 실패 시 주소만 표시 */ }
}
$('keys').textContent = 'PC 키보드 테스트: 숫자 1~5 시작(Shift=시험) · C 카메라 · Esc 메뉴';

// URL 파라미터로 바로 시작 (예: /tv?start=드론1종&mode=exam)
const qp = new URLSearchParams(location.search);
if (qp.get('start')) { const v = qp.get('start'); startSim(v.startsWith('드론') ? 'drone' : 'car', v, qp.get('mode') || 'practice'); }

// ---------------- 루프 ----------------
const clock = new THREE.Clock();
const mini = $('mini').querySelector('canvas'); const mctx = mini.getContext('2d');
let stateT = 0, hudT = 0;
function loop() {
  requestAnimationFrame(loop);
  const dt = Math.min(0.05, clock.getDelta());
  if (toastTimer > 0) { toastTimer -= dt; if (toastTimer <= 0) $('toast').style.opacity = 0; }
  if (hintTimer > 0) { hintTimer -= dt; if (hintTimer <= 0) $('hint').style.opacity = 0; }
  if (!sim) return;
  keyboardInput(dt);
  // 고정 스텝으로 물리 계산
  let rest = dt; while (rest > 1e-4) { const h = Math.min(rest, 1 / 120); sim.update(h); rest -= h; }
  renderer.render(sim.scene, sim.camera);
  hudT += dt;
  if (hudT > 0.1) { hudT = 0; $('panel').innerHTML = sim.hudPanel(); $('top').innerHTML = sim.hudTop(); sim.drawMinimap(mctx, mini.width, mini.height); }
  stateT += dt;
  if (stateT > (sim.kind === 'drone' ? 0.1 : 0.15)) { stateT = 0; send({ t: 'state', d: sim.phoneState() }); }
}
resize();
loop();
window.__sim = () => sim; // 디버그용
