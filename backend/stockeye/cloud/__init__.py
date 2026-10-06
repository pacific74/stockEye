"""클라우드 운영 (Supabase).

  client.py   Supabase REST(DB) + Storage 호출
  sync.py     parquet 원본 데이터를 Storage 와 주고받기 (연도별 분할)
  journal.py  매매일지/주문을 Supabase 표에 저장 (SQLite Journal 과 같은 사용법)
  publish.py  리포트·종목 상세·백테스트·매매 분석을 앱이 읽는 표에 발행

환경변수 (배치를 돌리는 곳에만 — GitHub Secrets 또는 VM 의 /etc/stockeye.env):
  SUPABASE_URL          https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY  service_role 키 (절대 앱/웹에 넣지 말 것)
  SUPABASE_USER_ID      내 계정의 User UID (Authentication → Users)
"""
