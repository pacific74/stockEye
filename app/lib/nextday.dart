import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'plan_line.dart';
import 'reversal.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 익일 유망주 V1 (실험 탭 · 관찰용) — 장 마감 데이터로 다음 거래일 움직임 후보
///   A 추세 25 · B 거래량 20 · C 가격 구조 20 · D 변동성 15 · E 시장 대비 10 · F 재료·위험 10
///   등급 A 80↑ 우선 관찰 · B 70~79 관심 · C 60~69 보조. 전날 점수와 장중 상태는 따로 보여줌.

const nextdayKind = ExpKind('nextday', '익일 유망주', ['trendA', 'volB', 'priceC', 'movD', 'rsE', 'newsF'],
    '기준 사이를 직선으로 이어 소수점까지 계산 · A 80↑ 우선 관찰 · B 70~79 관심 · C 60~69 보조 · 관찰용 (갭 추격 매수 아님)');

Color gradeColor(String? g) => switch (g) {
      'A' => Colors.deepPurple,
      'B' => Colors.indigo,
      'C' => Colors.blueGrey,
      _ => Colors.grey,
    };

Color liveColor(String? s) => switch (s) {
      '돌파' => Colors.red,
      '갭 추격 금지' => Colors.orange,
      '무효화 (지지 이탈)' => Colors.blue,
      '지지선 근처' => Colors.teal,
      _ => Colors.grey,
    };

Widget _chip(String s, Color color) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(6)),
      child: Text(s, style: TextStyle(fontSize: 11, color: color)),
    );

String _pct(num? v) => v == null ? '-' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(1)}%';

/// 목록 한 줄: 등급·유형·점수 + (장중이면) 지금 상태
class NextdayTile extends StatelessWidget {
  const NextdayTile({super.key, required this.c, required this.rank, this.price});
  final Json c;
  final int rank;
  final double? price;

  @override
  Widget build(BuildContext context) {
    final v = asMap(c['nextday']);
    final w = asMap(v['watch']);
    final live = asMap(v['live']);
    final tags = (v['tags'] is List) ? (v['tags'] as List).map((e) => '$e').toList() : <String>[];
    final score = v['score'] as num?;
    final col = gradeColor(v['grade'] as String?);
    final t = Theme.of(context).textTheme;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        leading: CircleAvatar(
            backgroundColor: col.withValues(alpha: 0.15),
            child: Text('${v['grade'] ?? rank}', style: TextStyle(color: col, fontWeight: FontWeight.bold))),
        title: StockName('${c['name']}', market: c['market'] as String?),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const SizedBox(height: 2),
          Wrap(spacing: 4, runSpacing: 2, children: [
            _chip('${v['type'] ?? ''}', col),
            for (final tg in tags) _chip(tg, Colors.orange),
          ]),
          const SizedBox(height: 2),
          if (live.isNotEmpty)
            Text('${live['time']} 지금 ${num0(live['price'] as num?)} (${_pct(live['chg'] as num?)}) · 시초 갭 ${_pct(live['gap'] as num?)} · ${live['status']}',
                style: t.bodySmall?.copyWith(color: liveColor(live['status'] as String?), fontWeight: FontWeight.w600))
          else if (w.isNotEmpty)
            Text('종가 ${num0(w['close'] as num?)} · 돌파 ${num0(w['breakout'] as num?)} · 지지 ${num0(w['support'] as num?)} · '
                '추격 금지 ${num0(w['no_chase'] as num?)}↑', style: t.bodySmall),
          PlanLine(c: c, price: price, live: price != null, showPrice: true),
        ]),
        isThreeLine: true,
        trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(score == null ? '-' : '${score.toStringAsFixed(1)}점',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: col)),
        ]),
        onTap: () => Navigator.push(context,
            MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${c['code']}', name: '${c['name']}', source: 'nextday'))),
      ),
    );
  }
}

/// 탭 위 요약: 등급 수 · 유형 · 최근 후보의 다음 날 결과
class NextdaySummary extends StatelessWidget {
  const NextdaySummary({super.key, required this.meta});
  final Json meta;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final g = asMap(meta['grades']);
    final results = asList(meta['results']);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${meta['as_of'] ?? ''} 장 마감 기준 → 다음 거래일 관찰'
              '${meta['live_time'] != null ? ' · ${meta['live_time']} 지금 상태 표시 (점수는 전날 그대로)' : ''}',
              style: const TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          Wrap(spacing: 6, children: [
            _chip('A 우선 ${g['A'] ?? 0}', gradeColor('A')),
            _chip('B 관심 ${g['B'] ?? 0}', gradeColor('B')),
            _chip('C 보조 ${g['C'] ?? 0}', gradeColor('C')),
          ]),
          if (meta['has_disclosures'] == false)
            Text('공시 자료를 받지 못해 재료 점수는 모두 중립(5점)입니다.', style: t.bodySmall?.copyWith(color: Colors.orange)),
          if (results.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('최근 후보의 다음 날 결과 (상위 30개 평균)', style: t.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
            for (final r in results.take(5))
              Text(
                  '${r['date']}→${r['next']}: 갭 ${_pct(asMap(r['avg'])['gap'] as num?)} · 시가→종가 ${_pct(asMap(r['avg'])['oc'] as num?)} '
                  '· 종가→종가 ${_pct(asMap(r['avg'])['cc'] as num?)} (상승 ${r['win_cc']}%) · 장중 최고 ${_pct(asMap(r['avg'])['mfe'] as num?)}',
                  style: t.bodySmall),
          ],
        ]),
      ),
    );
  }
}

/// 종목 상세: 등급·유형·관찰 계획 + 점수 구성
class NextdayCard extends StatelessWidget {
  const NextdayCard({super.key, required this.v});
  final Json v;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final w = asMap(v['watch']);
    final live = asMap(v['live']);
    final lines = (w['lines'] is List) ? (w['lines'] as List).map((e) => '$e').toList() : <String>[];
    final col = gradeColor(v['grade'] as String?);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${v['label'] ?? ''} · ${v['type'] ?? ''}${v['check'] != null ? ' — 확인: ${v['check']}' : ''}',
          style: t.bodyMedium?.copyWith(color: col, fontWeight: FontWeight.w600)),
      if (live.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('${live['time']} 지금 ${num0(live['price'] as num?)} (${_pct(live['chg'] as num?)}) · 시초 갭 ${_pct(live['gap'] as num?)} → ${live['status']}',
              style: t.bodyMedium?.copyWith(color: liveColor(live['status'] as String?), fontWeight: FontWeight.w600)),
        ),
      if (lines.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text('다음 거래일 관찰 계획', style: t.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
        for (final l in lines) Text('· $l', style: t.bodySmall),
        Text('전일 종가 ${num0(w['close'] as num?)} · 고가 ${num0(w['high'] as num?)} · 저가 ${num0(w['low'] as num?)} · '
            '20일선 ${num0(w['ma20'] as num?)} · 60일선 ${num0(w['ma60'] as num?)} · 박스 상단 ${num0(w['box_top'] as num?)}',
            style: t.bodySmall?.copyWith(color: Colors.grey)),
      ],
      const SizedBox(height: 6),
      ReversalScore(v: v, kind: nextdayKind),
    ]);
  }
}
