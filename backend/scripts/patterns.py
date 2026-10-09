"""검색 종목 '비슷한 과거 패턴' 요청 처리 (GitHub Actions: 요청 즉시 신호 · 매시간 점검)

  python -m scripts.patterns            # 대기 중인 요청을 처리 (없으면 바로 끝)
"""
from __future__ import annotations

import logging
import sys
import time

from stockeye.config import load_config, data_dir
from stockeye.data.pit import PointInTimeData
from stockeye.data.store import DataStore

log = logging.getLogger("stockeye.patterns")


def main():
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    t0 = time.time()
    from stockeye.cloud.client import Supabase
    from stockeye.cloud.sync import DataSync
    from stockeye.cloud.patterns import process_pattern_requests, TABLE
    sb = Supabase()
    if not sb.select(TABLE, {"status": "eq.queued", "select": "id", "limit": "1"}):
        print("대기 중인 패턴 요청 없음 → 끝"); return
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    DataSync(store, sb).pull()
    pit = PointInTimeData.from_store(store)
    n = 0
    for _ in range(3):                    # 처리하는 동안 새로 들어온 요청까지 (최대 3번)
        k = process_pattern_requests(sb, pit)
        n += k
        if k == 0:
            break
    print(f"패턴 요청 {n}건 처리 ({(time.time() - t0) / 60:.1f}분)")


if __name__ == "__main__":
    main()
