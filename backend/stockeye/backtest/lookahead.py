"""'미래를 보지 않았는지' 자동 검사 (Look-ahead Audit).

백테스트 결과가 좋을수록 먼저 의심해야 한다. 이 모듈은 4가지를 검사한다.

  1. 지표 인과성 (Truncation test)
     임의의 날짜 D를 골라, 'D까지만 있는 데이터'로 다시 계산한 지표와
     '전체 데이터'로 미리 계산한 지표의 D일 값이 완전히 같은지 비교.
     → 다르면 어떤 지표가 D 이후 데이터를 썼다는 뜻.

  2. 미래 오염 (Poison test)
     D 이후 데이터를 무작위 쓰레기 값으로 바꿔도 D일의 신호가 그대로인지 확인.

  3. 신호 동일성
     전략이 D일에 낸 매수 신호 목록이 1·2 조건에서 동일한지 확인.

  4. 체결 순서 / 코드 검사
     모든 거래가 '신호일 < 매수일 ≤ 매도일' 인지,
     소스 코드에 shift(-n), center=True, bfill 같은 미래참조 패턴이 없는지.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.pit import PointInTimeData, at, DECISION_TIME
from ..indicators import compute_features

FEATURE_COLS_SKIP = {"code"}
# 미래 가격을 일부러 쓰는 '성과 측정 전용' 파일 (점수·선정·매매 결정에는 쓰지 않음) — 늘릴 때는 신중히
OUTCOME_ONLY = {"lookahead.py", "v3_outcome.py", "score_power.py"}
BAD_PATTERNS = [
    (re.compile(r"\.shift\(\s*-\s*\d"), "shift(음수) → 미래 값을 당겨옴"),
    (re.compile(r"center\s*=\s*True"), "rolling(center=True) → 미래 구간 포함"),
    (re.compile(r"\.bfill\(|fillna\([^)]*method\s*=\s*['\"](bfill|backfill)"), "bfill → 미래 값으로 과거를 채움"),
]


def _code_lines(py: Path):
    """주석·문자열(docstring)을 제외한 '실행 코드'만 줄 단위로 돌려준다."""
    import io
    import tokenize
    lines: dict[int, list[str]] = {}
    with open(py, encoding="utf-8") as f:
        for tok in tokenize.generate_tokens(io.StringIO(f.read()).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
                            tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            lines.setdefault(tok.start[0], []).append(tok.string)
    return [(ln, "".join(toks)) for ln, toks in sorted(lines.items())]


@dataclass
class AuditReport:
    passed: bool = True
    checks: list = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = ""):
        self.checks.append({"check": name, "passed": bool(ok), "detail": detail})
        self.passed &= bool(ok)

    def to_dict(self):
        return {"passed": self.passed, "checks": self.checks}

    def __str__(self):
        lines = [f"미래참조 감사: {'통과 ✅' if self.passed else '실패 ❌'}"]
        for c in self.checks:
            lines.append(f"  {'✓' if c['passed'] else '✗'} {c['check']}  {c['detail']}")
        return "\n".join(lines)


def _truncate(data: PointInTimeData, d: pd.Timestamp, poison: bool, rng) -> PointInTimeData:
    def cut(df):
        if df.empty:
            return df
        if not poison:
            return df[df["date"] <= d]
        df = df.copy()
        fut = df["date"] > d
        num = [c for c in df.columns if c not in ("date", "code") and pd.api.types.is_numeric_dtype(df[c])]
        for c in num:
            df[c] = df[c].astype(float)
            if c == "chg_pct":
                df.loc[fut, c] = rng.uniform(-29, 29, fut.sum())
            else:   # 원래 값의 0.3~3배 무작위 → 미래가 완전히 달라짐
                df.loc[fut, c] = df.loc[fut, c] * rng.uniform(0.3, 3.0, fut.sum())
        return df
    return PointInTimeData(cut(data.ohlcv), cut(data.flows), cut(data.fund), data.disc, cut(data.index), data.listing)


def _feat_equal(a: pd.DataFrame, b: pd.DataFrame) -> tuple[bool, str]:
    cols = [c for c in a.columns if c in b.columns and c not in FEATURE_COLS_SKIP]
    a, b = a[cols].sort_index(), b.reindex(a.index)[cols]
    bad = []
    for c in cols:
        x, y = a[c].astype(float).to_numpy(), b[c].astype(float).to_numpy()
        same = np.isclose(x, y, rtol=1e-6, atol=1e-6, equal_nan=True)
        if not same.all():
            bad.append(c)
    return (not bad), (", ".join(bad[:8]) if bad else "")


def audit(data: PointInTimeData, features: pd.DataFrame, strategy=None, trades=None,
          n_dates: int = 6, n_codes: int = 40, feature_fn=compute_features, seed: int = 0,
          src_dir: str | Path | None = None) -> AuditReport:
    rng = np.random.default_rng(seed)
    rep = AuditReport()
    dates = features.index.get_level_values("date").unique().sort_values()
    # 지표가 충분히 쌓인 뒤 ~ 끝 직전 구간에서 표본 추출
    pool = dates[min(130, len(dates) // 3): len(dates) - 5]
    sample = sorted(rng.choice(pool, size=min(n_dates, len(pool)), replace=False))
    codes_all = features.index.get_level_values("code").unique()
    codes = list(rng.choice(codes_all, size=min(n_codes, len(codes_all)), replace=False))

    def sub(d_):
        return d_[d_["code"].isin(codes)] if not d_.empty else d_

    small = PointInTimeData(sub(data.ohlcv), sub(data.flows), sub(data.fund), data.disc, data.index, data.listing)

    trunc_ok, poison_ok, sig_ok = True, True, True
    details = []
    for d in sample:
        d = pd.Timestamp(d)
        full_x = features.xs(d, level="date")
        full_x = full_x[full_x.index.isin(codes)]
        for poison in (False, True):
            td = _truncate(small, d, poison, rng)
            f2 = feature_fn(td.ohlcv, td.flows, td.fund)
            x2 = f2.xs(d, level="date")
            ok, cols = _feat_equal(full_x, x2)
            if not ok:
                details.append(f"{d.date()} {'오염' if poison else '절단'}: {cols}")
                if poison:
                    poison_ok = False
                else:
                    trunc_ok = False
            if strategy is not None and poison:
                view_full = data.view(at(d, DECISION_TIME))
                view_td = td.view(at(d, DECISION_TIME))
                s1 = [s["code"] for s in strategy.signals(full_x, view_full)]
                s2 = [s["code"] for s in strategy.signals(x2, view_td)]
                if s1 != s2:
                    sig_ok = False
                    details.append(f"{d.date()} 신호 불일치: {s1[:5]} vs {s2[:5]}")

    sd = ", ".join(str(pd.Timestamp(s).date()) for s in sample)
    rep.add("지표 인과성 (데이터 절단 비교)", trunc_ok, f"표본일 {sd}, {len(codes)}종목" + ("" if trunc_ok else f" | 문제 지표: {details}"))
    rep.add("미래 오염 테스트 (D 이후 값을 쓰레기로 교체)", poison_ok, "" if poison_ok else str(details))
    if strategy is not None:
        rep.add("신호 동일성", sig_ok, "" if sig_ok else str(details))

    if trades is not None:
        bad = [t for t in trades if not (pd.Timestamp(t.signal_date) < pd.Timestamp(t.entry_date) <= pd.Timestamp(t.exit_date))]
        rep.add("체결 순서 (신호일 < 매수일 ≤ 매도일)", not bad, f"{len(trades)}건 검사" + (f", 위반 {len(bad)}건" if bad else ""))

    src = Path(src_dir) if src_dir else Path(__file__).resolve().parent.parent
    hits = []
    for py in src.rglob("*.py"):
        if py.name in OUTCOME_ONLY:      # 성과 '채점' 전용 모듈 (결정 코드에서 쓰지 않음)
            continue
        for ln, code_part in _code_lines(py):
            for pat, why in BAD_PATTERNS:
                if pat.search(code_part):
                    hits.append(f"{py.name}:{ln} {why}")
    rep.add("소스 코드 미래참조 패턴 검사", not hits, "; ".join(hits[:5]))
    return rep
