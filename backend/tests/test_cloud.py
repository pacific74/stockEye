"""클라우드 동기화 (가짜 Storage 로) — 연도별 분할 · 바뀐 조각만 올리기 · 받아서 그대로 복원."""
import pandas as pd

from stockeye.cloud.sync import DataSync
from stockeye.data.store import DataStore
from stockeye.data.sources.synthetic import generate


class FakeSB:
    def __init__(self):
        self.files, self.uploads = {}, []

    def upload(self, path, data, content_type="application/octet-stream"):
        self.files[path] = data
        self.uploads.append(path)

    def download(self, path):
        return self.files.get(path)


def test_push_pull_roundtrip(tmp_path):
    a = DataStore(tmp_path / "a")
    for k, v in generate(n_stocks=15, start="2024-11-01", end="2025-02-28").items():
        a.save(k, v)
    sb = FakeSB()
    up = DataSync(a, sb).push()
    assert "data/ohlcv/2024.parquet" in up and "data/ohlcv/2025.parquet" in up and "data/listing.parquet" in up
    sb.uploads.clear()
    assert DataSync(a, sb).push() == []                     # 바뀐 게 없으면 안 올림

    b = DataStore(tmp_path / "b")
    changed = DataSync(b, sb).pull()
    assert "ohlcv" in changed
    key = ["date", "code"]
    pd.testing.assert_frame_equal(a.load("ohlcv").sort_values(key).reset_index(drop=True),
                                  b.load("ohlcv").sort_values(key).reset_index(drop=True))
    assert DataSync(b, sb).pull() == []                     # 이미 같으면 다시 안 받음

    # 2025년 하루치만 바뀌면 2025 조각 + manifest 만 올라감
    oh = b.load("ohlcv")
    oh.loc[oh.index[-1], "close"] += 1
    b.save("ohlcv", oh)
    sb.uploads.clear()
    up = DataSync(b, sb).push()
    assert up == ["data/ohlcv/2025.parquet"]
