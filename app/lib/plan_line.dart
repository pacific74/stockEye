import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'nextday.dart' show gradeColor, liveColor;
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
  const PlanLine(
      {super.key, required this.c, this.price, this.live = false, this.extraChips = const [], this.showPrice = false, this.tab});
  final Json c;
  final double? price;
  final bool live; // true = 지금 시세 기준, false = 분석일 종가 기준
  final List<Widget> extraChips;
  final bool showPrice; // (예전) 관심 탭 목록 — 현재가는 이제 카드 오른쪽 위(WatchTile), 매수구간은 상태 칩 옆
  final String? tab; // 어느 탭 종목인지 → 탭별 유형·태그 칩과 확인 가격 줄

  @override
  Widget build(BuildContext context) {
    final s = PlanStatus.of(c, price);
    if (s == null) return const SizedBox.shrink();
    final tags = (c['tags'] is List) ? (c['tags'] as List).map((e) => '$e').toList() : <String>[];
    final p = asMap(c['plan']);
    final lo = p['entry_low'] as num?, hi = p['entry_high'] as num?;
    final zoneTxt = lo != null && hi != null ? '${num0(lo)}~${num0(hi)}' : null;
    final alert = c['market_alert'] as String?;
    final tc = tabChipTexts(c, tab);
    final seen = tc.map((e) => e.$1).toSet();
    final chips = [for (final x in tc) planChip(x.$1, x.$2)];
    final watch = tabWatch(context, c, tab);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      // 지수·업종 급락 → 매수 주의
      if (alert != null)
        Padding(padding: const EdgeInsets.only(top: 3), child: InfoBox('⚠ $alert', color: Colors.orange, bold: true, fill: true)),
      const SizedBox(height: 3),
      // 한 줄: 매수구간 상태 + 탭별 유형·태그 (같은 글자는 한 번만)
      infoBoxes([
        planChip(s.zone, s.color),
        // 매수구간 칩 옆에 구간 가격
        if (zoneTxt != null) InfoBox('매수구간 $zoneTxt', color: s.color),
        ...chips,
        ...extraChips,
        for (final tg in tags.where((x) => !seen.contains(x)).take(2)) planChip(strategyLabels[tg] ?? tg, Colors.blueGrey),
      ]),
      if (watch != null) Padding(padding: const EdgeInsets.only(top: 3), child: watch),
      if (s.up != null && s.down != null)
        Padding(
          padding: const EdgeInsets.only(top: 3),
          child: infoBoxes([
            InfoBox('목표 ${pct(s.up)}', color: upColor),
            InfoBox('손절 ${pct(s.down)}', color: downColor),
            if (s.rr != null) InfoBox('손익비 1:${s.rr!.toStringAsFixed(1)}'),
          ]),
        ),
    ]);
  }
}

/// 관심 탭 목록 카드 (V3 · 익일유망주 · 상승초기 · 추세전환 · 상파 공통)
///   [순위]  종목명 [시장]                 현재가 48,300원
///                                          84.8점
///          [업종 급락 주의] / [매수구간 안] [매수구간 47,400~48,800] / [목표] [손절] [손익비]
///   아래 줄들은 카드 오른쪽 끝까지 써서 한 줄에 들어가게
class WatchTile extends StatelessWidget {
  const WatchTile(
      {super.key, required this.c, required this.leading, required this.score, this.price, this.tab, this.onTap});
  final Json c;
  final Widget leading;
  final Widget score;
  final double? price; // 지금 시세 (없으면 분석일 종가)
  final String? tab;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final px = price ?? (asMap(c['plan'])['price'] as num?)?.toDouble();
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            leading,
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: StockName('${c['name']}', market: c['market'] as String?, style: t.titleMedium),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                    if (px != null)
                      Text.rich(TextSpan(children: [
                        TextSpan(text: price != null ? '현재가 ' : '기준가 ', style: t.bodySmall?.copyWith(color: Colors.grey)),
                        TextSpan(text: won(px), style: t.bodyMedium?.copyWith(fontWeight: FontWeight.bold)),
                      ])),
                    score,
                  ]),
                ]),
                PlanLine(c: c, price: price, live: price != null, tab: tab),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}


/// 탭별 유형·태그·경고 칩 글자와 색 (관심 목록 · 메인 금일 관심주 · 종목 상세 공통)
List<(String, Color)> tabChipTexts(Json c, String? tab) {
  final out = <(String, Color)>[];
  if (tab == 'nextday') {
    final v = asMap(c['nextday']);
    if (v.isEmpty) return out;
    if (v['type'] != null) out.add(('${v['type']}', gradeColor(v['grade'] as String?)));
    for (final tg in (v['tags'] as List? ?? const [])) {
      out.add(('$tg', Colors.orange));
    }
  } else if (tab == 'uplimit') {
    final v = asMap(c['uplimit']);
    if (v.isEmpty) return out;
    if (v['label'] != null) out.add(('${v['label']}', Colors.red));
    for (final w in (v['warnings'] as List? ?? const []).take(2)) {
      out.add(('$w'.split(' — ').first, Colors.orange));
    }
    final live = asMap(v['live']);
    if (live.isNotEmpty) out.add(('${live['status']}', Colors.teal));
  }
  // 같은 글자 한 번만
  final seen = <String>{};
  return [for (final x in out) if (seen.add(x.$1)) x];
}

/// 탭별 확인 가격 줄: 익일유망주 = 종가·돌파·지지·추격 금지 (장중이면 지금 상태), 상파 = 지지 가격
Widget? tabWatch(BuildContext context, Json c, String? tab) {
  final t = Theme.of(context).textTheme;
  if (tab == 'nextday') {
    final v = asMap(c['nextday']);
    final w = asMap(v['watch']), live = asMap(v['live']);
    String p(num? x) => x == null ? '-' : '${x >= 0 ? '+' : ''}${x.toStringAsFixed(1)}%';
    if (live.isNotEmpty) {
      return Text('${live['time']} 지금 ${num0(live['price'] as num?)} (${p(live['chg'] as num?)}) · 시초 갭 ${p(live['gap'] as num?)} · ${live['status']}',
          style: t.bodySmall?.copyWith(color: liveColor(live['status'] as String?), fontWeight: FontWeight.w600));
    }
    if (w.isEmpty) return null;
    return infoBoxes([
      InfoBox('종가 ${num0(w['close'] as num?)}'),
      InfoBox('돌파 ${num0(w['breakout'] as num?)}', color: upColor),
      InfoBox('지지 ${num0(w['support'] as num?)}', color: downColor),
      InfoBox('추격 금지 ${num0(w['no_chase'] as num?)}↑', color: Colors.orange),
    ]);
  }
  if (tab == 'uplimit') {
    final w = asMap(asMap(c['uplimit'])['watch']);
    if (w['support'] == null) return null;
    return infoBoxes([InfoBox('지지 ${num0(w['support'] as num?)} (${w['support_label'] ?? '상한가 당일 저가'})', color: downColor)]);
  }
  return null;
}
