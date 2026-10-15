import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';

/// 통계 > 전체현황 (2026-10-15) — 점수대(90~ · 80~ · 70~ · 60~) × 구분별 추천 결과 표
///   추천 유효기간 = 다음 거래일 하루: 그날 1차 매수구간에서 체결돼야 매수 (못 사면 미체결로 끝)
///   체결 뒤 2·3차 매수 · 1차 50% · 2차 30% · 3차 20% 매도 · 1·2차 뒤 매수가로 돌아오면 매수가매도(전량) · 손절
///   칸 = 체결된 것 중 비율 (괄호 = 평균 보유기간, 체결일 포함 거래일)
///   데이터: 저녁 배치 RECS 의 grid {날짜: {"90|v3": {"d": 완료, "h": 보유중}}} → 고른 기간만 더함
class OverviewTab extends StatefulWidget {
  const OverviewTab({super.key});
  @override
  State<OverviewTab> createState() => _OverviewTabState();
}

const _kinds = [
  ('v3', 'V3'),
  ('nextday', '유망주'),
  ('early', '상승초기'),
  ('reversal', '추세전환'),
  ('uplimit', '상파'),
  ('closingbet', '종가배팅'),
  ('daytrade', '단타'),
  ('limitcatch', '상한가포착'),
];
const _bands = [90, 80, 70, 60];
const _cats = ['t1', 't2', 't3', 'even', 'stop'];

// 칸 너비: 점수 · 구분 · 추천건수 · 체결율 · 1차 · 2차 · 3차 · 매수가매도 · 손절 · 평균손익 · 누적손익
const _wScore = 48.0, _wKind = 84.0, _wN = 64.0, _wFill = 60.0, _wCat = 84.0, _wAvg = 68.0, _wSum = 72.0;
const _rowH = 28.0;
const _tableW = _wScore + _wKind + _wN + _wFill + _wCat * 5 + _wAvg + _wSum;

class _OverviewTabState extends State<OverviewTab> with AutomaticKeepAliveClientMixin {
  late Future<Json> _f = _load();
  String _period = 'all'; // all · year · month
  String? _year, _month; // '2026' · '2026-10'
  String _mode = 'd'; // d 완료 · h 보유중

  @override
  bool get wantKeepAlive => true;

  static Future<Json> _load() => Api.latestBacktest(strategy: 'RECS').catchError((_) => <String, dynamic>{});

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return RefreshIndicator(
      onRefresh: () async => setState(() => _f = _load()),
      notificationPredicate: (n) => n.metrics.axis == Axis.vertical, // 표 안쪽(옆 스크롤 속) 세로 스크롤로 당겨서 새로고침
      child: FutureBuilder<Json>(
        future: _f,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          final grid = asMap((snap.data ?? const {})['grid']);
          final dates = grid.keys.toList()..sort();
          final years = {for (final d in dates) d.substring(0, 4)}.toList()..sort((a, b) => b.compareTo(a));
          final months = {for (final d in dates) d.substring(0, 7)}.toList()..sort((a, b) => b.compareTo(a));
          if (_year == null || !years.contains(_year)) _year = years.isEmpty ? null : years.first;
          if (_month == null || !months.contains(_month)) _month = months.isEmpty ? null : months.first;
          final pick = dates.where((d) => switch (_period) {
                'year' => _year != null && d.startsWith(_year!),
                'month' => _month != null && d.startsWith(_month!),
                _ => true,
              });
          // 기간 안 날짜를 점수대·구분별로 더함
          final sum = <String, Map<String, dynamic>>{};
          for (final d in pick) {
            for (final e in asMap(grid[d]).entries) {
              final m = asMap(asMap(e.value)[_mode]);
              if (m.isEmpty) continue;
              final band = e.key.split('|').first;
              for (final key in [e.key, '$band|all']) {
                final s = sum.putIfAbsent(key, () => {'n': 0, 'f': 0, 'p': 0.0});
                s['n'] = (s['n'] as int) + ((m['n'] as num?)?.toInt() ?? 0);
                s['f'] = (s['f'] as int) + ((m['f'] as num?)?.toInt() ?? 0);
                s['p'] = (s['p'] as double) + ((m['p'] as num?)?.toDouble() ?? 0);
                for (final c in _cats) {
                  final x = m[c];
                  if (x is List && x.length >= 2) {
                    final cur = (s[c] as List<num>?) ?? <num>[0, 0];
                    s[c] = <num>[cur[0] + (x[0] as num), cur[1] + (x[1] as num)];
                  }
                }
              }
            }
          }
          final note = Text(
            '* (괄호) 안은 평균 보유기간 (체결일 포함 거래일). 1·2·3차 · 매수가매도 · 손절 = 체결된 것 중 비율, 나머지는 기간 만료·장 마감 청산.\n'
            '추천 유효기간은 다음 거래일 하루 — 그날 1차 매수구간에서 체결되면 2·3차 매수·분할 매도를 이어 가고, 못 사면 미체결로 끝.\n'
            '단타·종가배팅·상한가포착은 당일매매 추적 결과. 평균·누적 손익은 비용 0.25% 뺀 % (누적 = 건별 손익의 합).',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey, fontSize: 11),
          );
          // 틀 고정: 검색 줄 + 표 머리는 그대로, 아래 표만 위아래로 스크롤 (옆으로는 머리·표가 같이 움직임)
          return Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _filters(context, years, months, dates),
              const SizedBox(height: 8),
              if (dates.isEmpty)
                Expanded(
                  child: ListView(physics: const AlwaysScrollableScrollPhysics(), children: const [
                    Padding(
                      padding: EdgeInsets.all(24),
                      child: Center(child: Text('아직 집계가 없어요 — 오늘 저녁 배치 뒤부터 보여요')),
                    ),
                  ]),
                )
              else
                Expanded(
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: SizedBox(
                      width: _tableW,
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        _header(context),
                        Expanded(
                          child: ListView(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding: const EdgeInsets.only(bottom: 32),
                            children: [
                              for (final b in _bands) _band(context, b, sum),
                              const SizedBox(height: 8),
                              note,
                            ],
                          ),
                        ),
                      ]),
                    ),
                  ),
                ),
            ]),
          );
        },
      ),
    );
  }

  // ---------------------------------------------------------------- 검색 줄: 기간 [전체 · 년 · 월] · 매매구분 [완료 · 보유중]
  Widget _filters(BuildContext context, List<String> years, List<String> months, List<String> dates) {
    final t = Theme.of(context).textTheme;
    Widget label(String s) => Padding(
          padding: const EdgeInsets.only(right: 6),
          child: Text(s, style: t.labelMedium?.copyWith(color: Colors.grey)),
        );
    Widget seg(List<(String, String)> items, String cur, ValueChanged<String> on) => SegmentedButton<String>(
          showSelectedIcon: false,
          style: const ButtonStyle(visualDensity: VisualDensity.compact, tapTargetSize: MaterialTapTargetSize.shrinkWrap),
          segments: [for (final (v, l) in items) ButtonSegment(value: v, label: Text(l))],
          selected: {cur},
          onSelectionChanged: (s) => setState(() => on(s.first)),
        );
    Widget drop(List<String> items, String? cur, String Function(String) text, ValueChanged<String> on) =>
        DropdownButton<String>(
          value: cur,
          isDense: true,
          underline: const SizedBox.shrink(),
          items: [for (final v in items) DropdownMenuItem(value: v, child: Text(text(v)))],
          onChanged: (v) {
            if (v != null) setState(() => on(v));
          },
        );
    return Wrap(spacing: 16, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
      Row(mainAxisSize: MainAxisSize.min, children: [
        label('기간'),
        seg(const [('all', '전체'), ('year', '년'), ('month', '월')], _period, (v) => _period = v),
        if (_period == 'year' && years.isNotEmpty) ...[
          const SizedBox(width: 8),
          drop(years, _year, (v) => '$v년', (v) => _year = v),
        ],
        if (_period == 'month' && months.isNotEmpty) ...[
          const SizedBox(width: 8),
          drop(months, _month, (v) => '${v.substring(0, 4)}년 ${int.parse(v.substring(5))}월', (v) => _month = v),
        ],
        if (_period == 'all' && dates.isNotEmpty) ...[
          const SizedBox(width: 8),
          Text('${dates.first} ~', style: t.bodySmall?.copyWith(color: Colors.grey)),
        ],
      ]),
      Row(mainAxisSize: MainAxisSize.min, children: [
        label('매매구분'),
        seg(const [('d', '완료'), ('h', '보유중')], _mode, (v) => _mode = v),
      ]),
    ]);
  }

  // ---------------------------------------------------------------- 표
  Color _headBg(BuildContext c) => Theme.of(c).colorScheme.primary.withValues(alpha: 0.35);
  Color _subBg(BuildContext c) => Theme.of(c).colorScheme.primary.withValues(alpha: 0.18);
  Color _line(BuildContext c) => Theme.of(c).dividerColor.withValues(alpha: 0.35);

  Widget _box(BuildContext context, double w, double h, Widget child,
          {Color? bg, Alignment al = Alignment.center, EdgeInsets pad = EdgeInsets.zero}) =>
      Container(
        width: w,
        height: h,
        alignment: al,
        padding: pad,
        decoration: BoxDecoration(
            color: bg, border: Border(right: BorderSide(color: _line(context)), bottom: BorderSide(color: _line(context)))),
        child: child,
      );

  Widget _header(BuildContext context) {
    final st = Theme.of(context).textTheme.labelMedium?.copyWith(fontWeight: FontWeight.bold);
    final bg = _headBg(context);
    Widget h(String s, double w) => _box(context, w, _rowH * 2, Text(s, style: st, textAlign: TextAlign.center), bg: bg);
    return Row(children: [
      h('점수', _wScore),
      h('구분', _wKind),
      h('추천건수', _wN),
      h('체결율', _wFill),
      Column(children: [
        _box(context, _wCat * 3, _rowH, Text('이익실현', style: st), bg: bg),
        Row(children: [
          for (final s in ['1차', '2차', '3차'])
            _box(context, _wCat, _rowH, Text(s, style: st?.copyWith(fontWeight: FontWeight.normal)), bg: _subBg(context)),
        ]),
      ]),
      h('매수가매도', _wCat),
      h('손절', _wCat),
      h('평균손익', _wAvg),
      h('누적손익', _wSum),
    ]);
  }

  Widget _band(BuildContext context, int band, Map<String, Map<String, dynamic>> sum) {
    final rows = [('all', '전체'), ..._kinds];
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _box(context, _wScore, _rowH * rows.length,
          Text('$band~', style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.bold))),
      Column(children: [
        for (final (i, (k, name)) in rows.indexed) _row(context, name, sum['$band|$k'], i, k == 'all'),
      ]),
    ]);
  }

  Widget _row(BuildContext context, String name, Map<String, dynamic>? s, int i, bool total) {
    final base = Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 12, fontWeight: total ? FontWeight.bold : null);
    final bg = total
        ? Theme.of(context).colorScheme.primary.withValues(alpha: 0.10)
        : (i.isEven ? Colors.white.withValues(alpha: 0.03) : null);
    final n = (s?['n'] as int?) ?? 0, f = (s?['f'] as int?) ?? 0;
    final p = (s?['p'] as double?) ?? 0;
    String pc(num v) => '${v.round()}%';
    String cat(String c) {
      final x = s?[c] as List<num>?;
      if (f == 0 || x == null || x[0] == 0) return f == 0 ? '-' : '0%';
      return '${pc(x[0] / f * 100)}(${(x[1] / x[0]).round()}일)';
    }

    Widget c(String text, double w, {Color? color, Alignment al = Alignment.center}) => _box(
        context, w, _rowH, Text(text, style: base?.copyWith(color: color), maxLines: 1, overflow: TextOverflow.ellipsis),
        bg: bg, al: al, pad: al == Alignment.centerLeft ? const EdgeInsets.only(left: 8) : EdgeInsets.zero);
    return Row(children: [
      c(name, _wKind, al: Alignment.centerLeft),
      c('$n', _wN),
      c(n == 0 ? '-' : pc(f / n * 100), _wFill),
      c(cat('t1'), _wCat, color: f > 0 ? upColor : null),
      c(cat('t2'), _wCat, color: f > 0 ? upColor : null),
      c(cat('t3'), _wCat, color: f > 0 ? upColor : null),
      c(cat('even'), _wCat, color: f > 0 ? Colors.orange : null),
      c(cat('stop'), _wCat, color: f > 0 ? downColor : null),
      c(f == 0 ? '-' : '${(p / f).toStringAsFixed(1)}%', _wAvg, color: f == 0 ? null : (p >= 0 ? upColor : downColor)),
      c(f == 0 ? '-' : '${p.toStringAsFixed(1)}%', _wSum, color: f == 0 ? null : (p >= 0 ? upColor : downColor)),
    ]);
  }
}
