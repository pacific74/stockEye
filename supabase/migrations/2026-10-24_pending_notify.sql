-- Supabase SQL Editor 에 통째로 붙여넣어 실행 (2026-10-24)
-- ntfy.sh 가 Supabase 공유 IP 를 429(하루 한도)로 막아서, 앱 '테스트 알림 보내기' 는 요청만 걸어 두고
-- PC 22번 창 · GitHub 배치가 대신 보냄. 가입 승인 요청 알림도 Supabase 시도가 안 접수되면 배치가 대신 보냄.
alter table public.profiles add column if not exists test_notify_at timestamptz;

create or replace function public.send_test_notify()
returns jsonb
language plpgsql security definer set search_path = public as $$
declare t text;
begin
  select ntfy_topic into t from public.profiles where user_id = auth.uid();
  if coalesce(t, '') = '' then return jsonb_build_object('ok', false, 'message', '먼저 알림 토픽을 저장하세요'); end if;
  update public.profiles set test_notify_at = now() where user_id = auth.uid();
  return jsonb_build_object('ok', true, 'message',
    '테스트를 요청했어요. PC·배치가 확인할 때 보내서 몇 분 걸릴 수 있고, 알림이 안 와도 정상일 수 있어요 (ntfy 무료 한도·전송 지연). 실제 알림은 정상으로 옵니다.');
end $$;
revoke all on function public.send_test_notify() from public, anon;
grant execute on function public.send_test_notify() to authenticated;
