import 'package:flutter/material.dart';

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
      '받을 수 있는 알림: 매일 저녁 리포트 요약 · 내 보유종목 경고 · 장중 매수 신호(켤 때만)',
      '토픽 이름은 비밀번호처럼 남에게 알려주지 마세요.',
    ]),
    (Icons.view_carousel_outlined, '화면 안내 (아래 메뉴)', [
      '오늘: 지금 시세 기준 — 코스피·코스닥, 오늘 살 만한 후보(지금 가격이 매수구간 근처), TOP10 지금 가격, 내 보유종목 손익, 돈이 몰리는 업종(오늘 | 어제). 장중 1분마다 자동 갱신',
      '후보: [지금 매수구간] = 어제 분석 후보 중 지금 가격으로 살 만한 종목, 나머지 탭 = 어제 장 마감 분석의 상승 후보·전략별 후보(목록마다 점수 높은 순 10개)',
      '차트: 캔들 + 이동평균선(5·20·60·120일) + 아래 거래량, 오른쪽에 가격 눈금',
      '보유: 내가 산 종목 기록과 매일 저녁 점검 (손절·목표·추세)',
      '일지: 매매 기록과 내 매매 분석 (승률·손익비·습관)',
      '백테스트(관리자만): 각 전략을 과거 5년에 적용한 결과',
      '어느 화면에서든 왼쪽 위 로고를 누르면 첫 화면으로 돌아갑니다.',
    ]),
    (Icons.insights_outlined, '종목 화면 읽는 법', [
      '점수(100점): 추세·거래량·거래대금·수급·돌파·변동성·재무·뉴스를 합친 점수',
      '판정: 매수 고려 / 눌림 대기 / 관심 / 관망',
      '시장 필터: 종목이 속한 시장(코스피/코스닥) 지수가 60일선 아래면 신규 매수를 쉬도록 판정을 "관망"으로 바꾸고, 오늘 살 만한 후보에서도 뺍니다 (5년 백테스트에서 손실·낙폭을 크게 줄인 규칙)',
      '매수 적정구간 · 1차/2차 목표가 · 손절가 · 손익비를 함께 보여줍니다.',
      '비슷한 과거 패턴: 지금 차트와 모양이 비슷했던 과거 구간과 "그 뒤 20일" 흐름을 비교 (참고용)',
    ]),
    (Icons.account_balance_wallet_outlined, '내 보유종목 기록', [
      '종목 화면의 [보유 추가] 또는 보유 탭의 [+ 추가]',
      '그날 점수·전략·손절·목표가 함께 저장되어 나중에 "왜 샀는지"를 볼 수 있어요.',
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
      bottomNavigationBar: showNav ? const MainNavBar() : null,
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
