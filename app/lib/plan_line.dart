import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'widgets/common.dart';

/// 후보 카드 아래 한 줄: 매수구간 여부 칩 + "지금 사면 목표 +x% · 손절 -y% · 손익비 1:z"
///   가격 = 지금 시세(있으면) 또는 분석일 종가. 목표 = 1차 목표가, 손절 = 손절가 (차트 지지·저항 기준)
class PlanStatus {
  PlanStatus(this.zone, this.color, this.up, this.down);
  final String zone;
  final Color color;
  final double? up; // 가격 → 1차 목표 (%)
  final double? down; // 가격 → 손절 (%, 음수)
  double? get rr => (up == null || down == null || down! >= 0) ? null : up! / -down!;

  static PlanStatus? of(Json c, double? price) {
    final p = asMap(c['plan']);
    double? v(String k) => (p[k] as num?)?.toDouble();
    final px = price ?? v('price');
    final lo = v('entry_low'), hi = v('entry_high'), t1 = v('target1'), st = v('stop');
    if (px == null || px <= 0) return null;
    String zone;
    Color color;
    if (st != null && px <= st) {
      zone = '손절가 아래';
      color = downColor;
    } else if (lo != null && hi != null && px >= lo && px <= hi) {
      zone = '매수구간 안';
      color = Colors.green;
    } else if (hi != null && px > hi && px <= hi * 1.02) {
      zone = '구간 바로 위';
      color = Colors.orange;
    } else if (hi != null && px > hi) {
      zone = '구간 위 (추격 주의)';
      color = Colors.grey;
    } else if (lo != null && px < lo) {
      zone = '구간 아래';
      color = Colors.blueGrey;
    } else {
      zone = '구간 정보 없음';
      color = Colors.grey;
    }
    return PlanStatus(zone, color, t1 == null ? null : (t1 / px - 1) * 100, st == null ? null : (st / px - 1) * 100);
  }
}

Widget planChip(String s, Color color) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(6)),
      child: Text(s, style: TextStyle(fontSize: 11, color: color)),
    );

class PlanLine extends StatelessWidget {
  const PlanLine({super.key, required this.c, this.price, this.live = false, this.extraChips = const []});
  final Json c;
  final double? price;
  final bool live; // true = 지금 시세 기준, false = 분석일 종가 기준
  final List<Widget> extraChips;

  @override
  Widget build(BuildContext context) {
    final s = PlanStatus.of(c, price);
    if (s == null) return const SizedBox.shrink();
    final t = Theme.of(context).textTheme;
    final tags = (c['tags'] is List) ? (c['tags'] as List).map((e) => '$e').toList() : <String>[];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 3),
      Wrap(spacing: 4, runSpacing: 2, children: [
        planChip(s.zone, s.color),
        ...extraChips,
        for (final tg in tags.take(2)) planChip(strategyLabels[tg] ?? tg, Colors.blueGrey),
      ]),
      if (s.up != null && s.down != null)
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Text(
              '${live ? '지금 사면' : '종가 기준'} 목표 ${pct(s.up)} · 손절 ${pct(s.down)}'
              '${s.rr == null ? '' : ' · 손익비 1:${s.rr!.toStringAsFixed(1)}'}',
              style: t.bodySmall),
        ),
    ]);
  }
}
