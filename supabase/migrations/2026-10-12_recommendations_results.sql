-- ============================================================
-- StockEye 스키마 변경분 (2026-10-12 · 추천 기록 결과 칸)
--   저녁 배치가 매일 채움 → 앱 '검증 > 추천주' 탭 (일별 추천주 결과 · 승률·손익 통계)
--   2026-10-12_recommendations.sql 다음에 실행. 여러 번 실행해도 안전
-- ============================================================
alter table public.recommendations
  add column if not exists res_status   text,         -- 1차 목표 · 2차 목표 · 3차 목표 · 손절 · 기간 만료 · 미체결 · 매수 대기 · 보유중 …
  add column if not exists res_done     boolean,      -- 결과가 끝났나 (20거래일 지남 · 손절 · 3차 목표 · 장중 탭 결과 나옴)
  add column if not exists res_pnl      numeric,      -- 손익 % (비용 0.25% 뺌, 산 금액 기준). 진행중이면 마지막 종가 평가
  add column if not exists res_filled   numeric,      -- 산 비중 % (1·2·3차 매수구간 중 체결된 비중 합)
  add column if not exists res_fill_day int,          -- 처음 산 날 (추천 다음 날 = 1)
  add column if not exists res_days     int,          -- 지난 거래일 수
  add column if not exists res_d_t1     int,          -- 1차 목표 처음 닿은 날
  add column if not exists res_d_t2     int,
  add column if not exists res_d_t3     int,
  add column if not exists res_d_stop   int,          -- 손절 날
  add column if not exists res_max_up   numeric,      -- 매수가 대비 최고가 %
  add column if not exists res_max_dn   numeric,      -- 매수가 대비 최저가 %
  add column if not exists res_last     numeric,      -- 마지막 종가
  add column if not exists res_updated  timestamptz;
create index if not exists recommendations_open on public.recommendations (rec_date) where res_done is not true;
