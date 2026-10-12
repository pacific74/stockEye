import 'package:flutter/material.dart';

import '../api.dart';
import '../closingbet.dart';
import '../daytrade.dart';
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
  late Future<Json> _dt = loadDaytradeValidation();
  late Future<Json> _cb = loadClosingbetValidation();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
          title: const LogoTitle('검증'),
          actions: topActions(context, onRefresh: () => setState(() {
            _hit = loadHitRate();
            _dt = loadDaytradeValidation();
            _cb = loadClosingbetValidation();
          }))),
      body: RefreshIndicator(
        onRefresh: () async {
          setState(() {
            _hit = loadHitRate();
            _dt = loadDaytradeValidation();
            _cb = loadClosingbetValidation();
          });
          await _hit.catchError((_) => <String, dynamic>{});
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            HitRunCard(onDone: () => setState(() {
            _hit = loadHitRate();
            _dt = loadDaytradeValidation();
            _cb = loadClosingbetValidation();
          })),
            HitRateSection(future: _hit),
            const SizedBox(height: 16),
            // 당일단타: 실전 기록 + 되돌려 보기
            DaytradeValidation(future: _dt),
            const SizedBox(height: 16),
            // 종가배팅: 실전 기록 + 되돌려 보기 (5년 일봉 · 과거 분봉)
            ClosingbetValidation(future: _cb),
          ],
        ),
      ),
    );
  }
}
