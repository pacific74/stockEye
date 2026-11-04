"""동영상/음성 -> 글(대본) 변환 (PC에서 실행). faster-whisper 사용 (영상에서 소리를 직접 읽음, ffmpeg 설치 불필요)

  python -m scripts.transcribe "D:\\stockPrj\\test\\강의.mp4"             # 기본 모델 small
  python -m scripts.transcribe "D:\\stockPrj\\test\\강의.mp4" --model medium   # 더 정확, 더 느림
결과: 같은 폴더에 <파일명>.txt (시간표시 포함) 와 <파일명>.srt
처음 한 번 모델을 내려받음 (small 약 500MB).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def ts(sec: float, srt: bool = False) -> str:
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{int((sec % 1) * 1000):03d}" if srt else f"{h:02d}:{m:02d}:{s:02d}"


def decode(path: str):
    """영상/음성 -> 16kHz 모노 float32 (PyAV 를 직접 사용: faster-whisper 내부 디코더와 av 버전 충돌 피함)"""
    import av
    import numpy as np
    out = []
    with av.open(path) as c:
        st = c.streams.audio[0]
        rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for fr in c.decode(st):
            for f in rs.resample(fr) or []:
                out.append(f.to_ndarray().reshape(-1))
        for f in rs.resample(None) or []:
            out.append(f.to_ndarray().reshape(-1))
    return np.concatenate(out).astype("float32") / 32768.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--model", default="small", help="tiny/base/small/medium/large-v3")
    ap.add_argument("--lang", default="ko")
    a = ap.parse_args()
    src = Path(a.path)
    if not src.exists():
        sys.exit(f"파일이 없습니다: {src}")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper 가 없습니다. 먼저:  pip install faster-whisper")
    print(f"모델 {a.model} 준비 (처음엔 내려받는 중...)", flush=True)
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    print("소리 읽는 중...", flush=True)
    audio = decode(str(src))
    segs, info = model.transcribe(audio, language=a.lang, vad_filter=True, beam_size=5)
    total = info.duration or 0
    print(f"길이 {total / 60:.1f}분 — 변환 시작", flush=True)
    t0 = time.time()
    txt, srt = [], []
    for i, s in enumerate(segs, 1):
        txt.append(f"[{ts(s.start)}] {s.text.strip()}")
        srt.append(f"{i}\n{ts(s.start, True)} --> {ts(s.end, True)}\n{s.text.strip()}\n")
        if i % 20 == 0:
            done = s.end / total * 100 if total else 0
            print(f"  {ts(s.end)} / {ts(total)}  ({done:.0f}%)  경과 {(time.time() - t0) / 60:.1f}분", flush=True)
    src.with_suffix(".txt").write_text("\n".join(txt), encoding="utf-8")
    src.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"끝 ({(time.time() - t0) / 60:.1f}분) -> {src.with_suffix('.txt')}")


if __name__ == "__main__":
    main()
