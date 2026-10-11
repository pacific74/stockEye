import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';

/// 관심종목 검증 (VAL-1.0) — 주간 배치가 backtests 'VALID' 에 올린 결과
///   전략별 판정 → 상세: 비교군 · 기간별 가격 경로 · 5분위 · Rank IC · 부트스트랩 · 목표/손절 · 실현 매매
Future<Json> loadValidation() => Api.latestBacktest(strategy: 'VALID');

Color verdictColor(String? v) => switch (v) {
      '매매 전략 후보' => Colors.green,
      '선별력 가능성' => Colors.teal,
      '추가 검증' => Colors.amber,
      '보류/수정' => Colors.deepOrange,
      _ => Colors.grey,
    };

String _p(num? v, {int nd = 2, bool sign = true}) =>
    v == null ? '-' : '${sign && v > 0 ? '+' : ''}${v.toStringAsFixed(nd)}%';
String _n(num? v, {int nd = 1}) => v == null ? '-' : v.toStringAsFixed(nd);

/// 검증 탭 맨 위: 전략별 판정 카드 목록
class ValidationList extends StatelessWidget {
  const ValidationList({super.key, required this.future});
  final Future<Json> future;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return FutureBuilder<Json>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
        }
        final r = snap.data;
        final ss = asList(r?['strategies']);
        if (r == null || ss.isEmpty) {
          return Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text('아직 관심종목 검증 결과가 없어요. 매주 토요일 주간 배치(weekly-backtest)가 계산합니다. '
                  '지금 보려면 Actions → weekly-backtest → Run workflow 에서 only 칸에 VALID 를 넣고 실행하세요.',
                  style: t.bodySmall),
            ),
          );
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SectionTitle('관심종목 검증', trailing: Text('${r['end'] ?? ''} 기준 · ${r['version'] ?? ''}', style: t.bodySmall)),
          for (final s in ss) _StrategyCard(s: asMap(s), all: r),
        ]);
      },
    );
  }
}

class _StrategyCard extends StatelessWidget {
  const _StrategyCard({required this.s, required this.all});
  final Json s, all;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final v = asMap(s['verdict']);
    final col = verdictColor(v['label'] as String?);
    final ps = asList(s['periods']);
    final conf = ps.firstWhere((p) => p['name'] == '확인', orElse: () => ps.isEmpty ? <String, dynamic>{} : ps.last);
    final h = '${s['main_h']}';
    final top = asMap(asMap(asMap(conf['selection'])[h])['top']);
    final al = asMap(asMap(asMap(conf['selection'])[h])['all']);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        title: Row(children: [
          Text('${s['name']}', style: const TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(color: col.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8)),
            child: Text('${v['label'] ?? '-'}', style: TextStyle(color: col, fontSize: 12, fontWeight: FontWeight.bold)),
          ),
        ]),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(
              '확인 기간 ${s['main_h']}일 · 상위10 ${_p(top['mean'] as num?)} vs 자격 전체 ${_p(al['mean'] as num?)}'
              ' · IC ${_n(asMap(conf['ic'])['mean'] as num?, nd: 3)}',
              style: t.bodySmall),
        ),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ValidationDetail(s: s, all: all))),
      ),
    );
  }
}

/// 전략 하나 상세
class ValidationDetail extends StatefulWidget {
  const ValidationDetail({super.key, required this.s, required this.all});
  final Json s, all;

  @override
  State<ValidationDetail> createState() => _ValidationDetailState();
}

class _ValidationDetailState extends State<ValidationDetail> {
  int _pi = 1; // 기본: 확인 기간

  @override
  Widget build(BuildContext context) {
    final s = widget.s;
    final t = Theme.of(context).textTheme;
    final ps = asList(s['periods']);
    if (_pi >= ps.length) _pi = ps.isEmpty ? 0 : ps.length - 1;
    final p = ps.isEmpty ? <String, dynamic>{} : ps[_pi];
    final v = asMap(s['verdict']);
    final col = verdictColor(v['label'] as String?);
    final mh = '${s['main_h']}';
    final sel = asMap(p['selection']);
    final settings = asMap(widget.all['settings']);
    final cost = asMap(settings['cost']);
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(title: LogoTitle('${s['name']} 검증'), actions: topActions(context)),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
        // 판정
        Card(
          color: col.withValues(alpha: 0.10),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${v['label'] ?? '-'}', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: col)),
              const SizedBox(height: 4),
              for (final w in (v['why'] as List? ?? const [])) Text('· $w', style: t.bodySmall),
              const SizedBox(height: 6),
              Text('기준가격 ${s['base'] == 'open1' ? '다음 날 시가 (T+1)' : '선정일 종가 (T)'} · 주 평가 기간 ${s['main_h']}거래일',
                  style: t.bodySmall?.copyWith(color: Colors.grey)),
            ]),
          ),
        ),
        // 기간 선택
        Wrap(spacing: 6, children: [
          for (var i = 0; i < ps.length; i++)
            ChoiceChip(
              label: Text('${ps[i]['name']}'),
              selected: _pi == i,
              onSelected: (_) => setState(() => _pi = i),
            ),
        ]),
        const SizedBox(height: 4),
        Text('${p['start'] ?? ''} ~ ${p['end'] ?? ''} · 신호일 ${p['dates'] ?? 0}일 · 신호 ${p['signals'] ?? 0}건'
            ' (반복 ${p['repeats'] ?? 0} · 미체결 ${p['unfilled'] ?? 0})',
            style: t.bodySmall),
        if (p['sufficient'] != true)
          Text('⚠ 표본 부족 — 신호일 ${settings['min_dates'] ?? 30}일·신호 ${settings['min_signals'] ?? 100}건 미만이라 참고만',
              style: t.bodySmall?.copyWith(color: Colors.orange)),

        // 비교군
        SectionTitle('비교군 (${s['main_h']}거래일)'),
        _Table(
          head: const ['', '평균', '중앙', '승률', 'MFE', 'MAE'],
          rows: [
            for (final g in const [('top', '상위10'), ('all', '자격 전체'), ('random', '랜덤10'), ('market', '코스피')])
              if (asMap(sel[mh])[g.$1] != null)
                () {
                  final x = asMap(asMap(sel[mh])[g.$1]);
                  return [g.$2, _p(x['mean'] as num?), _p(x['median'] as num?), x['win'] == null ? '-' : '${_n(x['win'] as num?)}%',
                    _p(x['mfe'] as num?, nd: 1), _p(x['mae'] as num?, nd: 1)];
                }(),
          ],
        ),

        // 기간별 가격 경로 (상위10)
        const SectionTitle('기간별 가격 경로 (상위10)'),
        _Table(
          head: const ['일', '종가', 'MFE', 'MAE', '+5%', '−5%', '고점일\n되돌림', '종료\n반납'],
          rows: [
            for (final h in (widget.all['horizons'] as List? ?? const [1, 3, 5, 10, 20]))
              () {
                final x = asMap(asMap(sel['$h'])['top']);
                return ['$h', _p(x['mean'] as num?, nd: 1), _p(x['mfe'] as num?, nd: 1), _p(x['mae'] as num?, nd: 1),
                  x['up5'] == null ? '-' : '${_n(x['up5'] as num?, nd: 0)}%', x['dn5'] == null ? '-' : '${_n(x['dn5'] as num?, nd: 0)}%',
                  x['pk_giveback'] == null ? '-' : '${_n(x['pk_giveback'] as num?)}%', _p(x['end_giveback'] as num?, nd: 1)];
              }(),
          ],
        ),
        Text('MFE = 기간 최고가, MAE = 기간 최저가 (실현 수익 아님) · +5% = 최고가가 +5% 넘은 비율 · −5% = 최저가가 −5% 아래인 비율 · '
            '고점일 되돌림 = 최고가 날 종가가 고가에서 밀린 폭 · 종료 반납 = 마지막 날 종가 ÷ 최고가',
            style: t.bodySmall?.copyWith(color: Colors.grey)),

        // 5분위
        SectionTitle('점수 5분위 (${s['main_h']}거래일, 그날 점수 순위)'),
        _Quintiles(q: asList(p['quintiles'])),

        // 신뢰도
        const SectionTitle('신뢰도'),
        _kv(context, 'Rank IC (점수 ↔ 수익률 순위 상관)', () {
          final ic = asMap(p['ic']);
          if (ic.isEmpty) return '-';
          return '${_n(ic['mean'] as num?, nd: 3)} · t ${_n(ic['t'] as num?, nd: 1)} · 양수 ${_n(ic['pos'] as num?)}% (${ic['days']}일)';
        }()),
        _kv(context, '상위10 − 자격 전체 (95% 구간)', () {
          final b = asMap(p['boot']);
          if (b.isEmpty) return '표본 부족';
          return '${_p(b['mean'] as num?)}  [${_p(b['lo'] as num?)} ~ ${_p(b['hi'] as num?)}]';
        }()),
        Text('날짜 단위 블록 부트스트랩 (블록 ${asMap(p['boot'])['block'] ?? '-'}일). 구간이 0을 넘으면 우연이 아닐 가능성이 큼',
            style: t.bodySmall?.copyWith(color: Colors.grey)),

        // 목표/손절 · 실현 매매
        const SectionTitle('목표가·손절가 & 실현 매매 (상위10)'),
        () {
          final tr = asMap(p['trade']);
          if (tr.isEmpty) return Text('-', style: t.bodySmall);
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _HitBar(target: tr['target_first'] as num?, stop: tr['stop_first'] as num?, neither: tr['neither'] as num?),
            const SizedBox(height: 6),
            _kv(context, '거래', '${tr['n']}건 · 승률 ${_n(tr['win'] as num?)}%'),
            _kv(context, '비용 뺀 수익률', '평균 ${_p(tr['mean'] as num?)} · 중앙 ${_p(tr['median'] as num?)}'),
            _kv(context, 'PF (이익 합 ÷ 손실 합)', _n(tr['pf'] as num?, nd: 2)),
          ]);
        }(),
        Text('T+1 시가 매수 → 차트 1차 목표가/손절가 먼저 닿는 쪽, 아니면 ${s['main_h']}일째 종가 매도. 같은 날 둘 다 닿으면 손절 우선 · '
            '시초가 상한가는 미체결 · 비용 매수 ${cost['buy'] ?? 0.15}% · 매도 ${cost['sell'] ?? 0.25}%',
            style: t.bodySmall?.copyWith(color: Colors.grey)),
        const SizedBox(height: 12),
        Text('하루 ±${_n(settings['jump_pct'] as num?, nd: 0)}% 넘는 변화(액면분할·병합 등)가 낀 구간은 제외 · 같은 종목이 평가 기간 안에 다시 선정되면 반복으로만 집계 · '
            '과거 성과는 미래 수익을 보장하지 않습니다.',
            style: t.bodySmall?.copyWith(color: Colors.grey)),
      ]),
    );
  }

  Widget _kv(BuildContext context, String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(k, style: Theme.of(context).textTheme.bodyMedium)),
          Text(v, style: const TextStyle(fontWeight: FontWeight.w600)),
        ]),
      );
}

class _Table extends StatelessWidget {
  const _Table({required this.head, required this.rows});
  final List<String> head;
  final List<List<String>> rows;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    Widget cell(String s, {bool bold = false, bool first = false}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 2),
          child: Text(s,
              textAlign: first ? TextAlign.left : TextAlign.right,
              style: (bold ? t.labelSmall : t.bodySmall)?.copyWith(
                  fontWeight: bold ? FontWeight.bold : null,
                  color: !bold && s.startsWith('+') ? upColor : (!bold && s.startsWith('-') && s.length > 1 ? downColor : null))),
        );
    return Table(
      columnWidths: const {0: FlexColumnWidth(1.4)},
      defaultVerticalAlignment: TableCellVerticalAlignment.middle,
      children: [
        TableRow(
            decoration: BoxDecoration(border: Border(bottom: BorderSide(color: Colors.grey.withValues(alpha: 0.3)))),
            children: [for (var i = 0; i < head.length; i++) cell(head[i], bold: true, first: i == 0)]),
        for (final r in rows) TableRow(children: [for (var i = 0; i < r.length; i++) cell(r[i], first: i == 0)]),
      ],
    );
  }
}

class _Quintiles extends StatelessWidget {
  const _Quintiles({required this.q});
  final List<Json> q;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    if (q.isEmpty) return Text('-', style: t.bodySmall);
    final vals = q.map((x) => ((x['median'] as num?) ?? 0).toDouble()).toList();
    final mx = vals.map((v) => v.abs()).fold<double>(0.5, (a, b) => a > b ? a : b);
    return Column(children: [
      for (final x in q.reversed)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(children: [
            SizedBox(width: 64, child: Text('Q${x['q']}${x['q'] == 5 ? ' (상위)' : x['q'] == 1 ? ' (하위)' : ''}', style: t.bodySmall)),
            Expanded(
              child: LayoutBuilder(builder: (context, c) {
                final v = ((x['median'] as num?) ?? 0).toDouble();
                final w = c.maxWidth / 2 * (v.abs() / mx);
                return Stack(alignment: Alignment.center, children: [
                  Container(height: 1, color: Colors.grey.withValues(alpha: 0.4)),
                  Align(
                    alignment: v >= 0 ? Alignment.centerLeft : Alignment.centerRight,
                    child: Padding(
                      padding: EdgeInsets.only(left: v >= 0 ? c.maxWidth / 2 : 0, right: v < 0 ? c.maxWidth / 2 : 0),
                      child: Container(width: w, height: 10, color: (v >= 0 ? upColor : downColor).withValues(alpha: 0.7)),
                    ),
                  ),
                ]);
              }),
            ),
            SizedBox(
                width: 140,
                child: Text('중앙 ${_p(x['median'] as num?)} · 평균 ${_p(x['mean'] as num?)}',
                    textAlign: TextAlign.right, style: t.bodySmall)),
          ]),
        ),
      Text('각 날짜에 자격 종목을 점수 순으로 5등분 · 막대 = 중앙값', style: t.bodySmall?.copyWith(color: Colors.grey)),
    ]);
  }
}

class _HitBar extends StatelessWidget {
  const _HitBar({this.target, this.stop, this.neither});
  final num? target, stop, neither;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final a = (target ?? 0).toDouble(), b = (stop ?? 0).toDouble(), c = (neither ?? 0).toDouble();
    final sum = (a + b + c) <= 0 ? 1.0 : a + b + c;
    Widget seg(double v, Color col) => Expanded(flex: (v / sum * 1000).round().clamp(1, 1000), child: Container(height: 12, color: col));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      ClipRRect(
        borderRadius: BorderRadius.circular(6),
        child: Row(children: [seg(a, upColor), seg(b, downColor), seg(c, Colors.grey)]),
      ),
      const SizedBox(height: 4),
      Text('목표 먼저 ${a.toStringAsFixed(1)}% · 손절 먼저 ${b.toStringAsFixed(1)}% · 둘 다 아님 ${c.toStringAsFixed(1)}%', style: t.bodySmall),
    ]);
  }
}
