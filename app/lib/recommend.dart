import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 통계 > 추천주 — 날마다 관심 목록에 나온 종목(추천 기록)의 실제 결과 + 승률·손익 통계
///   관심 탭(V3·익일유망주·상승초기·추세전환·상파): 추천 다음 날부터 최대 20거래일, 저장한 매매 계획대로
///     (1·2·3차 매수구간 → 1차 50%·2차 30%·3차 20% 매도 · 손절 · 20일째 종가, 비용 0.25%)
///   장중 탭(당일단타·종가배팅·상한가포착): 그 탭 실전 기록의 결과
///   저녁 배치가 매일 결과를 채움. 같은 종목이 여러 구분에 겹치면 구분마다 따로 매김
class RecTab extends StatefulWidget {
  const RecTab({super.key});
  @override
  State<RecTab> createState() => _RecTabState();
}

class _RecTabState extends State<RecTab> with AutomaticKeepAliveClientMixin {
  late Future<Json> _stats = _loadStats();
  List<String> _dates = const [];
  String? _day;
  Future<List<Json>>? _list;
  bool _loadingDates = true;

  @override
  bool get wantKeepAlive => true;

  static Future<Json> _loadStats() => Api.latestBacktest(strategy: 'RECS').catchError((_) => <String, dynamic>{});

  @override
  void initState() {
    super.initState();
    _loadDates();
  }

  Future<void> _loadDates() async {
    List<String> ds = const [];
    try {
      ds = await Api.recDates();
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      _dates = ds;
      _loadingDates = false;
      if (ds.isNotEmpty && (_day == null || !ds.contains(_day))) _pick(ds.first);
    });
  }

  void _pick(String d) {
    _day = d;
    _list = Api.recommendations(d);
  }

  Future<void> _refresh() async {
    setState(() => _stats = _loadStats());
    await _loadDates();
    if (_day != null) setState(() => _pick(_day!));
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final t = Theme.of(context).textTheme;
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
        children: [
          FutureBuilder<Json>(
            future: _stats,
            builder: (context, snap) => snap.connectionState != ConnectionState.done
                ? const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()))
                : _StatsBlock(d: snap.data ?? const {}),
          ),
          const SizedBox(height: 12),
          SectionTitle('일별 추천주', trailing: Text(_day ?? '', style: t.bodySmall)),
          if (_loadingDates)
            const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()))
          else if (_dates.isEmpty)
            Padding(
                padding: const EdgeInsets.all(12),
                child: Text('아직 추천 기록이 없어요. 오늘부터 저녁 배치·장중 탭이 추천을 저장하면 여기에 쌓여요.', style: t.bodySmall))
          else ...[
            SizedBox(
              height: 40,
              child: ListView(scrollDirection: Axis.horizontal, children: [
                for (final d in _dates.take(60))
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ChoiceChip(
                      label: Text(d.substring(5).replaceFirst('-', '/')),
                      selected: d == _day,
                      onSelected: (_) => setState(() => _pick(d)),
                    ),
                  ),
              ]),
            ),
            const SizedBox(height: 6),
            FutureBuilder<Json>(
              future: _stats,
              builder: (context, snap) {
                final day = asMap(asMap(snap.data?['by_day'])[_day]);
                if (day['n'] == null) return const SizedBox.shrink();
                return Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(_line(day), style: t.bodySmall?.copyWith(color: Colors.grey)),
                );
              },
            ),
            FutureBuilder<List<Json>>(
              future: _list,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
                }
                if (snap.hasError) return Text('불러오지 못했어요: ${snap.error}', style: t.bodySmall);
                final rows = snap.data ?? const <Json>[];
                if (rows.isEmpty) return Text('이날 추천이 없어요', style: t.bodySmall);
                final by = <String, List<Json>>{};
                for (final r in rows) {
                  by.putIfAbsent('${r['code']}', () => []).add(r);
                }
                final groups = by.values.toList()
                  ..sort((a, b) {
                    final c = b.length.compareTo(a.length); // 여러 구분에 겹친 종목 먼저
                    return c != 0 ? c : _best(b).compareTo(_best(a));
                  });
                return Column(children: [for (final g in groups) _StockCard(rows: g)]);
              },
            ),
          ],
        ],
      ),
    );
  }

  static double _best(List<Json> g) =>
      g.map((r) => (r['score'] as num?)?.toDouble() ?? 0).fold<double>(0, (a, b) => a > b ? a : b);

  static String _line(Json s) => '추천 ${s['n'] ?? 0} · 체결 ${s['filled'] ?? 0} · 끝남 ${s['done'] ?? 0} · 진행중 ${s['open'] ?? 0}'
      '${s['win'] != null ? ' · 승률 ${s['win']}%' : ''}${s['pnl'] != null ? ' · 평균 ${_sgn(s['pnl'] as num)}' : ''}'
      '${s['pnl_all'] != null ? ' · 평가 포함 ${_sgn(s['pnl_all'] as num)}' : ''}';
}

String _sgn(num v, {int d = 2}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}%';

String kindLabel(String k) => strategyLabels[k] ?? k;

/// 위쪽 통계: 전체 · 구분별 · 겹침 · 점수 구간 · 월별
class _StatsBlock extends StatelessWidget {
  const _StatsBlock({required this.d});
  final Json d;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final tot = asMap(d['total']);
    if ((tot['n'] ?? 0) == 0) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Text('추천주 통계가 아직 없어요. 추천이 쌓이면 저녁 배치가 매일 결과와 통계를 계산해요 '
              '(관심 탭은 추천 다음 날부터 20거래일, 장중 탭은 그 탭의 청산 규칙).', style: t.bodySmall),
        ),
      );
    }
    List<StatCell> row(String name, Json s) => [
          StatCell(name),
          StatCell('${s['n'] ?? 0}'),
          StatCell('${s['filled'] ?? 0}'),
          StatCell(s['win'] == null ? '-' : '${s['win']}%'),
          pnlCell(s['pnl'] as num?, bold: true),
          StatCell(s['t1_rate'] == null ? '-' : '${s['t1_rate']}%', color: upColor),
          StatCell(s['stop_rate'] == null ? '-' : '${s['stop_rate']}%', color: downColor),
        ];
    const header = ['구분', '추천', '체결', '승률', '평균', '1차↑', '손절'];
    Widget table(String title, Map<String, dynamic> m, {String Function(String)? name, bool withTotal = false}) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 10),
            Text(title, style: t.labelMedium),
            StatTable(header: header, boldFirst: withTotal, rows: [
              if (withTotal) row('전체', tot),
              for (final e in m.entries) row(name?.call(e.key) ?? e.key, asMap(e.value)),
            ]),
          ],
        );
    final months = asMap(d['by_month']).entries.toList().reversed.take(12);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text('추천주 통계', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            const Spacer(),
            Text('${d['updated'] ?? ''}', style: t.bodySmall),
          ]),
          Text('${d['first'] ?? ''} ~ ${d['last'] ?? ''} · ${d['days'] ?? 0}일 · 추천 ${tot['n']} · 체결 ${tot['filled']} · '
              '끝남 ${tot['done']} · 진행중 ${tot['open']} · 미체결 ${tot['unfilled']}',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          const SizedBox(height: 8),
          Wrap(spacing: 14, runSpacing: 6, children: [
            _Kpi('승률', tot['win'] == null ? '-' : '${tot['win']}%'),
            _Kpi('평균 손익', tot['pnl'] == null ? '-' : _sgn(tot['pnl'] as num), color: _c(tot['pnl'])),
            _Kpi('이긴 평균', tot['avg_win'] == null ? '-' : _sgn(tot['avg_win'] as num), color: upColor),
            _Kpi('진 평균', tot['avg_loss'] == null ? '-' : _sgn(tot['avg_loss'] as num), color: downColor),
            _Kpi('누적', tot['pnl_sum'] == null ? '-' : _sgn(tot['pnl_sum'] as num, d: 1), color: _c(tot['pnl_sum'])),
            _Kpi('1차 목표', tot['t1_rate'] == null ? '-' : '${tot['t1_rate']}%'),
            _Kpi('손절', tot['stop_rate'] == null ? '-' : '${tot['stop_rate']}%'),
          ]),
          table('구분별', asMap(d['by_kind']), name: kindLabel, withTotal: true),
          table('여러 구분에 겹친 종목 vs 한 구분만', asMap(d['by_overlap'])),
          table('점수 구간', asMap(d['by_score'])),
          table('월별 (최근 12개월)', {for (final e in months) e.key: e.value}),
          const SizedBox(height: 6),
          Text('승률·평균은 실제로 산(매수구간 체결) 추천 중 결과가 끝난 것만 · 비용 0.25% 뺀 % (산 금액 기준). '
              '1차↑ = 1차 목표 도달 비율. 누적 = 건마다 같은 금액을 넣었을 때 % 합. '
              '관심 탭은 추천 다음 날부터 ${d['hold_days'] ?? 20}거래일, 장중 탭은 그 탭의 청산 규칙.',
              style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
        ]),
      ),
    );
  }

  static Color? _c(dynamic v) => v is num ? (v >= 0 ? upColor : downColor) : null;
}

class _Kpi extends StatelessWidget {
  const _Kpi(this.label, this.value, {this.color});
  final String label, value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Text(label, style: t.bodySmall?.copyWith(color: Colors.grey)),
      Text(value, style: t.titleMedium?.copyWith(fontWeight: FontWeight.bold, color: color)),
    ]);
  }
}

/// 한 종목 카드: 종목명 + 겹친 구분 + 구분마다 계획(매수·목표·손절·손익비) → 결과
class _StockCard extends StatelessWidget {
  const _StockCard({required this.rows});
  final List<Json> rows;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final f = rows.first;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.push(context,
            MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${f['code']}', name: '${f['name'] ?? f['code']}'))),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(
                  child: Text('${f['name'] ?? f['code']}  ${f['code']}',
                      style: t.titleMedium, overflow: TextOverflow.ellipsis)),
              if (rows.length > 1) InfoBox('${rows.length}개 구분 겹침', color: Colors.deepPurple, bold: true, fill: true),
            ]),
            const SizedBox(height: 4),
            for (final r in rows) _KindRow(r: r),
          ]),
        ),
      ),
    );
  }
}

class _KindRow extends StatelessWidget {
  const _KindRow({required this.r});
  final Json r;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final pnl = r['res_pnl'] as num?;
    final done = r['res_done'] == true;
    final st = r['res_status'] as String?;
    final resColor = pnl == null ? Colors.grey : (pnl >= 0 ? upColor : downColor);
    final zones = [
      for (final i in [1, 2, 3])
        if (r['zone${i}_low'] is num && r['zone${i}_high'] is num && (r['zone${i}_low'] as num) != (r['zone${i}_high'] as num))
          '$i차 ${num0(r['zone${i}_low'] as num)}~${num0(r['zone${i}_high'] as num)}',
    ];
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        infoBoxes([
          InfoBox(kindLabel('${r['kind']}'), bold: true, fill: true, color: Colors.indigo),
          if (r['score'] is num) InfoBox('${(r['score'] as num).toStringAsFixed(1)}점'),
          if (r['rec_time'] != null && r['rec_time'] != '마감') InfoBox('${r['rec_time']}'),
          InfoBox(st == null ? '결과 대기' : '${done ? '' : '진행 · '}$st${pnl != null ? ' ${_sgn(pnl)}' : ''}',
              color: resColor, bold: pnl != null, fill: done && pnl != null),
          if (r['res_days'] is num && r['res_days'] != 0) InfoBox('${r['res_days']}일'),
        ]),
        const SizedBox(height: 2),
        Text(
            '매수 ${num0(r['entry'] as num?)} · 목표 ${num0(r['target1'] as num?)}'
            '${r['target2'] is num ? '/${num0(r['target2'] as num)}' : ''}${r['target3'] is num ? '/${num0(r['target3'] as num)}' : ''}'
            ' · 손절 ${num0(r['stop'] as num?)}${r['rr1'] is num ? ' · 손익비 ${r['rr1']}' : ''}'
            '${zones.length > 1 ? '\n${zones.join(' · ')}' : ''}'
            '${r['res_max_up'] is num ? '\n최고 ${_sgn(r['res_max_up'] as num, d: 1)} · 최저 ${_sgn((r['res_max_dn'] as num?) ?? 0, d: 1)}' : ''}',
            style: t.bodySmall?.copyWith(color: Colors.grey)),
      ]),
    );
  }
}
