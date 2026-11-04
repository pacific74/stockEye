// 연결 설정 — 필요하면 이 파일만 고치면 됩니다.
// 기본: PeerJS 무료 공개 중계서버(연결 시작할 때만 사용) + Google STUN.
// 휴대폰 데이터(LTE/5G)처럼 망이 크게 다를 때 연결이 안 되면 TURN 서버를 추가하세요.
//   예) Metered.ca 무료 TURN 가입 후 아래 iceServers 에 추가
//   { urls: 'turn:서버주소:80', username: '사용자', credential: '비밀번호' }
window.SIM_CONFIG = {
  idPrefix: 'kdlts-sim-',          // 방 코드 앞에 붙는 고유 접두어(다른 사이트와 겹치지 않게)
  peer: {},                        // 비워두면 PeerJS 공개 서버(0.peerjs.com) 사용
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
  ],
};
// 테스트용: 주소 뒤에 ?peerhost=호스트:포트 를 붙이면 자체 PeerJS 서버 사용
(() => {
  const ph = new URLSearchParams(location.search).get('peerhost');
  if (ph) { const [host, port] = ph.split(':'); window.SIM_CONFIG.peer = { host, port: Number(port) || 9000, path: '/', secure: location.protocol === 'https:' }; }
})();
