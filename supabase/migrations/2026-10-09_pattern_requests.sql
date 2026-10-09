-- ============================================================
-- StockEye 스키마 변경분 (2026-10-09)
--   내용: 종목 검색 → '비슷한 과거 패턴' 요청
--     - 앱: rpc('request_pattern', {p_code}) → 요청 등록 (+ GitHub 에 바로 신호, 설정한 경우)
--           rpc('pattern_request_status', {p_code}) → 그 종목의 최근 요청 상태
--     - 처리: GitHub Actions 'patterns' 작업 (신호 즉시 · 매시간 점검) + 장중 재분석·저녁 배치 끝
--   여러 번 실행해도 안전
--
--   [선택] 요청 즉시 실행 (몇 분 안에 결과) — GitHub 토큰을 Supabase 안에만 저장:
--     1) GitHub → Settings → Developer settings → Fine-grained tokens → 새 토큰
--        저장소: stockEye 하나만 · 권한: Contents = Read and write (repository_dispatch 에 필요)
--     2) Supabase SQL Editor 에서 (토큰은 채팅·코드에 붙이지 말고 여기에만):
--        insert into public.app_config values ('github_repo', '아이디/stockEye')
--          on conflict (key) do update set value = excluded.value;
--        insert into public.app_config values ('github_dispatch_token', '토큰값')
--          on conflict (key) do update set value = excluded.value;
--     설정하지 않으면 매시간 점검·장중·저녁 배치에서 처리됩니다 (최대 1시간 정도).
-- ============================================================

create table if not exists public.pattern_requests (
  id         bigint generated always as identity primary key,
  user_id    uuid not null default auth.uid() references auth.users(id) on delete cascade,
  code       text not null,
  status     text not null default 'queued',   -- queued | running | done | failed
  message    text,
  created_at timestamptz not null default now(),
  done_at    timestamptz
);
create index if not exists pattern_requests_status on public.pattern_requests (status, id);
create index if not exists pattern_requests_code on public.pattern_requests (code, id desc);
alter table public.pattern_requests enable row level security;   -- 정책 없음: 앱은 아래 함수로만 접근

-- GitHub 에 '패턴 요청 있음' 신호 (2분에 한 번까지, 설정 없으면 생략, 실패해도 무시)
create or replace function public._dispatch_patterns() returns void
language plpgsql security definer set search_path = public as $$
declare tok text; repo text; last text;
begin
  select value into tok from public.app_config where key = 'github_dispatch_token';
  select value into repo from public.app_config where key = 'github_repo';
  if coalesce(tok, '') = '' or coalesce(repo, '') = '' then return; end if;
  select value into last from public.app_config where key = 'pattern_last_dispatch';
  if last is not null and last::timestamptz > now() - interval '2 minutes' then return; end if;
  insert into public.app_config values ('pattern_last_dispatch', now()::text)
    on conflict (key) do update set value = excluded.value;
  begin
    perform net.http_post(
      url := 'https://api.github.com/repos/' || repo || '/dispatches',
      body := jsonb_build_object('event_type', 'pattern_request'),
      headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                    'User-Agent', 'stockeye', 'Content-Type', 'application/json'));
  exception when others then null;
  end;
end $$;
revoke all on function public._dispatch_patterns() from public, anon, authenticated;

-- 요청 등록: 승인 회원만 · 6자리 종목코드 · 같은 종목이 이미 대기 중이면 그 요청을 같이 씀 · 회원당 하루 30건
create or replace function public.request_pattern(p_code text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare r public.pattern_requests; n int; ahead int;
begin
  if not public.is_approved() then raise exception '승인된 회원만 요청할 수 있습니다'; end if;
  if p_code !~ '^[0-9A-Z]{6}$' then raise exception '종목코드 형식이 아닙니다'; end if;
  select * into r from public.pattern_requests where code = p_code and status in ('queued', 'running')
    order by id desc limit 1;
  if found then
    select count(*) into ahead from public.pattern_requests where status = 'queued' and id < r.id;
    return jsonb_build_object('id', r.id, 'status', r.status, 'created_at', r.created_at, 'ahead', ahead, 'existing', true);
  end if;
  select count(*) into n from public.pattern_requests where user_id = auth.uid() and created_at > now() - interval '1 day';
  if n >= 30 then raise exception '오늘 요청 한도(30건)를 넘었습니다'; end if;
  insert into public.pattern_requests (code) values (p_code) returning * into r;
  select count(*) into ahead from public.pattern_requests where status = 'queued' and id < r.id;
  perform public._dispatch_patterns();
  return jsonb_build_object('id', r.id, 'status', r.status, 'created_at', r.created_at, 'ahead', ahead, 'existing', false,
    'instant', exists (select 1 from public.app_config where key = 'github_dispatch_token' and coalesce(value, '') <> ''));
end $$;
revoke all on function public.request_pattern(text) from public, anon;
grant execute on function public.request_pattern(text) to authenticated;

-- 그 종목의 최근 요청 상태 (누가 요청했든)
create or replace function public.pattern_request_status(p_code text) returns jsonb
language sql stable security definer set search_path = public as $$
  select case when not public.is_approved() then null else (
    select jsonb_build_object('id', id, 'status', status, 'message', message, 'created_at', created_at, 'done_at', done_at,
      'instant', exists (select 1 from public.app_config where key = 'github_dispatch_token' and coalesce(value, '') <> ''))
    from public.pattern_requests where code = p_code order by id desc limit 1) end $$;
revoke all on function public.pattern_request_status(text) from public, anon;
grant execute on function public.pattern_request_status(text) to authenticated;
