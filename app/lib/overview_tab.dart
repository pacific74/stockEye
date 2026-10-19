import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'rec_detail.dart';

/// 통계 > 전체현황 · 당일단타 (2026-10-15)
///   전체현황: 점수대(90~ · 80~ · 70~ · 60~) × 구분별 추천 결과 표
///   당일단타: 점수별 당일단타만 + 매수시간별(09:00~10:00 10분 단위 × 점수별)
///   추천 유효기간 = 다음 거래일 하루: 그날 1차 매수구간에서 체결돼야 매수 (못 사면 미체결로 끝)
///   체결 뒤 2·3차 매수 · 1차 50% · 2차 30% · 3차 20% 매도 · 1·2차 뒤 매수가로 돌아오면 매수가매도(전량) · 손절
///   칸 = 체결된 것 중 비율 (괄호 = 평균 보유기간, 체결일 포함 거래일)
///   데이터: 저녁 배치 RECS 의 grid {날짜: {"90|v3": {"d": 완료, "h": 보유중}}} · dt_time {날짜: {"09:10|90": …}}
///   → 고른 기간만 더함
class OverviewTab extends StatefulWidget {
  const OverviewTab({super.key, this.daytrade = false, this.closingbet = false});
  final bool daytrade; // true = 통계 > 당일단타 탭
  final bool closingbet; // true = 통계 > 종가배팅 탭
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
const _dtBands = [90, 80]; // 통계 > 당일단타는 80점 이상만 (2026-10-15)
const _cats = ['t1', 't2', 't3', 'even', 'stop'];
const _times = ['09:00', '09:10', '09:20', '09:30', '09:40', '09:50'];

// 칸 너비: 점수 · 구분 · 추천건수 · 체결율 · 1차 · 2차 · 3차 · 매수가매도 · 손절 · 평균손익 · 누적손익
const _wScore = 48.0, _wKind = 84.0, _wTime = 72.0, _wN = 64.0, _wFill = 60.0, _wCat = 84.0, _wAvg = 68.0, _wSum = 72.0;
const _rowH = 28.0;
const _wNx = 104.0; // 종가배팅: NXT 상승 · 프리마켓 상승
const _metricsW = _wN + _wCat * 5 + _wAvg + _wSum; // 체결율 빼고

typedef _Sum = Map<String, dynamic>; // {n, f, p, t1: [건수, 보유일 합], …}

class _OverviewTabState extends State<OverviewTab> with AutomaticKeepAliveClientMixin {
  late Future<Json> _f = _load();
  String _period = 'all'; // all · year · month · day
  String? _year, _month, _day; // '2026' · '2026-10' · '2026-10-15'
  String _mode = 'd'; // d 완료 · h 보유중 · a 전체(둘 다)
  List<String> get _modes => _mode == 'a' ? const ['d', 'h'] : [_mode];
  String get _modeName => switch (_mode) { 'a' => '전체', 'h' => '보유중', _ => '완료' };

  @override
  bool get wantKeepAlive => true;

  static Future<Json> _load() => Api.latestBacktest(strategy: 'RECS').catchError((_) => <String, dynamic>{});

  /// 고른 기간의 날짜 묶음을 키별로 더함 (keyOf: 원래 키 → 더할 키들)
  Map<String, _Sum> _sumUp(Json grid, Iterable<String> pick, List<String> Function(String key) keyOf) {
    final sum = <String, _Sum>{};
    for (final d in pick) {
      for (final e in asMap(grid[d]).entries) {
       for (final md in _modes) {
        final m = asMap(asMap(e.value)[md]);
        if (m.isEmpty) continue;
        for (final key in keyOf(e.key)) {
          final s = sum.putIfAbsent(key, () => {'n': 0, 'f': 0, 'p': 0.0});
          s['n'] = (s['n'] as int) + ((m['n'] as num?)?.toInt() ?? 0);
          s['f'] = (s['f'] as int) + ((m['f'] as num?)?.toInt() ?? 0);
          s['p'] = (s['p'] as double) + ((m['p'] as num?)?.toDouble() ?? 0);
          // 결과 칸 [건수, 보유일 합, (종합 매수대비 합, 종합 수, 업종 매수대비 합, 업종 수)] · ib [종합 수, 종합+, 업종 수, 업종+]
          for (final c in [..._cats, 'ib']) {
            final x = m[c];
            if (x is List && x.length >= 2) {
              final cur = (s[c] as List<num>?) ?? <num>[];
              s[c] = <num>[
                for (var j = 0; j < (x.length > cur.length ? x.length : cur.length); j++)
                  (j < cur.length ? cur[j] : 0) + (j < x.length ? x[j] as num : 0)
              ];
            }
          }
        }
       }
      }
    }
    return sum;
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return RefreshIndicator(
      onRefresh: () async {
        RecDetail.reset();
        setState(() => _f = _load());
      },
      notificationPredicate: (n) => n.metrics.axis == Axis.vertical, // 표 안쪽(옆 스크롤 속) 세로 스크롤로 당겨서 새로고침
      child: FutureBuilder<Json>(
        future: _f,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          final data = snap.data ?? const <String, dynamic>{};
          final grid = asMap(data['grid']);
          final tgrid = asMap(data['dt_time']);
          final dates = grid.keys.toList()..sort();
          final years = {for (final d in dates) d.substring(0, 4)}.toList()..sort((a, b) => b.compareTo(a));
          final months = {for (final d in dates) d.substring(0, 7)}.toList()..sort((a, b) => b.compareTo(a));
          if (_year == null || !years.contains(_year)) _year = years.isEmpty ? null : years.first;
          if (_month == null || !months.contains(_month)) _month = months.isEmpty ? null : months.first;
          if (_day == null || !dates.contains(_day)) _day = dates.isEmpty ? null : dates.last; // 가장 최근 날
          bool inPeriod(String d) => switch (_period) {
                'year' => _year != null && d.startsWith(_year!),
                'month' => _month != null && d.startsWith(_month!),
                'day' => d == _day,
                _ => true,
              };
          final pick = dates.where(inPeriod).toList();
          // 추천건수를 누르면 그 칸의 종목·상태 목록 (고른 기간 · 완료/보유중 그대로)
          void open(String title, bool Function(Json r) pass) {
            final per = switch (_period) {
              'year' => '${_year ?? ''}년',
              'month' => _month == null ? '' : '${_month!.substring(0, 4)}년 ${int.parse(_month!.substring(5))}월',
              'day' => _day ?? '',
              _ => '전체 기간',
            };
            showRecDetail(context,
                title: '$title · $per · $_modeName',
                test: (r) => inPeriod('${r['d']}') && (_mode == 'a' || (r['dn'] == true) == (_mode == 'd')) && pass(r));
          }

          // 점수대·구분별 (키 '90|v3' → 그 키 + '90|all')
          final sum = _sumUp(grid, pick, (k) => [k, '${k.split('|').first}|all']);
          final note = Text(
            '* (괄호) 안은 평균 보유기간 (체결일 포함 거래일). 1·2·3차 · 매수가매도 · 손절 = 체결된 것 중 비율, 나머지는 기간 만료·장 마감 청산.\n'
            '추천 유효기간은 다음 거래일 하루 — 그날 1차 매수구간에서 체결되면 2·3차 매수·분할 매도를 이어 가고, 못 사면 미체결로 끝.\n'
            '단타·종가배팅·상한가포착은 당일매매 추적 결과(포착 시각 매수). 평균·누적 손익은 비용 0.25% 뺀 % (누적 = 건별 손익의 합).',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey, fontSize: 11),
          );
          final empty = Expanded(
            child: ListView(physics: const AlwaysScrollableScrollPhysics(), children: const [
              Padding(padding: EdgeInsets.all(24), child: Center(child: Text('아직 집계가 없어요 — 오늘 저녁 배치 뒤부터 보여요'))),
            ]),
          );
          final filters = _filters(context, years, months, dates);
          if (widget.closingbet) return _closingbet(context, filters, empty, dates.isEmpty, sum, asMap(data['cb_nx']), inPeriod, open);
          if (!widget.daytrade) {
            // 틀 고정: 검색 줄 + 표 머리는 그대로, 아래 표만 위아래로 스크롤 (옆으로는 머리·표가 같이 움직임)
            const tableW = _wScore + _wKind + _wFill + _metricsW;
            return Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                filters,
                const SizedBox(height: 8),
                if (dates.isEmpty)
                  empty
                else
                  Expanded(
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: SizedBox(
                        width: tableW,
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          _header(context, [('점수', _wScore), ('구분', _wKind)], fill: true),
                          Expanded(
                            child: ListView(
                              physics: const AlwaysScrollableScrollPhysics(),
                              padding: const EdgeInsets.only(bottom: 32),
                              children: [
                                for (final b in _bands)
                                  _group(context, '$b~', _wScore, [
                                    for (final (i, (k, name)) in [('all', '전체'), ..._kinds].indexed)
                                      _row(context, [(name, _wKind, true)], sum['$b|$k'], i, k == 'all',
                                          fill: true,
                                          onCount: () => open('$b~ · $name', (r) => r['b'] == b && (k == 'all' || r['k'] == k))),
                                  ]),
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
          }
          // ---- 통계 > 당일단타: 점수별 + 매수시간별 (검색 줄 고정, 두 표는 함께 스크롤)
          // 매수시간별 (키 '09:10|90' → 그 키 + '09:10|all')
          final tsum = _sumUp(tgrid, tgrid.keys.where(inPeriod), (k) {
            final p = k.split('|');
            return [k, if (_dtBands.contains(int.tryParse(p.last))) '${p.first}|all'];
          });
          final t = Theme.of(context).textTheme;
          Widget title(String s, String note) => Padding(
                padding: const EdgeInsets.fromLTRB(0, 12, 0, 6),
                child: Text.rich(TextSpan(children: [
                  TextSpan(text: s, style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                  TextSpan(text: '  $note', style: t.bodySmall?.copyWith(color: Colors.grey)),
                ])),
              );
          return Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              filters,
              const SizedBox(height: 4),
              if (dates.isEmpty && tgrid.isEmpty)
                empty
              else
                Expanded(
                  child: ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.only(bottom: 32),
                    children: [
                      title('점수별', '당일단타만 (80점 이상)'),
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          _header(context, [('점수', _wScore)], fill: true),
                          for (final (i, (b, name)) in [(0, '전체'), for (final b in _dtBands) (b, '$b~')].indexed)
                            _row(context, [(name, _wScore, false)], b == 0 ? _total(sum, 'daytrade') : sum['$b|daytrade'], i,
                                b == 0,
                                fill: true,
                                onCount: () => open('당일단타 · $name',
                                    (r) => r['k'] == 'daytrade' && (b == 0 ? _dtBands.contains(r['b']) : r['b'] == b))),
                        ]),
                      ),
                      title('매수시간별', '포착(매수) 시각 10분 단위 × 점수 (80점 이상)'),
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Text(
                            '둘째 줄 — 추천건수 밑: 매수 때 종합지수가 + 였던 비율 | 업종지수가 + 였던 비율 · '
                            '결과 칸 밑: 매수 때보다 그 순간(1·2·3차 · 매수가매도 · 손절) 종합지수 | 업종지수가 몇 % 움직였나 (평균). '
                            '종합지수 = 코스피 종목은 코스피, 코스닥 종목은 코스닥 · 2026-10-16 부터 기록',
                            style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
                      ),
                      if (tgrid.isEmpty)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          child: Text('매수시간별 집계가 아직 없어요 — 다음 저녁 배치(또는 daily-batch 수동 실행) 뒤부터 보여요',
                              style: t.bodySmall?.copyWith(color: Colors.orange)),
                        )
                      else
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          _header(context, [('매수시간', _wTime), ('점수', _wScore)]),
                          for (final tb in [..._times, if (tsum.keys.any((k) => k.startsWith('10:00'))) '10:00'])
                            _group(context, tb == '10:00' ? '10:00\n~' : '$tb\n~\n${_next(tb)}', _wTime, [ // 3줄: 09:00 / ~ / 09:10
                              for (final (i, (b, name)) in [(0, '전체'), for (final b in _dtBands) (b, '$b~')].indexed)
                                _row(context, [(name, _wScore, false)], b == 0 ? tsum['$tb|all'] : tsum['$tb|$b'], i, b == 0,
                                    ix: true,
                                    onCount: () => open('당일단타 · $tb~${_next(tb)} · $name',
                                        (r) => r['k'] == 'daytrade' && r['tb'] == tb && (b == 0 ? _dtBands.contains(r['b']) : r['b'] == b))),
                            ], rowH: _rowH * 2),
                        ]),
                      ),
                      const SizedBox(height: 8),
                      note,
                    ],
                  ),
                ),
            ]),
          );
        },
      ),
    );
  }

  /// 점수대 합계 (그 구분의 90~·80~·70~·60~ 를 더함)
  _Sum? _total(Map<String, _Sum> sum, String kind) {
    _Sum? out;
    for (final b in _dtBands) {
      final s = sum['$b|$kind'];
      if (s == null) continue;
      out ??= {'n': 0, 'f': 0, 'p': 0.0};
      out['n'] = (out['n'] as int) + (s['n'] as int);
      out['f'] = (out['f'] as int) + (s['f'] as int);
      out['p'] = (out['p'] as double) + (s['p'] as double);
      for (final c in _cats) {
        final x = s[c] as List<num>?;
        if (x == null) continue;
        final cur = (out[c] as List<num>?) ?? <num>[0, 0];
        out[c] = <num>[cur[0] + x[0], cur[1] + x[1]]; // 점수별 표는 지수 칸 없음
      }
    }
    return out;
  }

  static String _next(String hm) {
    final m = int.parse(hm.substring(3)) + 10;
    return m >= 60 ? '${(int.parse(hm.substring(0, 2)) + 1).toString().padLeft(2, '0')}:00' : '${hm.substring(0, 3)}$m';
  }

  // ---------------------------------------------------------------- 검색 줄: 기간 [전체 · 년 · 월 · 일] · 매매구분 [완료 · 보유중]
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
        seg(const [('all', '전체'), ('year', '년'), ('month', '월'), ('day', '일')], _period, (v) => _period = v),
        if (_period == 'year' && years.isNotEmpty) ...[
          const SizedBox(width: 8),
          drop(years, _year, (v) => '$v년', (v) => _year = v),
        ],
        if (_period == 'month' && months.isNotEmpty) ...[
          const SizedBox(width: 8),
          drop(months, _month, (v) => '${v.substring(0, 4)}년 ${int.parse(v.substring(5))}월', (v) => _month = v),
        ],
        if (_period == 'day' && dates.isNotEmpty) ...[
          const SizedBox(width: 8),
          drop(dates.reversed.toList(), _day, (v) => '${v.substring(0, 4)}-${v.substring(5, 7)}-${v.substring(8, 10)} (${_wd(v)})',
              (v) => _day = v),
        ],
      ]),
      Row(mainAxisSize: MainAxisSize.min, children: [
        label('매매구분'),
        seg(const [('a', '전체'), ('d', '완료'), ('h', '보유중')], _mode, (v) => _mode = v),
      ]),
    ]);
  }

  static String _wd(String d) => const ['월', '화', '수', '목', '금', '토', '일'][DateTime.parse(d).weekday - 1];

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

  /// 표 머리: 앞 칸들(이름·너비) + [체결율] + 추천건수 · 이익실현 1·2·3차 · 매수가매도 · 손절 · 평균손익 · 누적손익
  Widget _header(BuildContext context, List<(String, double)> leads,
      {bool fill = false, String count = '추천건수', List<String> extras = const []}) {
    final st = Theme.of(context).textTheme.labelMedium?.copyWith(fontWeight: FontWeight.bold);
    final bg = _headBg(context);
    Widget h(String s, double w) => _box(context, w, _rowH * 2, Text(s, style: st, textAlign: TextAlign.center), bg: bg);
    return Row(children: [
      for (final (s, w) in leads) h(s, w),
      h(count, _wN),
      if (fill) h('체결율', _wFill),
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
      for (final e in extras) h(e, _wNx),
    ]);
  }

  /// 묶음: 왼쪽에 합친 칸(점수대 · 매수시간) + 오른쪽 행들
  Widget _group(BuildContext context, String label, double w, List<Widget> rows, {double rowH = _rowH}) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _box(context, w, rowH * rows.length,
              Text(label,
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.bold, height: 1.2))),
          Column(children: rows),
        ],
      );

  /// 한 행: 앞 칸들(글자 · 너비 · 왼쪽정렬?) + 숫자 칸
  /// ix=true (매수시간별): 2줄 — 둘째 줄 추천건수 밑 '매수 때 종합지수 + 비율 | 업종지수 + 비율',
  ///   결과 칸 밑 '매수 대비 그 순간 종합 | 업종 변화 (평균 %)'
  Widget _row(BuildContext context, List<(String, double, bool)> leads, _Sum? s, int i, bool total,
      {bool fill = false, bool ix = false, bool countFilled = false, List<String> extras = const [], VoidCallback? onCount}) {
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

    final subSt = base?.copyWith(fontSize: 10.5, color: Colors.grey, fontWeight: FontWeight.normal);
    String sg(double v) => '${v > 0 ? '+' : (v < 0 ? '−' : '')}${v.abs().toStringAsFixed(1)}';
    // 둘째 줄: 매수 때 지수 + 비율 (추천건수 밑)
    String upRate() {
      final b = s?['ib'] as List<num>?;
      if (b == null || b.length < 4 || (b[0] == 0 && b[2] == 0)) return '-';
      String r(num a, num n) => n == 0 ? '-' : '${(a / n * 100).round()}%';
      return '${r(b[1], b[0])} | ${r(b[3], b[2])}';
    }

    // 둘째 줄: 결과 순간 지수 변화 (매수 대비 평균 %)
    String ixMove(String c) {
      final x = s?[c] as List<num>?;
      if (x == null || x.length < 6 || (x[3] == 0 && x[5] == 0)) return '-';
      return '${x[3] == 0 ? '-' : sg(x[2] / x[3])} | ${x[5] == 0 ? '-' : sg(x[4] / x[5])}';
    }

    Widget c(String text, double w, {Color? color, Alignment al = Alignment.center, String? sub, VoidCallback? onTap}) {
      final tap = onTap != null;
      final mainSt = base?.copyWith(
          color: tap ? Theme.of(context).colorScheme.primary : color, decoration: tap ? TextDecoration.underline : null);
      final box = _box(
          context,
          w,
          ix ? _rowH * 2 : _rowH,
          ix
              ? Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.center, children: [
                  Text(text, style: mainSt, maxLines: 1, overflow: TextOverflow.ellipsis),
                  if (sub != null) Text(sub, style: subSt, maxLines: 1, overflow: TextOverflow.ellipsis),
                ])
              : Text(text, style: mainSt, maxLines: 1, overflow: TextOverflow.ellipsis),
          bg: bg,
          al: al,
          pad: al == Alignment.centerLeft ? const EdgeInsets.only(left: 8) : EdgeInsets.zero);
      return tap ? InkWell(onTap: onTap, child: box) : box;
    }

    return Row(children: [
      for (final (text, w, left) in leads) c(text, w, al: left ? Alignment.centerLeft : Alignment.center),
      c(countFilled ? '$f' : '$n', _wN, sub: ix ? upRate() : null, onTap: (countFilled ? f : n) > 0 ? onCount : null),
      if (fill) c(n == 0 ? '-' : pc(f / n * 100), _wFill),
      c(cat('t1'), _wCat, color: f > 0 ? upColor : null, sub: ix ? ixMove('t1') : null),
      c(cat('t2'), _wCat, color: f > 0 ? upColor : null, sub: ix ? ixMove('t2') : null),
      c(cat('t3'), _wCat, color: f > 0 ? upColor : null, sub: ix ? ixMove('t3') : null),
      c(cat('even'), _wCat, color: f > 0 ? Colors.orange : null, sub: ix ? ixMove('even') : null),
      c(cat('stop'), _wCat, color: f > 0 ? downColor : null, sub: ix ? ixMove('stop') : null),
      c(f == 0 ? '-' : '${(p / f).toStringAsFixed(1)}%', _wAvg, color: f == 0 ? null : (p >= 0 ? upColor : downColor)),
      c(f == 0 ? '-' : '${p.toStringAsFixed(1)}%', _wSum, color: f == 0 ? null : (p >= 0 ? upColor : downColor)),
      for (final e in extras) c(e, _wNx),
    ]);
  }

  // ---------------------------------------------------------------- 통계 > 종가배팅 (2026-10-15)
  /// 점수대별 종가배팅(산 것) 결과 + NXT 애프터마켓(매수 날 저녁) · 프리마켓(다음 날 08:00~08:50) 상승 비율
  Widget _closingbet(BuildContext context, Widget filters, Widget empty, bool noData, Map<String, _Sum> sum, Json nxg,
      bool Function(String) inPeriod, void Function(String, bool Function(Json)) open) {
    // NXT: {날짜: {"90": {"d": [애프터 수, 애프터 +, 프리 수, 프리 +]}}} → 점수대별·전체 합
    final nx = <String, List<int>>{};
    for (final d in nxg.keys.where(inPeriod)) {
      for (final e in asMap(nxg[d]).entries) {
        if (!_dtBands.contains(int.tryParse(e.key))) continue;
        for (final md in _modes) {
          final v = asMap(e.value)[md];
          if (v is! List || v.length < 4) continue;
          for (final k in [e.key, 'all']) {
            final cur = nx.putIfAbsent(k, () => [0, 0, 0, 0]);
            for (var j = 0; j < 4; j++) {
              cur[j] += (v[j] as num).toInt();
            }
          }
        }
      }
    }
    String rate(List<int>? v, int i) => v == null || v[i] == 0 ? '-' : '${(v[i + 1] / v[i] * 100).round()}% (${v[i + 1]}/${v[i]})';
    final t = Theme.of(context).textTheme;
    final rows = [(0, '전체'), for (final b in _dtBands) (b, '$b~')];
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        filters,
        const SizedBox(height: 8),
        if (noData)
          empty
        else
          Expanded(
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.only(bottom: 32),
              children: [
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    _header(context, [('점수', _wScore)], count: '종가배팅\n건수', extras: ['NXT상승', '프리마켓상승']),
                    for (final (i, (b, name)) in rows.indexed)
                      _row(context, [(name, _wScore, false)], b == 0 ? _total(sum, 'closingbet') : sum['$b|closingbet'], i,
                          b == 0,
                          countFilled: true,
                          onCount: () => open(
                              '종가배팅 · $name',
                              (r) =>
                                  r['k'] == 'closingbet' &&
                                  r['cat'] != 'unfilled' &&
                                  r['cat'] != 'wait' &&
                                  (b == 0 ? _dtBands.contains(r['b']) : r['b'] == b)),
                          extras: [rate(nx[b == 0 ? 'all' : '$b'], 0), rate(nx[b == 0 ? 'all' : '$b'], 2)]),
                  ]),
                ),
                const SizedBox(height: 8),
                Text(
                    '종가배팅건수 = 14:50~15:20 매수 범위에서 실제로 산 것 (미체결 빼고). 1·2·3차 · 매수가매도 · 손절 = 그중 비율 (괄호 = 보유일, 산 날 포함).\n'
                    'NXT상승 = 산 날 저녁 넥스트레이드 애프터마켓 가격이 그날 종가보다 높았던 비율 (+ 건수/기록 건수).\n'
                    '프리마켓상승 = 다음 날 08:00~08:50 넥스트레이드 프리마켓이 전일 종가보다 높았던 비율. 80점 이상만 매수하므로 80~ · 90~ 만.',
                    style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
              ],
            ),
          ),
      ]),
    );
  }
}
