// 휴대폰 조종기
(() => {
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k, d) { try { const v = localStorage.getItem('sim.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('sim.' + k, JSON.stringify(v)); } catch { /* 저장 불가 무시 */ } },
  };
  const cfg = { autoCenter: store.get('autoCenter', true), wheelRange: store.get('wheelRange', 540), stickMode: store.get('stickMode', 2) };

  const CFG = window.SIM_CONFIG;
  let peer = null, conn = null, scene = null, mode = 'practice', st = {};
  let room = new URLSearchParams(location.search).get('room') || store.get('room', '');
  let everConnected = false, retryT = 0, openT = 0;
  // ---------------- 통신 (PeerJS / WebRTC) ----------------
  function status(text, ok) { $('conn').textContent = text; $('dot').className = 'dot' + (ok ? ' on' : ''); }
  function ensurePeer(cb) {
    if (peer && !peer.destroyed && peer.open) return cb();
    if (peer && !peer.destroyed) { peer.once('open', cb); return; }
    peer = new Peer({ ...CFG.peer, config: { iceServers: CFG.iceServers }, debug: 0 });
    peer.on('open', cb);
    peer.on('disconnected', () => { setTimeout(() => { try { peer.reconnect(); } catch { /* 무시 */ } }, 1500); });
    peer.on('error', (e) => {
      if (e.type === 'peer-unavailable') {
        if (everConnected) { status(`방 ${room} · TV 화면 다시 찾는 중…`, false); scheduleRetry(2500); }
        else { askRoom('방 코드가 맞지 않거나 TV 화면이 꺼져 있습니다. TV의 코드를 다시 입력하세요'); }
      } else if (['network', 'server-error', 'socket-error', 'socket-closed'].includes(e.type)) {
        status('인터넷 연결을 확인하세요 — 재시도 중…', false);
        try { peer.destroy(); } catch { /* 무시 */ } peer = null; scheduleRetry(3000);
      }
    });
  }
  function scheduleRetry(ms) { clearTimeout(retryT); retryT = setTimeout(connect, ms); }
  function connect() {
    clearTimeout(retryT); clearTimeout(openT);
    if (!room) { askRoom('TV 화면에 보이는 4자리 방 코드를 입력하세요'); return; }
    status(`방 ${room} · 연결 중…`, false);
    ensurePeer(() => {
      try { conn && conn.close(); } catch { /* 무시 */ }
      const c = conn = peer.connect(CFG.idPrefix + room, { reliable: true, serialization: 'json' });
      clearTimeout(openT);
      const timer = openT = setTimeout(() => { if (c.open || conn !== c) return; try { c.close(); } catch { /* 무시 */ } if (conn === c) conn = null; if (everConnected) { status('연결이 오래 걸립니다 — 다시 시도 중…', false); scheduleRetry(500); } else askRoom('TV 화면을 찾지 못했습니다. 방 코드를 확인하고 다시 입력하세요 (TV와 휴대폰 모두 인터넷 연결 필요)'); }, 8000);
      c.on('open', () => { clearTimeout(timer); everConnected = true; store.set('room', room); $('roomBox').style.display = 'none'; status(`방 ${room} 연결됨 · TV 확인 중…`, true); send({ t: 'hello-phone' }); });
      c.on('data', (m) => { if (m && typeof m === 'object') onMsg(m); });
      c.on('close', () => { clearTimeout(timer); if (conn === c) { status(`방 ${room} · 연결 끊김 — 재연결 중…`, false); scheduleRetry(1500); } });
      c.on('error', () => { /* close 에서 처리 */ });
    });
  }
  function send(m) { if (conn && conn.open) { try { conn.send(m); } catch { /* 무시 */ } } }
  connect();

  function askRoom(msg) {
    $('conn').textContent = msg; $('roomBox').style.display = 'flex'; $('roomIn').value = room || '';
  }
  $('roomGo').onclick = () => {
    const v = $('roomIn').value.replace(/[^0-9]/g, '');
    if (v.length < 4) { toast('4자리 숫자를 입력하세요'); return; }
    room = v; everConnected = false; $('roomBox').style.display = 'none';
    connect();
  };
  function onMsg(m) {
    if (m.t === 'status') {
      status(`방 ${room} · TV 연결됨 — 시험을 선택하세요`, true);
    }
    if (m.t === 'scene') setScene(m);
    if (m.t === 'state') { st = m.d; render(); }
    if (m.t === 'instr') { $('cInstr').textContent = m.text; $('dInstr').textContent = m.text; }
    if (m.t === 'toast') toast(m.text);
    if (m.t === 'result') { toast(m.title); vib(m.ok ? [60, 60, 60, 60, 200] : [400]); }
    if (m.t === 'event') {
      if (m.kind === 'penalty') { vib([80, 50, 80]); flash('#ff5a52'); toast(m.text); }
      else if (m.kind === 'fail') { vib([350]); flash('#ff0000'); toast(m.text); }
      else if (m.kind === 'warn') { vib(60); flash('#ffb020'); }
    }
  }
  function vib(p) { try { navigator.vibrate && navigator.vibrate(p); } catch { /* 진동 미지원 */ } }
  let flashT; function flash(c) { const f = $('flash'); f.style.boxShadow = `inset 0 0 0 10px ${c}`; clearTimeout(flashT); flashT = setTimeout(() => f.style.boxShadow = 'inset 0 0 0 0 transparent', 350); }
  let toastT; function toast(t) { const el = $('ptoast'); el.textContent = t; el.style.opacity = 1; clearTimeout(toastT); toastT = setTimeout(() => el.style.opacity = 0, 2000); }

  // ---------------- 화면 전환 ----------------
  function show(id) { document.querySelectorAll('.screen').forEach(s => s.classList.toggle('on', s.id === id)); document.body.classList.toggle('playing', id !== 'menu'); }
  function setScene(m) {
    if (!m.kind) { scene = null; show('menu'); return; }
    scene = m;
    if (m.kind === 'car') { buildGears(m.manual); $('pClu').style.display = m.manual ? '' : 'none'; show('car'); }
    else { stickLabels(); show('drone'); }
    buildOverlay();
  }

  // 시작 메뉴
  document.querySelectorAll('#modeSeg button').forEach(b => b.onclick = () => {
    mode = b.dataset.mode; document.querySelectorAll('#modeSeg button').forEach(x => x.classList.toggle('sel', x === b));
  });
  document.querySelectorAll('#menu .grid button').forEach(b => b.onclick = () => {
    goFull();
    resetInputs();
    send({ t: 'start', kind: b.dataset.kind, variant: b.dataset.variant, mode });
  });
  function goFull() {
    const d = document.documentElement;
    try { const p = d.requestFullscreen ? d.requestFullscreen() : d.webkitRequestFullscreen && d.webkitRequestFullscreen(); p && p.then && p.then(() => screen.orientation && screen.orientation.lock && screen.orientation.lock('landscape').catch(() => {})).catch(() => {}); } catch { /* 전체화면 미지원 */ }
  }

  // 명령 버튼
  document.addEventListener('pointerdown', (e) => {
    const b = e.target.closest('[data-cmd]'); if (!b) return;
    e.preventDefault();
    send({ t: 'cmd', c: b.dataset.cmd, arg: b.dataset.arg });
    vib(15);
    if (b.hasAttribute('data-close')) $('overlay').classList.remove('on');
  });
  document.querySelectorAll('[data-open]').forEach(b => b.addEventListener('pointerdown', (e) => { e.preventDefault(); $('overlay').classList.add('on'); }));
  $('ovClose').onclick = () => $('overlay').classList.remove('on');
  $('ovFull').onclick = goFull;
  $('ovHome').onclick = () => { $('overlay').classList.remove('on'); send({ t: 'menu' }); scene = null; show('menu'); };

  function buildOverlay() {
    $('ovTitle').textContent = `${scene.variant} · ${scene.mode === 'exam' ? '시험 모드' : '연습 모드'}`;
    const J = $('jumps'); J.innerHTML = '';
    $('jumpTitle').textContent = scene.kind === 'car' ? '구간 바로가기 (연습 모드)' : '실기 항목 바로가기 (연습 모드)';
    (scene.jumps || []).forEach(j => {
      const b = document.createElement('button'); b.textContent = j.name;
      if (scene.mode === 'exam') b.disabled = true, b.style.opacity = .4;
      b.onclick = () => { send({ t: 'cmd', c: 'jump', arg: j.id }); $('overlay').classList.remove('on'); resetInputs(); };
      J.appendChild(b);
    });
    const S = $('settings'); S.innerHTML = '';
    const add = (label, fn) => { const b = document.createElement('button'); b.textContent = label(); b.onclick = () => { fn(); b.textContent = label(); }; S.appendChild(b); };
    if (scene.kind === 'car') {
      add(() => `핸들 자동복귀: ${cfg.autoCenter ? '켬' : '끔'}`, () => { cfg.autoCenter = !cfg.autoCenter; store.set('autoCenter', cfg.autoCenter); });
      add(() => `핸들 회전범위: ±${cfg.wheelRange / 2}°`, () => { cfg.wheelRange = cfg.wheelRange === 540 ? 900 : cfg.wheelRange === 900 ? 360 : 540; store.set('wheelRange', cfg.wheelRange); });
    } else {
      add(() => `조종 모드: Mode ${cfg.stickMode} ${cfg.stickMode === 2 ? '(왼쪽 스로틀)' : '(오른쪽 스로틀)'}`, () => { cfg.stickMode = cfg.stickMode === 2 ? 1 : 2; store.set('stickMode', cfg.stickMode); stickLabels(); });
    }
  }

  // ---------------- 자동차 ----------------
  const car = { wheel: 0, held: false, thr: 0, brk: 0, clu: 0 };
  function buildGears(manual) {
    const G = $('gearBox'); G.innerHTML = '';
    const list = manual ? ['1', '2', '3', 'N', 'R'] : ['P', 'R', 'N', 'D'];
    list.forEach(g => { const b = document.createElement('button'); b.textContent = g; b.dataset.cmd = 'gear'; b.dataset.arg = g; b.id = 'g' + g; G.appendChild(b); });
  }
  // 핸들
  (() => {
    const W = $('wheel'); let pid = null, last = 0;
    const ang = (e) => { const r = W.getBoundingClientRect(); return Math.atan2(e.clientY - (r.top + r.height / 2), e.clientX - (r.left + r.width / 2)); };
    let lastTap = 0;
    W.addEventListener('pointerdown', (e) => {
      e.preventDefault(); if (pid !== null) return;
      if (e.target.classList.contains('hub')) { const now = Date.now(); if (now - lastTap < 350) { car.wheel = 0; } lastTap = now; }
      pid = e.pointerId; try { W.setPointerCapture(pid); } catch { /* 무시 */ } last = ang(e); car.held = true;
    });
    W.addEventListener('pointermove', (e) => {
      if (e.pointerId !== pid) return;
      const a = ang(e); let d = a - last; if (d > Math.PI) d -= 2 * Math.PI; if (d < -Math.PI) d += 2 * Math.PI; last = a;
      const lim = cfg.wheelRange / 2;
      car.wheel = Math.max(-lim, Math.min(lim, car.wheel + d * 180 / Math.PI));
    });
    const up = (e) => { if (e.pointerId !== pid) return; pid = null; car.held = false; };
    W.addEventListener('pointerup', up); W.addEventListener('pointercancel', up);
  })();
  // 페달
  function pedal(el, key) {
    let pid = null; const fill = el.querySelector('.fill');
    const val = (e) => { const r = el.getBoundingClientRect(); return Math.max(0.15, Math.min(1, 0.15 + 0.85 * (e.clientY - r.top) / (r.height * 0.85))); };
    el.addEventListener('pointerdown', (e) => { e.preventDefault(); pid = e.pointerId; try { el.setPointerCapture(pid); } catch { /* 무시 */ } car[key] = val(e); });
    el.addEventListener('pointermove', (e) => { if (e.pointerId === pid) car[key] = val(e); });
    const up = (e) => { if (e.pointerId === pid) { pid = null; car[key] = 0; } };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    return () => { fill.style.height = (car[key] * 100) + '%'; };
  }
  const pedalDraw = [pedal($('pThr'), 'thr'), pedal($('pBrk'), 'brk'), pedal($('pClu'), 'clu')];

  // ---------------- 드론 스틱 ----------------
  const sticks = { L: { x: 0, y: 0 }, R: { x: 0, y: 0 } };
  function stick(el, S) {
    const knob = el.querySelector('.knob'); let pid = null;
    const set = (e) => {
      const r = el.getBoundingClientRect(); const half = r.width / 2 - 20;
      S.x = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / half));
      S.y = Math.max(-1, Math.min(1, -(e.clientY - (r.top + r.height / 2)) / half));
    };
    el.addEventListener('pointerdown', (e) => { e.preventDefault(); pid = e.pointerId; try { el.setPointerCapture(pid); } catch { /* 무시 */ } set(e); });
    el.addEventListener('pointermove', (e) => { if (e.pointerId === pid) set(e); });
    const up = (e) => { if (e.pointerId === pid) { pid = null; S.x = 0; S.y = 0; } };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    return () => { const r = el.clientWidth / 2 - 20; knob.style.left = `calc(50% + ${S.x * r}px)`; knob.style.top = `calc(50% - ${S.y * r}px)`; };
  }
  const stickDraw = [stick($('stickL'), sticks.L), stick($('stickR'), sticks.R)];
  function stickLabels() {
    const m2 = cfg.stickMode === 2;
    const L = m2 ? ['상승', '하강', '좌회전(기수)', '우회전(기수)'] : ['전진', '후진', '좌회전(기수)', '우회전(기수)'];
    const R = m2 ? ['전진', '후진', '좌이동', '우이동'] : ['상승', '하강', '좌이동', '우이동'];
    ['lT', 'lB', 'lL', 'lR'].forEach((id, i) => $(id).textContent = L[i]);
    ['rT', 'rB', 'rL', 'rR'].forEach((id, i) => $(id).textContent = R[i]);
  }
  function droneInput() {
    const dz = (v) => Math.abs(v) < 0.06 ? 0 : (v - Math.sign(v) * 0.06) / 0.94;
    const L = sticks.L, R = sticks.R;
    const yaw = dz(L.x), rol = dz(R.x);
    const thr = cfg.stickMode === 2 ? dz(L.y) : dz(R.y);
    const pit = cfg.stickMode === 2 ? dz(R.y) : dz(L.y);
    return { thr, yaw, pit, rol };
  }

  function resetInputs() { car.wheel = 0; car.thr = car.brk = car.clu = 0; sticks.L.x = sticks.L.y = sticks.R.x = sticks.R.y = 0; }

  // ---------------- 상태 표시 ----------------
  function render() {
    if (!scene) return;
    if (st.kind === 'car') {
      $('cSpd').textContent = Math.abs(st.kmh); $('cGear').textContent = st.gear; $('cScore').textContent = st.score;
      const on = (id, v, cls = 'on') => { const el = $(id); if (!el) return; el.classList.remove('on', 'amber', 'red'); if (v) el.classList.add(cls); };
      on('bEngine', st.engine); on('bBelt', st.belt); on('bPbrake', st.pbrake, 'red'); on('bHazard', st.hazard, 'amber');
      on('bSigL', st.signal === 'L', 'amber'); on('bSigR', st.signal === 'R', 'amber'); on('bLights', st.lights); on('bWiper', st.wiper);
      document.querySelectorAll('#gearBox button').forEach(b => b.classList.toggle('sel', b.dataset.arg === st.gear));
    } else if (st.kind === 'drone') {
      $('dAlt').textContent = st.alt.toFixed(1); $('dMode').textContent = `${st.fmode} · ${st.item}`;
      const a = $('bArm'); a.classList.toggle('on', st.armed); a.classList.toggle('red', !st.armed); a.innerHTML = st.armed ? '시동 ON<br>(착륙 후 끄기)' : '시동<br>(ARM)';
      $('bFmode').textContent = st.fmode === 'ATTI' ? 'ATTI 모드' : 'GPS 모드';
      $('bWind').innerHTML = `바람<br>${['없음', '약함', '강함'][st.wind]}`;
    }
  }

  // ---------------- 입력 전송 루프 (30Hz) ----------------
  let lastT = performance.now();
  function tick() {
    const now = performance.now(); const dt = Math.min(0.1, (now - lastT) / 1000); lastT = now;
    if (scene && scene.kind === 'car') {
      if (!car.held && cfg.autoCenter && Math.abs(st.kmh || 0) > 2) car.wheel *= Math.max(0, 1 - dt * Math.min(3, Math.abs(st.kmh) / 8));
      $('wheel').style.transform = `rotate(${car.wheel}deg)`;
      $('wheelVal').textContent = `${car.wheel.toFixed(0)}°`;
      pedalDraw.forEach(f => f());
      send({ t: 'in', d: { steer: car.wheel / (cfg.wheelRange / 2), thr: car.thr, brk: car.brk, clu: car.clu } });
    } else if (scene && scene.kind === 'drone') {
      stickDraw.forEach(f => f());
      send({ t: 'in', d: droneInput() });
    }
  }
  setInterval(tick, 33);
  stickLabels();
})();
