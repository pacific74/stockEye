-- ============================================================
-- StockEye 스키마 변경분 (2026-10-08, 두 번째)
--   내용: 백테스트 요청은 관리자만 (앱에서도 백테스트 메뉴는 관리자에게만 보임)
--   여러 번 실행해도 안전
-- ============================================================
drop policy if exists "own insert" on public.backtest_requests;
create policy "own insert" on public.backtest_requests for insert to authenticated
  with check (user_id = auth.uid() and public.is_admin() and not exists (
    select 1 from public.backtest_requests b where b.user_id = auth.uid() and b.status in ('queued', 'running')));
