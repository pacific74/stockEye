-- ============================================================
-- StockEye 스키마 변경분 (2026-10-07 저녁)
--   대상: 오늘 '회원 관리(가입 승인)' 스키마를 이미 실행한 경우
--   내용: 회원별 휴대폰 알림 (승인 알림 · 매일 요약 · 보유종목 경고 · 장중 매수 신호)
--   여러 번 실행해도 안전
-- ============================================================

-- 1) 알림 설정 칸
alter table public.profiles add column if not exists ntfy_topic text;
alter table public.profiles add column if not exists notify_daily boolean not null default true;
alter table public.profiles add column if not exists notify_holdings boolean not null default true;
alter table public.profiles add column if not exists notify_signals boolean not null default false;

-- 2) 알림 보내기 (서버 내부용)
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

-- 3) 가입 알림 (관리자에게)
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

-- 4) 승인하면 본인에게 알림 + 내 알림 설정 + 테스트
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
