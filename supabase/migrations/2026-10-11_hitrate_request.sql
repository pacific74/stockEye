-- ============================================================
-- StockEye 스키마 변경분 (2026-10-11)
--   내용: 앱 '검증' 화면에서 관심종목 적중률 계산 요청 (관리자만)
--     - 앱: rpc('request_hitrate', {p_only}) → GitHub 'weekly-backtest' 작업에 바로 신호
--           p_only 예: 'HIT' (전체) · 'HIT:nextday' · 'HIT:2025' · 'HIT:early:2024,2025'
--     - 진행 상태: system_status 'hitrate_job' (queued → running → done / failed) 를 앱이 읽음
--   신호에는 패턴 요청과 같은 설정이 필요 (Supabase app_config 의 github_dispatch_token · github_repo).
--   토큰은 SQL Editor 에서만 넣고 채팅·코드에 붙이지 말 것 (2026-10-09_pattern_requests.sql 참고)
--   여러 번 실행해도 안전
-- ============================================================

create or replace function public.request_hitrate(p_only text default 'HIT') returns jsonb
language plpgsql security definer set search_path = public as $$
declare tok text; repo text; cur jsonb; cur_at timestamptz; only_ text := coalesce(nullif(trim(p_only), ''), 'HIT');
begin
  if not public.is_admin() then raise exception '관리자만 요청할 수 있습니다'; end if;
  -- 허용 형식만: HIT · HIT:탭[,탭] · HIT:연도[,연도] · HIT:탭:연도
  if only_ !~ '^HIT(:(v3|nextday|early|reversal|uplimit)(,(v3|nextday|early|reversal|uplimit))*)?(:20[0-9]{2}(,20[0-9]{2})*)?$' then
    raise exception '형식이 맞지 않습니다: %', only_;
  end if;
  select value into tok from public.app_config where key = 'github_dispatch_token';
  select value into repo from public.app_config where key = 'github_repo';
  if coalesce(tok, '') = '' or coalesce(repo, '') = '' then
    raise exception 'GitHub 신호 설정이 없습니다 (app_config github_dispatch_token · github_repo). Actions 에서 직접 실행하세요';
  end if;
  -- 이미 대기(10분 안)·실행 중(2시간 안)이면 다시 보내지 않음 — 신호가 안 먹혀 '대기'로 남아도 10분 뒤엔 다시 요청 가능
  select payload, updated_at into cur, cur_at from public.system_status where key = 'hitrate_job';
  if cur is not null and ((cur->>'status' = 'queued' and cur_at > now() - interval '10 minutes')
                       or (cur->>'status' = 'running' and cur_at > now() - interval '2 hours')) then
    return jsonb_build_object('ok', false, 'status', cur->>'status', 'only', cur->>'only', 'message', '이미 계산 중입니다');
  end if;
  insert into public.system_status (key, payload, updated_at)
    values ('hitrate_job', jsonb_build_object('status', 'queued', 'only', only_, 'at', now()), now())
    on conflict (key) do update set payload = excluded.payload, updated_at = excluded.updated_at;
  begin
    perform net.http_post(
      url := 'https://api.github.com/repos/' || repo || '/dispatches',
      body := jsonb_build_object('event_type', 'hitrate_request', 'client_payload', jsonb_build_object('only', only_)),
      headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                    'User-Agent', 'stockeye', 'Content-Type', 'application/json'));
  exception when others then
    raise exception 'GitHub 신호 실패: %', sqlerrm;
  end;
  return jsonb_build_object('ok', true, 'status', 'queued', 'only', only_);
end $$;
revoke all on function public.request_hitrate(text) from public, anon;
grant execute on function public.request_hitrate(text) to authenticated;
