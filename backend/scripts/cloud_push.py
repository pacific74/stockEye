"""PC 의 원본 데이터(5년치 parquet)를 Supabase Storage 로 올리기 / 받기.

  python -m scripts.cloud_push            # 처음 한 번: PC 데이터를 클라우드로 (바뀐 조각만)
  python -m scripts.cloud_push --force    # 전부 다시 올리기
  python -m scripts.cloud_push --pull     # 클라우드 → PC (PC 에서 백테스트 등을 할 때)

필요: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
from __future__ import annotations

import argparse
import logging
import sys

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore
from stockeye.cloud.sync import DataSync


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    store = DataStore(data_dir(load_config()))
    sync = DataSync(store)
    if args.pull:
        changed = sync.pull()
        print(f"받기 완료: {', '.join(changed) or '바뀐 것 없음'} → {store.root}")
        return
    if not store.path("ohlcv").exists():
        raise SystemExit(f"{store.root} 에 ohlcv.parquet 가 없습니다")
    up = sync.push(force=args.force)
    print(f"올리기 완료: {len(up)}개 조각 → Supabase Storage 'stockeye/data/'")


if __name__ == "__main__":
    main()
