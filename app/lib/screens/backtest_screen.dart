import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'hitrate_screen.dart';

/// 검증 탭 — 관심종목 적중률만 (탭별 매일 상위 3 → 20일 안에 목표/손절, 연도·분기, 평균 손익)
///   예전 V2 엔진 · V3 기준 전략 · 상세 검증(VALID) 화면은 2026-10-11 뺐다.
///   (계산 코드는 남아 있어 Actions 에서 only=VALID 로 직접 돌릴 수는 있음)
class BacktestScreen extends StatefulWidget {
  const BacktestScreen({super.key});

  @override
  State<BacktestScreen> createState() => _BacktestScreenState();
}

class _BacktestScreenState extends State<BacktestScreen> {
  late Future<Json> _hit = loadHitRate();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
          title: const LogoTitle('검증'),
          actions: topActions(context, onRefresh: () => setState(() => _hit = loadHitRate()))),
      body: RefreshIndicator(
        onRefresh: () async {
          setState(() => _hit = loadHitRate());
          await _hit.catchError((_) => <String, dynamic>{});
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            HitRunCard(onDone: () => setState(() => _hit = loadHitRate())),
            HitRateSection(future: _hit),
          ],
        ),
      ),
    );
  }
}
