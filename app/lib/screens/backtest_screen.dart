import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'hitrate_screen.dart';

/// 검증 탭 — 지난 5년 (2026-10-14: 추천주·시장·업종은 '통계' 탭으로 옮김)
///   추천주   : 날마다 관심 목록에 나온 종목(추천 기록)의 실제 결과 + 승률·손익 통계 (앞으로 쌓이는 진짜 기록)
///   시장·업종 : 당일단타 매수→청산 구간의 시장·업종 흐름과 결과 (2026-10-14 · 시장 필터·진입 시간 조절용)
///   지난 5년 : 관심종목 적중률(과거 되돌려 보기) · 당일단타 · 종가배팅 · 상한가포착 검증 (예전 검증 화면 그대로)
///   예전 V2 엔진 · V3 기준 전략 · 상세 검증(VALID) 화면은 2026-10-11 뺐다.
class BacktestScreen extends StatefulWidget {
  const BacktestScreen({super.key});

  @override
  State<BacktestScreen> createState() => _BacktestScreenState();
}

class _BacktestScreenState extends State<BacktestScreen> {
  int _gen = 0; // 새로고침할 때마다 +1 → 두 탭 다시 만들기

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const LogoTitle('검증 · 지난 5년'),
        actions: topActions(context, onRefresh: () => setState(() => _gen++)),
      ),
      body: _PastTab(key: ValueKey('past$_gen')),
    );
  }
}

/// 지난 5년 — 관심종목 적중률 (2026-10-15 당일단타·종가배팅·상한가포착 검증 뺌)
class _PastTab extends StatefulWidget {
  const _PastTab({super.key});

  @override
  State<_PastTab> createState() => _PastTabState();
}

class _PastTabState extends State<_PastTab> with AutomaticKeepAliveClientMixin {
  late Future<Json> _hit = loadHitRate();

  @override
  bool get wantKeepAlive => true;

  void _reload() => setState(() {
        _hit = loadHitRate();
      });

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return RefreshIndicator(
      onRefresh: () async {
        _reload();
        await _hit.catchError((_) => <String, dynamic>{});
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
        children: [
          HitRunCard(onDone: _reload),
          HitRateSection(future: _hit),
          // 2026-10-15: 당일단타·종가배팅·상한가포착 검증은 뺌 (결과는 통계 > 전체현황)
        ],
      ),
    );
  }
}
