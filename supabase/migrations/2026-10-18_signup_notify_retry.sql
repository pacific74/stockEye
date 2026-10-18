-- Supabase SQL Editor 에 통째로 붙여넣어 실행 (2026-10-18) — 가입 알림 429 시 5분 뒤 재시도 (schema.sql 과 같은 내용)
-- ntfy 알림 보내기 (서버 내부용, 실패해도 무시) — 요청 번호(net 응답 확인용)를 돌려준다
drop function if exists public._ntfy(text, text, text);
create or replace function public._ntfy(p_topic text, p_title text, p_message text) returns bigint
language plpgsql security definer set search_path = public as $$
declare server text; tok text; rid bigint;
begin
  if p_topic is null or p_topic = '' then return null; end if;
  select value into server from public.app_config where key = 'ntfy_server';
  select value into tok from public.app_config where key = 'ntfy_token';   -- 선택: ntfy 계정 토큰 (없으면 익명 · 공유 IP 라 429 가 날 수 있음)
  begin
    select net.http_post(url := coalesce(nullif(server, ''), 'https://ntfy.sh'),
                         body := jsonb_build_object('topic', p_topic, 'title', p_title, 'message', p_message),
                         headers := case when coalesce(tok, '') <> ''
                                         then jsonb_build_object('Content-Type', 'application/json', 'Authorization', 'Bearer ' || tok)
                                         else jsonb_build_object('Content-Type', 'application/json') end) into rid;
  exception when others then rid := null;
  end;
  return rid;
end $$;
revoke all on function public._ntfy(text, text, text) from public, anon, authenticated;

-- 가입 알림 재시도 기록 (2026-10-18: ntfy.sh 가 429 로 거절하면 5분 뒤 다시 · 최대 6번)
alter table public.profiles add column if not exists signup_notified boolean not null default false;
alter table public.profiles add column if not exists signup_tries int not null default 0;
alter table public.profiles add column if not exists signup_req bigint;
alter table public.profiles add column if not exists signup_at timestamptz;

create or replace function public._admin_topic() returns text
language sql stable security definer set search_path = public as $$
  select coalesce(
    nullif((select value from public.app_config where key = 'ntfy_topic'), ''),
    (select ntfy_topic from public.profiles where is_admin and coalesce(ntfy_topic, '') <> '' order by created_at limit 1)) $$;
revoke all on function public._admin_topic() from public, anon, authenticated;

create or replace function public._signup_ping(p_user uuid, p_email text) returns void
language plpgsql security definer set search_path = public as $$
declare rid bigint;
begin
  rid := public._ntfy(public._admin_topic(), 'StockEye 가입 승인 요청',
                      coalesce(p_email, '') || ' 님이 가입했습니다. 앱 → 회원 관리에서 승인하세요.');
  update public.profiles set signup_req = rid, signup_at = now(), signup_tries = signup_tries + 1 where user_id = p_user;
end $$;
revoke all on function public._signup_ping(uuid, text) from public, anon, authenticated;

-- 5분마다: 승인 대기 중인데 알림이 정상(200번대) 접수되지 않았으면 다시 보냄
create or replace function public.retry_signup_notify() returns void
language plpgsql security definer set search_path = public as $$
declare r record; ok boolean;
begin
  for r in select user_id, email, signup_req, signup_at from public.profiles
            where status = 'pending' and not signup_notified and signup_tries < 6 loop
    ok := r.signup_req is not null and exists (select 1 from net._http_response
                                               where id = r.signup_req and status_code between 200 and 299);
    if ok then
      update public.profiles set signup_notified = true where user_id = r.user_id;
    elsif r.signup_at is null or r.signup_at < now() - interval '4 minutes' then
      perform public._signup_ping(r.user_id, r.email);
    end if;
  end loop;
end $$;
revoke all on function public.retry_signup_notify() from public, anon, authenticated;

do $$ begin
  create extension if not exists pg_cron;
  perform cron.unschedule(jobid) from cron.job where jobname = 'signup-notify-retry';
  perform cron.schedule('signup-notify-retry', '*/5 * * * *', 'select public.retry_signup_notify()');
exception when others then raise notice 'pg_cron 사용 불가 → 가입 알림 재시도 생략 (Database → Extensions 에서 pg_cron 켜기)';
end $$;

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  first_user boolean := not exists (select 1 from public.profiles where is_admin);
begin
  insert into public.profiles (user_id, email, status, is_admin)
  values (new.id, new.email, case when first_user then 'approved' else 'pending' end, first_user)
  on conflict (user_id) do nothing;
  if not first_user then
    perform public._signup_ping(new.id, new.email);
  end if;
  return new;
end $$;

