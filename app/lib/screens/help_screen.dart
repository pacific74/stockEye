import 'package:flutter/material.dart';

import '../version.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';

/// 회원 이용 안내 (로그인 화면 · 승인 대기 화면 · 홈 메뉴에서 열림)
class HelpScreen extends StatelessWidget {
  const HelpScreen({super.key, this.showNav = true});
  final bool showNav; // 로그인 전/승인 대기 화면에서 열 때는 하단 메뉴 없음

  static const _sections = <(IconData, String, List<String>)>[
    (Icons.how_to_reg, '처음 시작하기', [
      '① 로그인 화면에서 [회원가입] → 이메일·비밀번호(8자 이상) 입력',
      '② 받은 메일의 인증 링크 누르기 (안 보이면 스팸함 확인)',
      '③ 다시 로그인 → "관리자 승인을 기다리고 있어요" 화면이 나오면 기다리기',
      '④ 승인되면 [다시 확인] → 바로 이용',
      '팁: 승인 대기 화면의 [승인되면 폰으로 알림 받기]를 해 두면 승인 즉시 알려 드려요.',
    ]),
    (Icons.add_to_home_screen, '앱처럼 쓰기 (홈 화면에 추가)', [
      '안드로이드(크롬): 주소창 오른쪽 ⋮ → [홈 화면에 추가]',
      '아이폰(사파리): 아래 공유 버튼 □↑ → [홈 화면에 추가]',
      '이후 홈 화면의 StockEye 아이콘으로 바로 실행됩니다.',
    ]),
    (Icons.notifications_active_outlined, '휴대폰 알림 받기', [
      '① 폰에 ntfy 앱 설치 (Play 스토어 / App Store 에서 "ntfy")',
      '② StockEye 오른쪽 위 ⋮ → [알림 설정] → 토픽 [복사]',
      '③ ntfy 앱 ＋ 버튼 → 토픽 붙여넣기 → 구독',
      '④ StockEye 에서 [저장] → [테스트 알림 보내기]',
      '받을 수 있는 알림: 매일 저녁 V3 요약(선정일·매수/매도 예정일·상위 3) · 내 보유종목 매도 예정일 임박',
      '토픽 이름은 비밀번호처럼 남에게 알려주지 마세요.',
    ]),
    (Icons.view_carousel_outlined, '화면 안내 (아래 메뉴)', [
      '오늘: V3 기준 전략 카드, 코스피·코스닥, V3 상위 10 지금 가격, 내 보유종목 손익·매도 예정일, 돈이 몰리는 업종(오늘 | 어제). 장중 1분마다 자동 갱신',
      '후보: V3B 상위 10 — 선정일이면 매수일(다음 거래일 시가)과 매도 예정일, 아니면 참고 순위와 다음 선정일',
      '차트: 캔들 + 이동평균선(5·20·60·120일) + 아래 거래량, 오른쪽에 가격 눈금',
      '보유: 내가 산 종목 기록과 V3 기준 매도 예정일 (매수일 포함 20거래일째), 3거래일 안이면 알림',
      '일지: 매매 기록과 내 매매 분석 (승률·손익비·습관)',
      '백테스트(관리자만): V3 기준 전략 검증 — ① 종목 선정력 ② 실제 매매를 나눠서',
      '어느 화면에서든 왼쪽 위 로고를 누르면 첫 화면으로 돌아갑니다.',
    ]),
    (Icons.insights_outlined, '종목 화면 읽는 법', [
      'V3 기준 전략 (규칙 고정): V3B 점수 = (변동성 15 + 재무 25 + 가격위치 20) ÷ 60 × 100 — 화면은 100점 환산, 추세·거래량·거래대금·수급·공시는 참고로만 표시',
      '변동성이 낮을수록 · 재무가 좋을수록 · 20·60일선이나 지지선 근처에서 조정 중일수록 점수가 높습니다',
      '자격: 매수 차단(관리종목·감사의견·횡령배임·대규모 유상증자·거래대금 부족·자본잠식 등) 없음 · 과열 아님 · 60일선이 급락 중이 아님',
      '5거래일마다 상위 10개 선정 → 다음 거래일 시가 매수 → 매수일 포함 20거래일째 종가 매도 (손절·익절 없음)',
      '보유 중인 종목이 다시 상위 10 에 들면 20거래일 연장, 추가매수는 하지 않습니다. 최대 20종목 · 종목당 5%',
      '추세·거래량 점수를 크게 주던 예전 방식(V2)은 검증에서 오히려 수익이 낮아 화면에서 뺐습니다',
      '비슷한 과거 패턴: 지금 차트와 모양이 비슷했던 과거 구간과 "그 뒤 20일" 흐름을 비교 (참고용)',
    ]),
    (Icons.account_balance_wallet_outlined, '내 보유종목 기록', [
      '종목 화면의 [보유 추가] 또는 보유 탭의 [+ 추가]',
      '매수일을 기준으로 V3 매도 예정일(20거래일째)을 계산해 보여줍니다. 종목 화면의 목표가·손절가는 참고용입니다(V3 규칙엔 손절·익절 없음).',
      '팔았으면 [매도 기록] → 수익률·보유기간·결과가 매매일지에 자동 기록',
      '내 기록은 나만 볼 수 있습니다.',
    ]),
    (Icons.warning_amber_rounded, '꼭 알아 두세요', [
      'StockEye 는 통계·규칙 기반의 참고 도구이며 매수·매도 권유가 아닙니다.',
      '과거 백테스트·유사 패턴 결과가 미래 수익을 보장하지 않습니다.',
      '투자 판단과 결과의 책임은 본인에게 있습니다.',
      '분석(후보·점수)은 평일 장 마감 후 저녁에 갱신되고, 메인 화면의 지금 시세는 네이버 금융 실시간 시세입니다.',
    ]),
  ];

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      bottomNavigationBar: showNav ? const MainNavBar() : const VersionFooter(),
      appBar: AppBar(
          title: showNav ? const LogoTitle('이용 안내') : const Text('이용 안내'),
          actions: showNav ? topActions(context) : null),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 32),
        children: [
          for (final (icon, title, lines) in _sections)
            Card(
              child: Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  initiallyExpanded: title == '처음 시작하기',
                  leading: Icon(icon),
                  title: Text(title, style: t.titleSmall),
                  childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                  expandedCrossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final l in lines.where((l) => canSeeBacktest || !l.startsWith('백테스트')))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 3),
                        child: Text(l, style: t.bodyMedium?.copyWith(height: 1.4)),
                      ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
