-- ============================================================
-- StockEye 스키마 변경분 (2026-10-12)
--   내용: 앱 메인·'관심 > 종가배팅' 의 [종목찾기] 버튼 (관리자만)
--     - 앱: rpc('request_closingbet') → GitHub 'closingbet' 작업에 신호 (repository_dispatch closingbet_request)
--       → GitHub 이 python -m scripts.closingbet --cloud --once 를 한 번 실행 → system_status 'closingbet' 갱신
--         (15:20 이후 실행이면 매수 후보 상위 3 을 저장 → 다음 날 저녁 배치가 검증 결과를 매김)
--     - 진행 상태: system_status 'closingbet_job' (queued → running → done / failed)
--   신호 설정은 당일단타와 같음 (app_config github_dispatch_token · github_repo). 여러 번 실행해도 안전
-- ============================================================

create or replace function public.request_closingbet() returns jsonb
language plpgsql security definer set search_path = public as $$
declare tok text; repo text; cur jsonb; cur_at timestamptz;
begin
  if not public.is_admin() then raise exception '관리자만 요청할 수 있습니다'; end if;
  select value into tok from public.app_config where key = 'github_dispatch_token';
  select value into repo from public.app_config where key = 'github_repo';
  if coalesce(tok, '') = '' or coalesce(repo, '') = '' then
    raise exception 'GitHub 신호 설정이 없습니다 (app_config github_dispatch_token · github_repo)';
  end if;
  -- 대기(5분 안)·실행 중(10분 안)이면 다시 보내지 않음 (실패·멈춤이면 10분 뒤 다시 요청 가능)
  select payload, updated_at into cur, cur_at from public.system_status where key = 'closingbet_job';
  if cur is not null and ((cur->>'status' = 'queued' and cur_at > now() - interval '5 minutes')
                       or (cur->>'status' = 'running' and cur_at > now() - interval '10 minutes')) then
    return jsonb_build_object('ok', false, 'status', cur->>'status', 'message', '이미 찾는 중입니다');
  end if;
  insert into public.system_status (key, payload, updated_at)
    values ('closingbet_job', jsonb_build_object('status', 'queued', 'at', now()), now())
    on conflict (key) do update set payload = excluded.payload, updated_at = excluded.updated_at;
  begin
    perform net.http_post(
      url := 'https://api.github.com/repos/' || repo || '/dispatches',
      body := jsonb_build_object('event_type', 'closingbet_request', 'client_payload', '{}'::jsonb),
      headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                    'User-Agent', 'stockeye', 'Content-Type', 'application/json'));
  exception when others then
    raise exception 'GitHub 신호 실패: %', sqlerrm;
  end;
  return jsonb_build_object('ok', true, 'status', 'queued');
end $$;
revoke all on function public.request_closingbet() from public, anon;
grant execute on function public.request_closingbet() to authenticated;
