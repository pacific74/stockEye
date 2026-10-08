-- ============================================================
-- StockEye 스키마 변경분 (2026-10-08)
--   대상: 2026-10-07_member_notify.sql 까지 실행한 경우
--   내용: 메인 화면 '지금 시세' — Supabase 가 네이버 실시간 시세를 대신 받아 20초간 캐시
--   여러 번 실행해도 안전
-- ============================================================

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
