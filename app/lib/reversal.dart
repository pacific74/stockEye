import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 추세전환 (실험 탭 · 관찰용) — 바닥에서 20일선이 수평 → 상승으로 도는 종목, 100점 (소수점 점수)
///   ① 하락·바닥 15 ② 바닥 횡보 25 ③ 이평 전환 35 ④ 초기 반등 15 ⑤ 거래량·변동성 10
///   70점 이상 후보 · 80점 이상 우선 관찰 · 매매 규칙 없음 (V3 기준 전략과 별개)

/// 실험 탭 설정: 후보 dict 의 필드 · 항목 순서 · 이름 · 기준 설명
class ExpKind {
  const ExpKind(this.field, this.title, this.parts, this.note);
  final String field, title, note;
  final List<String> parts;
}

const reversalKind = ExpKind('reversal', '추세전환', ['bottom15', 'base25', 'ma35', 'rebound15', 'volume10'],
    '기준 사이를 직선으로 이어 소수점까지 계산 · 70점 이상 후보 · 80점 이상 우선 관찰 · 관찰용 (매매 규칙 없음)');

/// 상승초기형 V1: 20일선 회복 + 단기 상승 시작
const earlyKind = ExpKind('early', '상승초기', ['trend25', 'mom20', 'mid20', 'vol20', 'risk15'],
    '기준 사이를 직선으로 이어 소수점까지 계산 · 80↑ 우선 관찰 · 70~79 관찰 후보 · 60~69 보류 · 관찰용 (매매 규칙 없음)');

const reversalParts = ['bottom15', 'base25', 'ma35', 'rebound15', 'volume10'];

Color reversalColor(num? s) => s == null
    ? Colors.grey
    : s >= 80
        ? Colors.deepPurple
        : s >= 70
            ? Colors.indigo
            : Colors.blueGrey;

Widget _chip(String s, Color color) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(6)),
      child: Text(s, style: TextStyle(fontSize: 11, color: color)),
    );

/// 목록 한 줄: 총점(소수점) · 판정 · 5개 항목
class ReversalTile extends StatelessWidget {
  const ReversalTile({super.key, required this.c, required this.rank, this.kind = reversalKind});
  final Json c;
  final int rank;
  final ExpKind kind;

  @override
  Widget build(BuildContext context) {
    final v = asMap(c[kind.field]);
    final parts = asMap(v['parts']), labels = asMap(v['labels']), maxes = asMap(v['maxes']);
    final score = v['score'] as num?;
    final col = reversalColor(score);
    final plan = asMap(c['plan']);
    final t = Theme.of(context).textTheme;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        leading: CircleAvatar(child: Text('$rank')),
        title: StockName('${c['name']}', market: c['market'] as String?),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const SizedBox(height: 2),
          Wrap(spacing: 4, runSpacing: 2, children: [
            for (final k in kind.parts)
              _chip('${labels[k] ?? k} ${(parts[k] as num?)?.toStringAsFixed(1) ?? '-'}/${maxes[k] ?? ''}', Colors.indigo),
          ]),
          const SizedBox(height: 2),
          Text('기준가 ${num0(plan['price'] as num?)} · ${v['label'] ?? ''}', style: t.bodySmall),
        ]),
        isThreeLine: true,
        trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(score == null ? '-' : '${score.toStringAsFixed(1)}점',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: col)),
          Text('${v['label'] ?? ''}', style: t.bodySmall?.copyWith(color: col)),
        ]),
        onTap: () => Navigator.push(context,
            MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${c['code']}', name: '${c['name']}'))),
      ),
    );
  }
}

/// 종목 상세: 추세전환 점수 5개 항목 막대 + 세부 14개 (펼쳐 보기)
class ReversalScore extends StatelessWidget {
  const ReversalScore({super.key, required this.v, this.kind = reversalKind});
  final Json v;
  final ExpKind kind;

  Widget _bar(String label, num? got, num max, {bool small = false}) => Padding(
        padding: EdgeInsets.symmetric(vertical: small ? 1 : 3),
        child: Row(children: [
          SizedBox(width: small ? 128 : 96, child: Text(label, style: TextStyle(fontSize: small ? 12 : null))),
          Expanded(
            child: LinearProgressIndicator(
              value: got == null ? 0 : (got / max).clamp(0, 1).toDouble(),
              minHeight: small ? 5 : 8,
              color: small ? Colors.indigo.shade200 : Colors.indigo,
              borderRadius: BorderRadius.circular(4),
            ),
          ),
          SizedBox(
            width: 70,
            child: Text(got == null ? '데이터없음' : '${got.toStringAsFixed(small ? 2 : 1)}/$max',
                textAlign: TextAlign.right, style: const TextStyle(fontSize: 12)),
          ),
        ]),
      );

  static String excl(Json v) {
    final ex = v['excluded'];
    return (ex is List && ex.isNotEmpty) ? ' (제외: ${ex.join(', ')})' : ' (매수 차단·1차 필터로 목록 제외)';
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final parts = asMap(v['parts']), labels = asMap(v['labels']), maxes = asMap(v['maxes']);
    final subs = asList(v['subs']);
    final score = v['score'] as num?;
    final col = reversalColor(score);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${kind.title} ${score == null ? '-' : score.toStringAsFixed(1)}점 · ${v['label'] ?? ''}'
          '${v['eligible'] == true ? '' : excl(v)}',
          style: t.bodySmall?.copyWith(fontWeight: FontWeight.w600, color: col)),
      for (final k in kind.parts) _bar('${labels[k] ?? k}', parts[k] as num?, (maxes[k] as num?) ?? 1),
      if (subs.isNotEmpty)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            dense: true,
            title: Text('세부 항목 ${subs.length}개', style: t.bodySmall),
            children: [
              for (final s in subs) _bar('${s['label']}', s['score'] as num?, (s['max'] as num?) ?? 1, small: true),
            ],
          ),
        ),
      Text('${kind.note} ${v['version'] ?? ''}',
          style: t.bodySmall),
    ]);
  }
}
