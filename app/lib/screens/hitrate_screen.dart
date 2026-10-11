import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets/common.dart';

/// 관심종목 적중률 (HIT-1.0) — 검증 탭 맨 위
///   탭마다 매일 점수 상위 3 → 다음 날 시가 매수 → 20거래일 안에 1·2·3차 목표 / 손절 / 보합
///   연도별 표 → 연도를 누르면 분기, 칸(1·2·3차·손절)을 누르면 며칠째에 닿았는지 1~20일 분포
Future<Json> loadHitRate() => Api.latestBacktest(strategy: 'HIT');

const _cols = [('t1', '1차'), ('t2', '2차'), ('t3', '3차'), ('stop', '손절'), ('flat', '보합')];
const _tabs = [('v3', 'V3'), ('nextday', '익일유망주'), ('early', '상승초기'), ('reversal', '추세전환'), ('uplimit', '상파')];

Color _colOf(String k) => switch (k) {
      't1' || 't2' || 't3' => const Color(0xFFD32F2F),
      'stop' => const Color(0xFF1565C0),
      _ => Colors.grey,
    };

class HitRateSection extends StatefulWidget {
  const HitRateSection({super.key, required this.future});
  final Future<Json> future;

  @override
  State<HitRateSection> createState() => _HitRateSectionState();
}

class _HitRateSectionState extends State<HitRateSection> {
  String _tab = 'v3';
  final Set<String> _open = {}; // 펼친 연도

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return FutureBuilder<Json>(
      future: widget.future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
        }
        final r = snap.data;
        final tabs = asMap(r?['tabs']);
        if (r == null || tabs.isEmpty) {
          return Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text('아직 적중률 결과가 없어요. 매주 토요일 주간 배치가 계산합니다. 지금 보려면 Actions → weekly-backtest → '
                  'Run workflow 에서 칸에 HIT 를 넣고 실행하세요. (탭·연도 일부: HIT:nextday · HIT:2025 · HIT:early:2024,2025)',
                  style: t.bodySmall),
            ),
          );
        }
        if (!tabs.containsKey(_tab)) _tab = tabs.keys.first;
        final v = asMap(tabs[_tab]);
        final years = asMap(v['years']);
        final ys = years.keys.toList()..sort((a, b) => b.compareTo(a)); // 최근 연도 먼저
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SectionTitle('관심종목 적중률', trailing: Text('${r['end'] ?? ''} 기준', style: t.bodySmall)),
          Text('탭마다 매일 상위 3종목 → 다음 날 시가 매수 → 20거래일 안에 차트 목표가·손절가 중 어디에 닿았나. '
              '승률 = 목표 ÷ (목표 + 손절). 연도를 누르면 분기, 숫자를 누르면 며칠째에 닿았는지 보여요.',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 4, children: [
            for (final x in _tabs)
              if (tabs.containsKey(x.$1))
                ChoiceChip(label: Text(x.$2), selected: _tab == x.$1, onSelected: (_) => setState(() => _tab = x.$1)),
          ]),
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 6, 8, 10),
              child: Column(children: [
                _header(context),
                _row(context, '전체', asMap(v['total']), bold: true, title: '${v['name']} 전체'),
                const Divider(height: 8),
                for (final y in ys) ...[
                  _row(context, y, asMap(years[y]),
                      title: '${v['name']} $y년',
                      expand: () => setState(() => _open.contains(y) ? _open.remove(y) : _open.add(y)),
                      expanded: _open.contains(y)),
                  if (_open.contains(y))
                    for (final q in const ['Q1', 'Q2', 'Q3', 'Q4'])
                      if (asMap(asMap(years[y])['quarters'])[q] != null)
                        _row(context, '  ${q.substring(1)}분기', asMap(asMap(asMap(years[y])['quarters'])[q]),
                            title: '${v['name']} $y년 ${q.substring(1)}분기', sub: true),
                  const Divider(height: 6),
                ],
              ]),
            ),
          ),
        ]);
      },
    );
  }

  Widget _header(BuildContext context) {
    final s = Theme.of(context).textTheme.labelSmall?.copyWith(fontWeight: FontWeight.bold);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        SizedBox(width: 58, child: Text('년도', style: s)),
        for (final c in _cols) Expanded(child: Text(c.$2, textAlign: TextAlign.right, style: s)),
        Expanded(child: Text('승률', textAlign: TextAlign.right, style: s)),
      ]),
    );
  }

  /// 한 줄: 연도(또는 분기) · 1·2·3차 · 손절 · 보합 · 승률, 아래에 코스피 등락·이슈
  Widget _row(BuildContext context, String label, Json s,
      {bool bold = false, bool sub = false, String title = '', VoidCallback? expand, bool expanded = false}) {
    final t = Theme.of(context).textTheme;
    if ((s['n'] ?? 0) == 0) return const SizedBox.shrink();
    final base = (sub ? t.bodySmall : t.bodyMedium)?.copyWith(fontWeight: bold ? FontWeight.bold : null);
    final issue = s['issue'] as String?;
    final kospi = s['kospi'] as num?;
    return InkWell(
      onTap: expand,
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: sub ? 3 : 5),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            SizedBox(
              width: 58,
              child: Row(children: [
                Flexible(child: Text(label, style: base, overflow: TextOverflow.ellipsis)),
                if (expand != null) Icon(expanded ? Icons.expand_less : Icons.expand_more, size: 14, color: Colors.grey),
              ]),
            ),
            for (final c in _cols)
              Expanded(
                child: InkWell(
                  onTap: c.$1 == 'flat' ? null : () => _showDays(context, title, c.$1, c.$2, s),
                  child: Text('${(s[c.$1] as num?)?.toStringAsFixed(0) ?? '-'}%',
                      textAlign: TextAlign.right,
                      style: base?.copyWith(
                          color: _colOf(c.$1),
                          decoration: c.$1 == 'flat' ? null : TextDecoration.underline,
                          decorationStyle: TextDecorationStyle.dotted)),
                ),
              ),
            Expanded(
              child: Text(s['win'] == null ? '-' : '${(s['win'] as num).toStringAsFixed(0)}%',
                  textAlign: TextAlign.right, style: base?.copyWith(fontWeight: FontWeight.bold)),
            ),
          ]),
          if ((issue != null && issue.isNotEmpty) || kospi != null)
            Padding(
              padding: const EdgeInsets.only(left: 4, top: 1),
              child: Text(
                  [
                    if (kospi != null) '코스피 ${kospi >= 0 ? '+' : ''}${kospi.toStringAsFixed(1)}%',
                    if (issue != null && issue.isNotEmpty) issue,
                    '${s['n']}건',
                  ].join(' · '),
                  style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: sub ? 10 : 11)),
            ),
        ]),
      ),
    );
  }

  /// 칸을 누르면: 그 결과(1·2·3차 목표 / 손절)에 처음 닿은 날 1~20일 분포
  void _showDays(BuildContext context, String title, String key, String name, Json s) {
    final days = (asMap(s['days'])[key] as List? ?? const []).map((e) => (e as num).toInt()).toList();
    final total = days.fold<int>(0, (a, b) => a + b);
    final n = (s['n'] as num?)?.toInt() ?? 0;
    final mx = days.isEmpty ? 1 : days.reduce((a, b) => a > b ? a : b).clamp(1, 1 << 30);
    final col = _colOf(key);
    final cums = <int>[];
    for (final d in days) {
      cums.add((cums.isEmpty ? 0 : cums.last) + d);
    }
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('$title · $name 에 처음 닿은 날', style: Theme.of(ctx).textTheme.titleSmall),
            Text('$n건 중 $total건 (${n == 0 ? 0 : (total / n * 100).toStringAsFixed(1)}%)',
                style: Theme.of(ctx).textTheme.bodySmall),
            const SizedBox(height: 10),
            for (var i = 0; i < days.length; i++)
              Builder(builder: (_) {
                final cum = cums[i];
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(children: [
                    SizedBox(width: 42, child: Text('${i + 1}일째', style: const TextStyle(fontSize: 12))),
                    Expanded(
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: FractionallySizedBox(
                          widthFactor: days[i] / mx,
                          child: Container(height: 12, color: col.withValues(alpha: 0.7)),
                        ),
                      ),
                    ),
                    SizedBox(
                      width: 96,
                      child: Text('${days[i]}건 · 누적 ${total == 0 ? 0 : (cum / total * 100).toStringAsFixed(0)}%',
                          textAlign: TextAlign.right, style: const TextStyle(fontSize: 11)),
                    ),
                  ]),
                );
              }),
          ]),
        ),
      ),
    );
  }
}
