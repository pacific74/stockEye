import 'package:flutter/material.dart';

import '../overview_tab.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';

/// 통계 탭 (관리자만 · 2026-10-14 검증에서 옮김)
///   전체현황 : 점수대(90~·80~·70~·60~) × 구분별 추천 결과 표 (2026-10-15 · 추천 유효기간 다음 거래일 하루)
///   당일단타 : 점수별 당일단타만 + 매수시간별(09:00~10:00 10분 단위 × 점수) 결과 표
///   종가배팅 : 점수대별 종가배팅 결과 + NXT 애프터마켓 · 다음 날 프리마켓 상승 비율 (2026-10-15 · 시장·업종 탭은 뺌)
class StatsScreen extends StatefulWidget {
  const StatsScreen({super.key});

  @override
  State<StatsScreen> createState() => _StatsScreenState();
}

class _StatsScreenState extends State<StatsScreen> {
  int _gen = 0; // 새로고침할 때마다 +1 → 두 탭 다시 만들기

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const LogoTitle('통계'),
          actions: topActions(context, onRefresh: () => setState(() => _gen++)),
          bottom: const TabBar(tabs: [Tab(text: '전체현황'), Tab(text: '당일단타'), Tab(text: '종가배팅')]),
        ),
        body: TabBarView(children: [
          OverviewTab(key: ValueKey('ov$_gen')),
          OverviewTab(key: ValueKey('dt$_gen'), daytrade: true),
          OverviewTab(key: ValueKey('cb$_gen'), closingbet: true),
        ]),
      ),
    );
  }
}
