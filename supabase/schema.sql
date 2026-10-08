-- ============================================================
-- StockEye Supabase 스키마 (v2: PC 없이 클라우드 운영)
--   Supabase 대시보드 → SQL Editor → New query → 이 파일 전체 붙여넣기 → Run
--   (여러 번 실행해도 안전: 이미 있는 것은 건너뜀)
--
--   [분석 결과]  배치(GitHub Actions / 클라우드 VM)가 service_role 키로 매일 씀
--                로그인한 사용자는 읽기만 (로그인 안 하면 아무것도 못 봄)
--     daily_reports, candidates, stock_details, backtests, system_status
--   [내 데이터]  본인 것만 (RLS)
--     positions(매매일지·보유종목), orders(승인 대기 주문), alerts, paper_cash,
--     journal_analysis, position_reviews, backtest_requests
--   [회원] profiles — 가입 → 관리자 승인 후 이용 (가장 먼저 가입한 사람이 관리자)
--   [원본 데이터] Storage 버킷 'stockeye' (비공개, service_role 만 접근)
--
--   시각 컬럼은 timestamp(시간대 없음) = 한국 시각(KST) 그대로 저장
-- ============================================================

-- ---------------------------------------------------------------- 회원 (관리자 승인제)
-- 가입하면 profiles 에 'pending' 으로 등록 → 관리자가 앱의 '회원 관리'에서 승인해야 데이터가 보인다.
-- 가장 먼저 가입한 사람(=나)이 자동으로 관리자.
create table if not exists public.profiles (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  email      text,
  status     text not null default 'pending',   -- pending | approved | rejected
  is_admin   boolean not null default false,
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  decided_by uuid
);
alter table public.profiles enable row level security;
alter table public.profiles add column if not exists ntfy_topic text;          -- 각자 휴대폰 알림 토픽
alter table public.profiles add column if not exists notify_daily boolean not null default true;     -- 매일 리포트 요약
alter table public.profiles add column if not exists notify_holdings boolean not null default true;  -- 내 보유종목 경고
alter table public.profiles add column if not exists notify_signals boolean not null default false;  -- 장중 매수 신호

-- 관리자 알림 설정 (선택): insert into public.app_config values ('ntfy_topic', '내토픽') on conflict (key) do update set value = excluded.value;
create table if not exists public.app_config (key text primary key, value text);
alter table public.app_config enable row level security;   -- 정책 없음 = 서버(service_role)만

create or replace function public.is_approved() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.profiles where user_id = auth.uid() and status = 'approved') $$;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.profiles where user_id = auth.uid() and status = 'approved' and is_admin) $$;

-- 가입 알림을 휴대폰(ntfy)으로 보내기 위한 확장 (없으면 알림만 생략)
do $$ begin
  create extension if not exists pg_net;
exception when others then raise notice 'pg_net 사용 불가 → 가입 알림 생략';
end $$;

-- ntfy 알림 보내기 (서버 내부용, 실패해도 무시)
create or replace function public._ntfy(p_topic text, p_title text, p_message text) returns void
language plpgsql security definer set search_path = public as $$
declare server text;
begin
  if p_topic is null or p_topic = '' then return; end if;
  select value into server from public.app_config where key = 'ntfy_server';
  begin
    perform net.http_post(url := coalesce(nullif(server, ''), 'https://ntfy.sh'),
                          body := jsonb_build_object('topic', p_topic, 'title', p_title, 'message', p_message));
  exception when others then null;
  end;
end $$;
revoke all on function public._ntfy(text, text, text) from public, anon, authenticated;

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  first_user boolean := not exists (select 1 from public.profiles where is_admin);
  topic text;
begin
  insert into public.profiles (user_id, email, status, is_admin)
  values (new.id, new.email, case when first_user then 'approved' else 'pending' end, first_user)
  on conflict (user_id) do nothing;
  if not first_user then
    select value into topic from public.app_config where key = 'ntfy_topic';
    perform public._ntfy(topic, 'StockEye 가입 승인 요청',
                         coalesce(new.email, '') || ' 님이 가입했습니다. 앱 → 회원 관리에서 승인하세요.');
  end if;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- 이 기능을 넣기 전에 가입한 사용자: 승인 상태로 등록, 가장 먼저 가입한 사람 = 관리자
insert into public.profiles (user_id, email, status, is_admin, created_at)
select id, email, 'approved', false, created_at from auth.users
on conflict (user_id) do nothing;
update public.profiles set is_admin = true
 where user_id = (select user_id from public.profiles order by created_at limit 1)
   and not exists (select 1 from public.profiles where is_admin);

drop policy if exists "self or admin read" on public.profiles;
create policy "self or admin read" on public.profiles for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

-- 관리자: 승인 / 거절 / 승인 취소
create or replace function public.set_user_status(p_user uuid, p_status text)
returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception '관리자만 할 수 있습니다'; end if;
  if p_status not in ('approved', 'rejected', 'pending') then raise exception '상태 값이 올바르지 않습니다'; end if;
  if p_user = auth.uid() then raise exception '자기 자신은 바꿀 수 없습니다'; end if;
  update public.profiles set status = p_status, decided_at = now(), decided_by = auth.uid() where user_id = p_user;
  if not found then return jsonb_build_object('ok', false, 'message', '사용자 없음'); end if;
  if p_status = 'approved' then
    perform public._ntfy((select ntfy_topic from public.profiles where user_id = p_user),
                         'StockEye 가입 승인', '가입이 승인됐습니다. 앱에서 [다시 확인]을 누르면 바로 이용할 수 있어요.');
  end if;
  return jsonb_build_object('ok', true);
end $$;

-- 내 알림 설정 (승인 전에도 가능 → 승인되면 바로 알림 받음)
drop function if exists public.set_my_notify(text, boolean, boolean);
create or replace function public.set_my_notify(p_topic text, p_daily boolean default true,
                                                p_holdings boolean default true, p_signals boolean default false)
returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception '로그인이 필요합니다'; end if;
  if coalesce(p_topic, '') <> '' and p_topic !~ '^[A-Za-z0-9_-]{6,64}$' then
    raise exception '토픽은 영문·숫자·-·_ 로 6~64자여야 합니다';
  end if;
  update public.profiles set ntfy_topic = nullif(p_topic, ''), notify_daily = coalesce(p_daily, true),
         notify_holdings = coalesce(p_holdings, true), notify_signals = coalesce(p_signals, false)
   where user_id = auth.uid();
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.send_test_notify()
returns jsonb
language plpgsql security definer set search_path = public as $$
declare t text;
begin
  select ntfy_topic into t from public.profiles where user_id = auth.uid();
  if t is null then return jsonb_build_object('ok', false, 'message', '먼저 알림 토픽을 저장하세요'); end if;
  perform public._ntfy(t, 'StockEye 테스트', '알림이 잘 옵니다 👍');
  return jsonb_build_object('ok', true, 'message', '보냈습니다. 몇 초 안에 ntfy 앱에 오면 성공');
end $$;
revoke all on function public.set_my_notify(text, boolean, boolean, boolean) from public, anon;
grant execute on function public.set_my_notify(text, boolean, boolean, boolean) to authenticated;
revoke all on function public.send_test_notify() from public, anon;
grant execute on function public.send_test_notify() to authenticated;
revoke all on function public.set_user_status(uuid, text) from public, anon;
grant execute on function public.set_user_status(uuid, text) to authenticated;

-- ---------------------------------------------------------------- 분석 결과
create table if not exists public.daily_reports (
  date        date primary key,
  as_of       timestamp not null,
  market      jsonb not null,           -- 지수, 분위기, 상승/하락 종목 수
  sectors     jsonb not null,           -- 업종/테마 강도 전체 (소속 상위 종목 포함)
  top10       jsonb not null,
  strategies  jsonb,                    -- 전략 A~E 요약 (이름·설명·한계·후보 수·상위 3)
  funnel      jsonb,
  labels      jsonb,
  unmatched_theme_names jsonb,
  ai_explained int default 0,
  created_at  timestamptz not null default now()
);

create table if not exists public.candidates (
  date        date not null,
  list        text not null,            -- 'overall' | 'A' | 'B' | 'C' | 'D' | 'E'
  rank        int  not null,
  code        text not null,
  name        text,
  score       numeric,
  strategy_score numeric,
  verdict     text,
  payload     jsonb not null,           -- 매매계획, 근거, 주의사항 전체
  primary key (date, list, code)
);
create index if not exists candidates_date_list on public.candidates (date, list, rank);

-- 전 종목 상세 (검색해서 들어가는 화면). 최신 1건만 유지.
create table if not exists public.stock_details (
  code        text primary key,
  name        text,
  market      text,
  sector      text,
  date        date,
  score       numeric,
  in_universe boolean,                  -- 1차 필터 통과 여부
  candidate   jsonb not null,           -- 점수·매매계획·근거·주의
  chart       jsonb,                    -- 최근 120일 일봉
  disclosures jsonb,                    -- 최근 30일 공시
  explanation jsonb,                    -- 설명 (AI 또는 규칙 기반)
  similar_patterns jsonb,               -- 비슷한 과거 패턴 (후보 종목만 미리 계산)
  updated_at  timestamptz not null default now()
);
create index if not exists stock_details_name on public.stock_details (name);

create table if not exists public.backtests (
  key         text primary key,         -- 'A'~'E', 'engine'
  name        text,
  start_date  date,
  end_date    date,
  metrics     jsonb,
  metrics_oos jsonb,
  audit_passed boolean,
  payload     jsonb not null,           -- 전체 결과 (거래 목록, 자산곡선, 연도별 …)
  updated_at  timestamptz not null default now()
);

create table if not exists public.system_status (
  key         text primary key,         -- 'trading' | 'batch'
  payload     jsonb not null,
  updated_at  timestamptz not null default now()
);

alter table public.daily_reports  enable row level security;
alter table public.candidates     enable row level security;
alter table public.stock_details  enable row level security;
alter table public.backtests      enable row level security;
alter table public.system_status  enable row level security;

do $$
declare t text;
begin
  foreach t in array array['daily_reports','candidates','stock_details','backtests','system_status'] loop
    execute format('drop policy if exists "read for users" on public.%I', t);
    execute format('create policy "read for users" on public.%I for select to authenticated using (public.is_approved())', t);
  end loop;
end $$;
-- 쓰기 정책 없음 → service_role 키(배치)만 쓸 수 있음

-- ---------------------------------------------------------------- 매매일지 / 보유종목
create table if not exists public.positions (
  id            text primary key default substr(md5(random()::text || clock_timestamp()::text), 1, 12),
  user_id       uuid not null default auth.uid() references auth.users(id) on delete cascade,
  mode          text not null,          -- paper | kis_paper | real | manual
  code text not null, name text,
  strategy text, list_key text,
  score numeric, strategy_score numeric,
  entry_time timestamp not null, entry_price numeric not null, qty numeric not null, entry_cost numeric,
  stop numeric, target1 numeric, target2 numeric,
  reasons jsonb, warnings jsonb,
  market_mood text, theme text, verdict text,
  plan jsonb,
  signal_time timestamp,
  exit_time timestamp, exit_price numeric, exit_proceeds numeric, exit_reason text,
  ret_pct numeric, pnl numeric, hold_days int, result text,
  min_price numeric, max_price numeric,
  late_stop boolean default false,
  memo text,
  status text not null default 'open'   -- open | closed
);
create index if not exists positions_user_status on public.positions (user_id, status, mode);

create table if not exists public.orders (
  id            text primary key default substr(md5(random()::text || clock_timestamp()::text), 1, 12),
  user_id       uuid not null default auth.uid() references auth.users(id) on delete cascade,
  created_at    timestamp not null,
  mode text not null, side text not null,
  code text not null, name text,
  qty numeric not null, price numeric,
  reason text, position_id text,
  snapshot jsonb,
  status text not null,   -- pending | approve_requested | approved | sent | filled | rejected | expired | failed
  expires_at timestamp,
  broker_order_id text, filled_price numeric, filled_qty numeric, filled_at timestamp,
  message text
);
create index if not exists orders_user_status on public.orders (user_id, status);

create table if not exists public.alerts (
  id        bigint generated always as identity primary key,
  user_id   uuid not null references auth.users(id) on delete cascade,
  time      timestamp not null,
  kind      text not null, code text, name text, message text, payload jsonb
);
create index if not exists alerts_key on public.alerts (user_id, kind, code, time);

create table if not exists public.paper_cash (
  user_id uuid not null references auth.users(id) on delete cascade,
  mode    text not null,
  balance numeric not null,
  primary key (user_id, mode)
);

create table if not exists public.journal_analysis (
  user_id    uuid not null references auth.users(id) on delete cascade,
  mode       text not null,             -- 'all' | paper | kis_paper | real | manual
  payload    jsonb not null,            -- 통계 + 코치 요약
  updated_at timestamptz not null default now(),
  primary key (user_id, mode)
);

create table if not exists public.position_reviews (
  position_id text primary key references public.positions(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  payload     jsonb not null,
  updated_at  timestamptz not null default now()
);

create table if not exists public.backtest_requests (
  id         bigint generated always as identity primary key,
  user_id    uuid not null default auth.uid() references auth.users(id) on delete cascade,
  spec       jsonb not null,            -- {"strategy":"A"} | {"engine":true,"min_score":75} | {"rules":[...]}
  status     text not null default 'queued',   -- queued | running | done | failed
  result     jsonb,
  message    text,
  created_at timestamptz not null default now(),
  done_at    timestamptz
);

alter table public.positions         enable row level security;
alter table public.orders            enable row level security;
alter table public.alerts            enable row level security;
alter table public.paper_cash        enable row level security;
alter table public.journal_analysis  enable row level security;
alter table public.position_reviews  enable row level security;
alter table public.backtest_requests enable row level security;

-- 본인 것 읽기
do $$
declare t text;
begin
  foreach t in array array['positions','orders','alerts','paper_cash','journal_analysis','position_reviews','backtest_requests'] loop
    execute format('drop policy if exists "own read" on public.%I', t);
    execute format('create policy "own read" on public.%I for select to authenticated using (user_id = auth.uid() and public.is_approved())', t);
  end loop;
end $$;

-- 보유종목: 손절/목표/메모 수정, 삭제는 앱에서 직접 (추가·매도는 아래 함수로)
drop policy if exists "own update" on public.positions;
create policy "own update" on public.positions for update to authenticated
  using (user_id = auth.uid() and public.is_approved()) with check (user_id = auth.uid());
drop policy if exists "own delete" on public.positions;
create policy "own delete" on public.positions for delete to authenticated using (user_id = auth.uid() and public.is_approved());

-- 백테스트 요청: 앱에서 넣기
drop policy if exists "own insert" on public.backtest_requests;
-- 한 사람당 대기/실행 중인 요청은 1개까지 (여러 사람이 써도 배치 시간이 넘치지 않게)
create policy "own insert" on public.backtest_requests for insert to authenticated
  with check (user_id = auth.uid() and public.is_approved() and not exists (
    select 1 from public.backtest_requests b where b.user_id = auth.uid() and b.status in ('queued', 'running')));

-- ---------------------------------------------------------------- 앱에서 부르는 함수 (RPC)
create or replace function public.kst_now() returns timestamp
language sql stable as $$ select (now() at time zone 'Asia/Seoul')::timestamp(0) $$;

-- 직접 산 종목 기록: 그날 분석 스냅샷(점수·전략·손절·목표·근거)과 함께 매매일지에 저장
create or replace function public.open_manual_position(
  p_code text, p_price numeric, p_qty numeric, p_entry_time timestamp default null,
  p_stop numeric default null, p_target1 numeric default null, p_target2 numeric default null,
  p_memo text default null, p_name text default null)
returns public.positions
language plpgsql security definer set search_path = public as $$
declare
  d   public.stock_details;
  c   jsonb;
  pl  jsonb;
  mood text;
  lk  text;
  r   public.positions;
begin
  if not public.is_approved() then raise exception '관리자 승인 후 이용할 수 있습니다'; end if;
  select * into d from stock_details where code = p_code;
  -- 오늘 후보 목록에 있으면 그 후보(전략 정보 포함)를 우선 사용
  select cd.payload, cd.list into c, lk from candidates cd
   where cd.code = p_code and cd.date = (select max(date) from daily_reports)
   order by (cd.list = 'overall') desc, cd.rank limit 1;
  if c is null then c := coalesce(d.candidate, '{}'::jsonb); lk := null; end if;
  pl := coalesce(c->'plan', '{}'::jsonb);
  select market->>'mood' into mood from daily_reports order by date desc limit 1;
  insert into positions (user_id, mode, code, name, strategy, list_key, score, strategy_score,
                         entry_time, entry_price, qty, entry_cost, stop, target1, target2,
                         reasons, warnings, market_mood, theme, verdict, plan,
                         min_price, max_price, memo, status)
  values (auth.uid(), 'manual', p_code, coalesce(p_name, d.name, c->>'name', p_code),
          coalesce(c->>'strategy', case when lk not in ('overall') then lk end), lk,
          (c->>'score')::numeric, (c->>'strategy_score')::numeric,
          coalesce(p_entry_time, kst_now()), p_price, p_qty, p_price * p_qty,
          coalesce(p_stop, (pl->>'stop')::numeric), coalesce(p_target1, (pl->>'target1')::numeric),
          coalesce(p_target2, (pl->>'target2')::numeric),
          coalesce(c->'reasons', '[]'::jsonb) || coalesce(c->'strategy_reasons', '[]'::jsonb),
          coalesce(c->'warnings', '[]'::jsonb), mood, c->>'theme', pl->>'verdict', pl,
          p_price, p_price, p_memo, 'open')
  returning * into r;
  return r;
end $$;

-- 매도 기록 (수익률·보유기간·결과·손절 지연 자동 계산)
create or replace function public.close_position(
  p_id text, p_price numeric, p_reason text default '수동', p_exit_time timestamp default null)
returns public.positions
language plpgsql security definer set search_path = public as $$
declare
  p public.positions;
  t timestamp := coalesce(p_exit_time, kst_now());
  proceeds numeric;
  cost numeric;
  ret numeric;
  days int;
begin
  if not public.is_approved() then raise exception '관리자 승인 후 이용할 수 있습니다'; end if;
  select * into p from positions where id = p_id and user_id = auth.uid() for update;
  if p is null or p.status <> 'open' then raise exception '열린 포지션이 아닙니다'; end if;
  proceeds := p_price * p.qty;
  cost := coalesce(nullif(p.entry_cost, 0), p.entry_price * p.qty);
  ret := case when cost > 0 then (proceeds / cost - 1) * 100 else 0 end;
  select greatest(0, count(*) - 1) into days
    from generate_series(p.entry_time::date, t::date, interval '1 day') g
   where extract(isodow from g) < 6;
  update positions set exit_time = t, exit_price = p_price, exit_proceeds = proceeds, exit_reason = p_reason,
         ret_pct = round(ret, 2), pnl = round(proceeds - cost), hold_days = days,
         result = case when ret > 0.5 then '성공' when ret < -0.5 then '실패' else '본전' end,
         late_stop = (p.stop is not null and p_price < p.stop * 0.99),
         min_price = least(coalesce(p.min_price, p_price), p_price),
         max_price = greatest(coalesce(p.max_price, p_price), p_price),
         status = 'closed'
   where id = p_id
  returning * into p;
  return p;
end $$;

-- 반자동 주문 승인: 상태만 바꾸고, 실제 주문은 장중 감시 서버가 현재가를 다시 확인한 뒤 낸다
create or replace function public.approve_order(p_id text)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare o public.orders;
begin
  if not public.is_approved() then raise exception '관리자 승인 후 이용할 수 있습니다'; end if;
  select * into o from orders where id = p_id and user_id = auth.uid() for update;
  if o is null or o.status <> 'pending' then
    return jsonb_build_object('ok', false, 'message', '승인 대기 주문이 아닙니다 (만료/처리됨)');
  end if;
  if o.expires_at is not null and o.expires_at < kst_now() then
    update orders set status = 'expired' where id = p_id;
    return jsonb_build_object('ok', false, 'message', '승인 시간이 지나 만료됐습니다');
  end if;
  update orders set status = 'approve_requested' where id = p_id;
  return jsonb_build_object('ok', true, 'queued', true,
    'message', '승인했습니다. 감시 서버가 현재가를 다시 확인한 뒤 주문합니다 (보통 30초 안).');
end $$;

create or replace function public.reject_order(p_id text)
returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_approved() then raise exception '관리자 승인 후 이용할 수 있습니다'; end if;
  update orders set status = 'rejected', message = '사용자 거절'
   where id = p_id and user_id = auth.uid() and status = 'pending';
  if not found then return jsonb_build_object('ok', false, 'message', '승인 대기 주문이 아닙니다'); end if;
  return jsonb_build_object('ok', true);
end $$;

revoke all on function public.open_manual_position(text, numeric, numeric, timestamp, numeric, numeric, numeric, text, text) from public, anon;
revoke all on function public.close_position(text, numeric, text, timestamp) from public, anon;
revoke all on function public.approve_order(text) from public, anon;
revoke all on function public.reject_order(text) from public, anon;
grant execute on function public.open_manual_position(text, numeric, numeric, timestamp, numeric, numeric, numeric, text, text) to authenticated;
grant execute on function public.close_position(text, numeric, text, timestamp) to authenticated;
grant execute on function public.approve_order(text) to authenticated;
grant execute on function public.reject_order(text) to authenticated;

-- ---------------------------------------------------------------- API 접근 권한 (명시)
-- 프로젝트 생성 때 "Automatically expose new tables" 를 껐어도 동작하도록 직접 부여.
-- 실제로 누가 무엇을 보는지는 위의 RLS 정책이 결정한다 (로그인 안 한 anon 에게는 아무 권한도 주지 않음).
grant usage on schema public to authenticated, service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;
grant select on public.profiles to authenticated;
grant select on public.daily_reports, public.candidates, public.stock_details, public.backtests,
                public.system_status, public.positions, public.orders, public.alerts, public.paper_cash,
                public.journal_analysis, public.position_reviews, public.backtest_requests to authenticated;
grant update, delete on public.positions to authenticated;
grant insert on public.backtest_requests to authenticated;
grant usage, select on all sequences in schema public to authenticated;

-- ---------------------------------------------------------------- 원본 데이터 보관 (Storage)
insert into storage.buckets (id, name, public)
values ('stockeye', 'stockeye', false)
on conflict (id) do nothing;
-- 정책을 만들지 않으므로 service_role(배치)만 읽고 쓸 수 있음

-- ---------------------------------------------------------------- v1 에서 쓰던 표 정리 (있으면)
drop table if exists public.ai_explanations;
drop table if exists public.sector_strength;
drop table if exists public.journal;
drop table if exists public.holdings;
drop table if exists public.trades;
drop table if exists public.watchlist;
drop table if exists public.strategy_settings;

-- ---------------------------------------------------------------- 지금 시세 (메인 화면, 2026-10-08)
-- 1) 서버에서 웹 주소를 바로 읽는 확장 (Supabase: Database → Extensions 의 'http')
create extension if not exists http with schema extensions;

-- 2) 캐시 (여러 사람이 동시에 열어도 네이버에는 20초에 한 번만 요청)
create table if not exists public.live_cache (
  key        text primary key,
  status     int,
  body       jsonb,
  fetched_at timestamptz not null default now()
);
alter table public.live_cache enable row level security;   -- 정책 없음 = 아래 함수로만 접근
revoke all on public.live_cache from anon, authenticated;

-- 3) 실시간 시세 (승인된 회원만)
--    p_kind  = 'index' (KOSPI,KOSDAQ,KPI200) | 'stock' (종목코드 6자리, 쉼표로 최대 50개)
--    반환    = {status, body(네이버 응답 그대로), fetched_at, cached, error?}  — 해석은 앱이 함
create or replace function public.live_quotes(p_kind text, p_codes text)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  k text;
  old public.live_cache;
  had boolean;
  v_status int;
  v_content text;
  v_body jsonb;
begin
  if not public.is_approved() then raise exception '관리자 승인 후 이용할 수 있습니다'; end if;
  p_codes := upper(replace(coalesce(p_codes, ''), ' ', ''));
  if p_kind = 'stock' then
    if p_codes !~ '^[0-9A-Z]{6}(,[0-9A-Z]{6}){0,49}$' then raise exception '종목코드 형식이 올바르지 않습니다'; end if;
  elsif p_kind = 'index' then
    if p_codes !~ '^(KOSPI|KOSDAQ|KPI200)(,(KOSPI|KOSDAQ|KPI200)){0,2}$' then raise exception '지수 코드가 올바르지 않습니다'; end if;
  else
    raise exception 'p_kind 는 index 또는 stock';
  end if;

  k := p_kind || ':' || p_codes;
  select * into old from public.live_cache where key = k;
  had := found;
  if had and old.status = 200 and old.fetched_at > now() - interval '20 seconds' then
    return jsonb_build_object('status', old.status, 'body', old.body, 'fetched_at', old.fetched_at, 'cached', true);
  end if;

  begin
    perform extensions.http_set_curlopt('CURLOPT_TIMEOUT_MS', '4000');
    select r.status, r.content into v_status, v_content
      from extensions.http((
        'GET',
        'https://polling.finance.naver.com/api/realtime/domestic/' || p_kind || '/' || p_codes,
        array[extensions.http_header('User-Agent', 'Mozilla/5.0 (StockEye)'),
              extensions.http_header('Referer', 'https://finance.naver.com/')],
        null, null)::extensions.http_request) r;
    begin
      v_body := v_content::jsonb;
    exception when others then
      v_body := to_jsonb(left(coalesce(v_content, ''), 300));
    end;
  exception when others then
    -- 네트워크 오류: 예전 값이라도 돌려준다
    if had then
      return jsonb_build_object('status', old.status, 'body', old.body, 'fetched_at', old.fetched_at,
                                'cached', true, 'stale', true, 'error', sqlerrm);
    end if;
    return jsonb_build_object('status', 0, 'body', null, 'fetched_at', now(), 'error', sqlerrm);
  end;

  if v_status = 200 then
    insert into public.live_cache (key, status, body, fetched_at) values (k, v_status, v_body, now())
    on conflict (key) do update set status = excluded.status, body = excluded.body, fetched_at = excluded.fetched_at;
  elsif had then
    return jsonb_build_object('status', old.status, 'body', old.body, 'fetched_at', old.fetched_at,
                              'cached', true, 'stale', true, 'error', 'HTTP ' || v_status);
  end if;
  if random() < 0.02 then
    delete from public.live_cache where fetched_at < now() - interval '2 days';
  end if;
  return jsonb_build_object('status', v_status, 'body', v_body, 'fetched_at', now(), 'cached', false);
end $$;
revoke all on function public.live_quotes(text, text) from public, anon;
grant execute on function public.live_quotes(text, text) to authenticated;
