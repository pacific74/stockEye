-- ============================================================
-- StockEye 스키마 변경분 (2026-10-12 · 추천 기록)
--   내용: 관심 목록에 나온 종목을 '그때 계획 그대로' 영구 보관 → 나중에 실제 결과와 맞춰 검증
--     - 저녁 배치: V3 · 유망주 · 상승초기 · 추세전환 · 상파 목록 전부
--     - 장중: 당일단타 '진입 조건 충족' · 종가배팅 '매수 후보' · 상한가포착 '매수 검토' 가 처음 나온 때 (PC·종목찾기)
--     - 같은 추천일 + 구분 + 종목은 하루 첫 기록만 (나중 것은 무시)
--     - 여러 구분에 겹쳐 추천되면 구분마다 따로 저장 → recommendation_overlaps 뷰로 한 종목 한 줄 (겹친 구분 전부)
--   candidates 표는 60일만 남고 같은 날 다시 돌리면 덮어써서 검증용으로 따로 둠
--   읽기: 승인된 사용자 · 쓰기: 배치(service_role)만. 여러 번 실행해도 안전
-- ============================================================

create table if not exists public.recommendations (
  rec_date     date not null,             -- 추천일
  kind         text not null,             -- v3 · nextday(유망주) · early(상승초기) · reversal(추세전환) · uplimit(상파)
                                          -- · daytrade(당일단타) · closingbet(종가배팅) · limitcatch(상한가포착)
  code         text not null,
  name         text,
  rec_time     text,                      -- '마감'(저녁 배치) 또는 장중 처음 나온 시각 HH:MM
  source       text,                      -- daily · pc · github
  rank         int,
  score        numeric,
  status       text,                      -- 등급·상태 (매수 후보 · 진입 조건 충족 · 매수 검토 …)
  verdict      text,                      -- 판정 문구 / 유형
  price        numeric,                   -- 추천 때 기준가 (종가 또는 그 시각 가격)
  zone1_low    numeric, zone1_high numeric, zone1_w numeric,   -- 매수구간 1·2·3차 (하단·상단·비중%)
  zone2_low    numeric, zone2_high numeric, zone2_w numeric,
  zone3_low    numeric, zone3_high numeric, zone3_w numeric,
  entry        numeric,                   -- 매수가 = 1차 매수구간 중앙값 (장중 탭은 진입·매수가)
  entry_avg    numeric,                   -- 1·2·3차 구간 중앙값의 비중 평균
  target1      numeric, target2 numeric, target3 numeric,
  stop         numeric,                   -- 손절가 (상한가포착은 '조건 무효' 가격)
  stop_pct     numeric,                   -- 매수가 대비 %
  target1_pct  numeric, target2_pct numeric,
  rr1          numeric,                   -- 손익비 (1차 목표 − 매수가) ÷ (매수가 − 손절가)
  rr2          numeric,                   -- 2차 목표 기준
  market       text,
  sector       text,
  version      text,                      -- 엔진 버전 (V3 · NX · LC-0.1 …)
  payload      jsonb,                     -- 만들 때 들어간 전체 (점수 항목 · 근거 · 주의 · 계획)
  created_at   timestamptz not null default now(),
  primary key (rec_date, kind, code)
);
create index if not exists recommendations_kind_date on public.recommendations (kind, rec_date);
create index if not exists recommendations_code on public.recommendations (code, rec_date);

alter table public.recommendations enable row level security;
drop policy if exists "read for users" on public.recommendations;
create policy "read for users" on public.recommendations for select to authenticated using (public.is_approved());
-- 쓰기 정책 없음 → service_role 키(배치)만 쓸 수 있음

-- 같은 날 같은 종목이 여러 구분(V3·유망주·당일단타 …)에 겹쳐 추천되면 구분마다 한 줄씩 따로 저장됨 (위 키).
-- 한 종목을 한 줄로 모아 보기: 겹친 구분 전부 + 구분별 점수·매수가·목표·손절·손익비
create or replace view public.recommendation_overlaps with (security_invoker = true) as
select rec_date, code, max(name) as name,
       count(*) as n_kinds,                                   -- 몇 개 구분에서 추천됐나
       array_agg(kind order by kind) as kinds,                -- 겹친 구분 전부
       jsonb_object_agg(kind, jsonb_build_object(
         'rec_time', rec_time, 'score', score, 'status', status, 'entry', entry, 'target1', target1,
         'target2', target2, 'stop', stop, 'rr1', rr1)) as detail
from public.recommendations
group by rec_date, code;
grant select on public.recommendation_overlaps to authenticated;
