// 휴대폰 조종기
(() => {
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k, d) { try { const v = localStorage.getItem('sim.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('sim.' + k, JSON.stringify(v)); } catch { /* 저장 불가 무시 */ } },
  };
  const cfg = { autoCenter: store.get('autoCenter', true), wheelRange: store.get('wheelRange', 540), stickMode: 2 };

  const CFG = window.SIM_CONFIG;
  let peer = null, conn = null, scene = null, mode = 'practice', st = {};
  let room = new URLSearchParams(location.search).get('room') || store.get('room', '');
  let everConnected = false, retryT = 0, openT = 0, lastRx = 0, missCount = 0, linkUp = false;
  // ---------------- 통신 (PeerJS / WebRTC) ----------------
  function status(text, ok) {
    $('conn').textContent = text; $('dot').className = 'dot' + (ok ? ' on' : '');
    linkUp = !!ok;
    const nb = $('netBanner'); if (nb) { nb.textContent = text + '  ↻ 눌러서 재연결'; nb.style.display = ok ? 'none' : 'block'; }
  }
  function freshPeer() { try { peer && peer.destroy(); } catch { /* 무시 */ } peer = null; }
  function ensurePeer(cb) {
    if (peer && !peer.destroyed && peer.open && !peer.disconnected) return cb();
    if (peer && (peer.destroyed || peer.disconnected)) freshPeer();   // 화면 꺼짐 등으로 끊긴 연결은 새로 만든다
    if (peer) { peer.once('open', cb); return; }
    const p = peer = new Peer({ ...CFG.peer, config: { iceServers: CFG.iceServers }, debug: 0 });
    p.on('open', cb);
    p.on('disconnected', () => { if (peer === p) { freshPeer(); scheduleRetry(1000); } });
    p.on('error', (e) => {
      if (peer !== p) return;
      if (e.type === 'peer-unavailable') {
        missCount++;
        if (everConnected && missCount < 8) { status(`방 ${room} · TV 화면 다시 찾는 중… (${missCount})`, false); scheduleRetry(2500); }
        else { everConnected = false; askRoom('TV 화면을 찾지 못했습니다. TV 화면의 방 코드를 확인해서 입력하세요 (TV를 새로 열었으면 코드가 바뀌었을 수 있어요)'); }
      } else {
        status('인터넷 연결을 확인하세요 — 재시도 중…', false);
        freshPeer(); scheduleRetry(3000);
      }
    });
  }
  function scheduleRetry(ms) { clearTimeout(retryT); retryT = setTimeout(connect, ms); }
  function dropConn() { const c = conn; conn = null; try { c && c.close(); } catch { /* 무시 */ } }
  function connect() {
    clearTimeout(retryT); clearTimeout(openT);
    if (!room) { askRoom('TV 화면에 보이는 4자리 방 코드를 입력하세요'); return; }
    status(`방 ${room} · 연결 중…`, false);
    ensurePeer(() => {
      dropConn();
      const c = conn = peer.connect(CFG.idPrefix + room, { reliable: true, serialization: 'json' });
      clearTimeout(openT);
      openT = setTimeout(() => {
        if (c.open || conn !== c) return;
        dropConn();
        if (everConnected) { status('연결이 오래 걸립니다 — 다시 시도 중…', false); freshPeer(); scheduleRetry(500); }
        else askRoom('TV 화면을 찾지 못했습니다. 방 코드를 확인하고 다시 입력하세요 (TV와 휴대폰 모두 인터넷 연결 필요)');
      }, 9000);
      c.on('open', () => {
        clearTimeout(openT); everConnected = true; missCount = 0; lastRx = performance.now();
        store.set('room', room); $('roomBox').style.display = 'none';
        status(`방 ${room} 연결됨 · TV 확인 중…`, true); send({ t: 'hello-phone' });
      });
      c.on('data', (m) => { lastRx = performance.now(); if (m && typeof m === 'object') onMsg(m); });
      c.on('close', () => { if (conn === c) { conn = null; status(`방 ${room} · 연결 끊김 — 재연결 중…`, false); scheduleRetry(1200); } });
      c.on('error', () => { /* close 에서 처리 */ });
    });
  }
  function send(m) { if (conn && conn.open) { try { conn.send(m); } catch { /* 무시 */ } } }
  // 화면을 껐다 켜거나 다른 앱에 갔다 오면: 연결 상태를 확인하고 바로 다시 붙는다
  function wake() {
    if (!room) return;
    if (conn && conn.open && performance.now() - lastRx < 2500) { send({ t: 'hello-phone' }); return; }
    dropConn(); freshPeer(); missCount = 0; connect();
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') setTimeout(wake, 300); });
  window.addEventListener('pageshow', (e) => { if (e.persisted) setTimeout(wake, 300); });
  window.addEventListener('online', () => setTimeout(wake, 500));
  // TV 신호가 4초 넘게 안 오면 끊긴 것으로 보고 다시 연결
  setInterval(() => {
    if (document.visibilityState !== 'visible') return;
    if (conn && conn.open && performance.now() - lastRx > 4000) { status(`방 ${room} · 신호 없음 — 재연결 중…`, false); dropConn(); freshPeer(); connect(); }
  }, 1000);
  $('netBanner').addEventListener('pointerdown', () => wake());
  connect();

  function askRoom(msg) {
    $('conn').textContent = msg; $('roomBox').style.display = 'flex'; $('roomIn').value = room || '';
    show('menu');
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
      const info = document.createElement('div'); info.style.cssText = 'grid-column:1/-1;font-size:13px;color:#8b98a5;line-height:1.6';
      info.innerHTML = '<b style="color:#fff">Mode 2</b> (국내 드론 실기시험 표준)<br>왼쪽 스틱: 위·아래 = 상승·하강, 좌·우 = 기수 회전<br>오른쪽 스틱: 위·아래 = 전진·후진, 좌·우 = 좌·우 이동';
      S.appendChild(info);
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
      const r = el.getBoundingClientRect(); const half = r.width * 0.33;
      S.x = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / half));
      S.y = Math.max(-1, Math.min(1, -(e.clientY - (r.top + r.height / 2)) / half));
    };
    el.addEventListener('pointerdown', (e) => { e.preventDefault(); pid = e.pointerId; try { el.setPointerCapture(pid); } catch { /* 무시 */ } set(e); });
    el.addEventListener('pointermove', (e) => { if (e.pointerId === pid) set(e); });
    const up = (e) => { if (e.pointerId === pid) { pid = null; S.x = 0; S.y = 0; } };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    return () => { const r = el.clientWidth * 0.33; knob.style.left = `calc(50% + ${S.x * r}px)`; knob.style.top = `calc(50% - ${S.y * r}px)`; };
  }
  const stickDraw = [stick($('stickL'), sticks.L), stick($('stickR'), sticks.R)];
  function stickLabels() { /* Mode 2 고정 — 라벨은 HTML 에 있음 */ }
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
    if (st.instr) { if ($('dInstr').textContent !== st.instr) $('dInstr').textContent = st.instr; if ($('cInstr').textContent !== st.instr) $('cInstr').textContent = st.instr; }
    if (st.kind === 'car') {
      $('cSpd').textContent = Math.abs(st.kmh); $('cGear').textContent = st.gear; $('cScore').textContent = st.score;
      const on = (id, v, cls = 'on') => { const el = $(id); if (!el) return; el.classList.remove('on', 'amber', 'red'); if (v) el.classList.add(cls); };
      on('bEngine', st.engine); on('bBelt', st.belt); on('bPbrake', st.pbrake, 'red'); on('bHazard', st.hazard, 'amber');
      on('bSigL', st.signal === 'L', 'amber'); on('bSigR', st.signal === 'R', 'amber'); on('bLights', st.lights); on('bWiper', st.wiper);
      document.querySelectorAll('#gearBox button').forEach(b => b.classList.toggle('sel', b.dataset.arg === st.gear));
    } else if (st.kind === 'drone') {
      $('dAlt').textContent = st.alt.toFixed(1);
      $('lHs').textContent = (st.hs ?? 0).toFixed(1); $('lVs').textContent = (st.vs ?? 0).toFixed(1);
      $('lDist').textContent = (st.dist ?? 0).toFixed(1); $('lHd').textContent = Math.round(st.hd ?? 0);
      $('lMode').textContent = st.fmode === 'ATTI' ? 'ATTI' : 'GPS';
      const la = $('lArm'); la.textContent = st.armed ? '모터 ON' : '모터 OFF'; la.className = st.armed ? 'on' : 'off';
      $('lWind').textContent = `바람 ${['없음', '약함', '강함'][st.wind]} ${(st.ws ?? 0).toFixed(1)}m/s`;
      $('lItem').textContent = st.item || '';
      const bat = Math.round(st.bat ?? 100); const lb = $('lBat'); lb.textContent = `🔋 ${bat}%`; lb.style.color = bat < 30 ? '#ff7a72' : '#4be08f';
      ['led1', 'led2', 'led3', 'led4'].forEach((id, i) => { $(id).className = bat > i * 25 ? (bat < 30 ? 'low' : 'on') : ''; });
      const a = $('bArm'); a.classList.toggle('armed', st.armed);
      $('bFmode').classList.toggle('hot', st.fmode !== 'ATTI'); $('bFmode').firstChild.textContent = st.fmode === 'ATTI' ? 'A' : 'G';
      $('bWind').classList.toggle('hot', st.wind > 0);
      if (st.results) $('lChips').innerHTML = st.results.map((r, i) => `<span class="${r || (i === st.idx ? 'cur' : '')}">${i + 1}</span>`).join('');
      const d = st.dev;
      $('lDev').innerHTML = !d ? '' : d.land ? `패드 중심까지 <b class="${d.dh <= d.tol ? 'good' : 'bad'}">${d.dh.toFixed(1)}m</b> (허용 ${d.tol}m)`
        : `목표 오차 수평 <b class="${d.dh <= d.tol ? 'good' : 'bad'}">${d.dh.toFixed(1)}m</b> · 고도 <b class="${d.dv <= 0.8 ? 'good' : 'bad'}">${d.dv.toFixed(1)}m</b>`;
      drawLcdMap();
    }
  }

  // 액정 미니맵 (위에서 본 비행장, 조종자 아래쪽)
  function drawLcdMap() {
    const cv = $('lMap'); const L = scene && scene.layout; if (!cv || !L || !L.field) return;
    const dpr = window.devicePixelRatio || 1;
    const W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr);
    if (!W || !H) return;
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    const g = cv.getContext('2d'); g.clearRect(0, 0, W, H);
    // 지도는 드론 근처를 확대 (시험장 35×80m 전체가 길쭉해서)
    const F = L.field;
    const viewLen = 45, sc = Math.min((W - 8) / F.w, (H - 8) / viewLen);
    const cz = Math.max(viewLen / 2 - 2, Math.min(F.len - viewLen / 2 + 2, (st.z ?? L.A.z) + 6));
    const X = x => W / 2 - x * sc, Y = z => H / 2 + (cz - z) * sc;
    g.fillStyle = 'rgba(90,150,70,.45)'; g.fillRect(X(F.w / 2), Y(F.len), F.w * sc, F.len * sc);
    g.strokeStyle = 'rgba(255,255,255,.55)'; g.lineWidth = dpr; g.strokeRect(X(F.w / 2), Y(F.len), F.w * sc, F.len * sc);
    g.strokeStyle = 'rgba(255,255,255,.8)'; g.beginPath(); g.arc(X(L.A.x), Y(L.A.z), L.R * sc, 0, 7); g.stroke();
    const fs = Math.max(10 * dpr, sc * 1.3);
    g.font = `bold ${fs}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
    const sq = (p, c, t) => { const k = Math.max(5 * dpr, sc * 1.0); g.fillStyle = c; g.fillRect(X(p.x) - k, Y(p.z) - k, k * 2, k * 2); g.fillStyle = '#fff'; g.fillText(t, X(p.x), Y(p.z) + 1); };
    const tri = (p, t) => { const k = Math.max(5 * dpr, sc * 0.9); g.fillStyle = '#ff3b30'; g.beginPath(); g.moveTo(X(p.x), Y(p.z) - k); g.lineTo(X(p.x) + k, Y(p.z) + k * 0.8); g.lineTo(X(p.x) - k, Y(p.z) + k * 0.8); g.fill(); g.fillStyle = '#fff'; g.fillText(t, X(p.x), Y(p.z) - k * 1.9); };
    sq(L.P, '#2aa7e6', 'P'); sq(L.H, '#1f3fd1', 'H'); sq(L.F, '#3f5f1f', 'F');
    for (const k of ['A', 'B', 'C', 'D', 'E']) tri(L[k], k);
    if (st.tgt) { g.strokeStyle = '#00ffaa'; g.lineWidth = 2 * dpr; g.beginPath(); g.arc(X(st.tgt[0]), Y(st.tgt[1]), Math.max(6 * dpr, sc * 1.2), 0, 7); g.stroke(); }
    if (st.x != null) {
      g.save(); g.translate(X(st.x), Y(st.z)); g.rotate(-(st.hd || 0) * Math.PI / 180);
      const k = Math.max(8 * dpr, sc * 1.4);
      g.fillStyle = '#ffd60a'; g.strokeStyle = '#000'; g.lineWidth = dpr;
      g.beginPath(); g.moveTo(0, -k); g.lineTo(k * 0.7, k * 0.8); g.lineTo(0, k * 0.4); g.lineTo(-k * 0.7, k * 0.8); g.closePath(); g.fill(); g.stroke(); g.restore();
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
    } else if (now - (tick.ping || 0) > 1000) { tick.ping = now; send({ t: 'ping' }); }
  }
  setInterval(tick, 33);
  stickLabels();
})();
