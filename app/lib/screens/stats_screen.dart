import 'package:flutter/material.dart';

import '../intraday_ctx.dart';
import '../recommend.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';

/// 통계 탭 (관리자만 · 2026-10-14 검증에서 옮김)
///   추천주   : 날마다 관심 목록에 나온 종목(추천 기록)의 실제 결과 + 승률·손익 통계
///   시장·업종 : 당일매매 매수→청산 구간의 시장·업종 흐름과 결과 (시장 필터·진입 시간 조절용)
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
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const LogoTitle('통계'),
          actions: topActions(context, onRefresh: () => setState(() => _gen++)),
          bottom: const TabBar(tabs: [Tab(text: '추천주'), Tab(text: '시장·업종')]),
        ),
        body: TabBarView(children: [
          RecTab(key: ValueKey('rec$_gen')),
          IntradayCtxTab(key: ValueKey('ctx$_gen')),
        ]),
      ),
    );
  }
}
