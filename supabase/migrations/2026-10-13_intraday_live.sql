-- ============================================================
-- StockEye 스키마 변경분 (2026-10-13 · 당일매매 실시간)
--   intraday_live: PC 22_intraday.bat(당일단타 + 상한가포착 통합)이 고정 종목의 상태가 바뀔 때마다 한 행씩 씀
--     key = '종류:날짜:종목' (daytrade:2026-10-13:005930) · payload = 추적 상태 (지금가·목표 달성·매도신호·결과)
--     앱 '당일매매' 화면이 Realtime 으로 받아 바로 반영 (가격만 바뀐 것은 종목당 10초에 한 번)
--   읽기: 관리자만 · 쓰기: PC 의 service_role 키만 (앱에서는 못 씀)
--   7일 지난 행은 저녁 배치가 지움. 여러 번 실행해도 안전
-- ============================================================

create table if not exists public.intraday_live (
  key        text primary key,
  kind       text not null,
  date       date not null,
  code       text not null,
  payload    jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
create index if not exists intraday_live_date on public.intraday_live (date);

alter table public.intraday_live enable row level security;
drop policy if exists intraday_live_admin_read on public.intraday_live;
create policy intraday_live_admin_read on public.intraday_live
  for select to authenticated using (public.is_admin());

-- Realtime 으로 변경 전달 (이미 들어 있으면 건너뜀)
do $$
begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'intraday_live') then
    alter publication supabase_realtime add table public.intraday_live;
  end if;
end $$;
