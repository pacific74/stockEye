import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'daytrade.dart' show dtIsToday, DaytradeFindButton, NewsLine, liveWindow, lookupLabel;
import 'format.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 종가배팅 (CB-0.1) — PC 가 평일 14:50~15:20 1분마다 올리는 후보 (system_status 'closingbet')
///   상태: 매수 후보(80↑ · 갭 위험 높음 아님 · 14:50~15:20) / 우선 관찰(80↑) / 관찰(70↑) / 진입 금지
///   종가 무렵 매수 → 다음 날 오전(10:30 까지) 청산. 주문은 하지 않음 — 알림·관찰용

Color cbStatusColor(String? s) => switch (s) {
      '매수 후보' => const Color(0xFFD32F2F),
      '우선 관찰' => Colors.orange,
      '관찰' => Colors.teal,
      _ => Colors.grey,
    };

Color cbGapColor(String? g) => switch (g) {
      '높음' => Colors.red,
      '보통' => Colors.orange,
      '낮음' => Colors.teal,
      _ => Colors.grey,
    };

String _sgn(num? v, {int d = 1}) => v == null ? '-' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}%';

/// 후보 카드: 순위 · 종목명 [점수] · 현재가 / 상태 · 유형 · 갭 위험 · 오늘 등락 · 거래대금 / 매수 범위 · 다음 날 목표·손절 / 근거
class ClosingbetTile extends StatelessWidget {
  const ClosingbetTile({super.key, required this.r, required this.rank, this.price, this.showRules = false});
  final Json r;
  final int rank;
  final double? price;
  final bool showRules; // 다음 날 오전 매도 규칙까지 (관심 탭)

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final st = '${r['status'] ?? ''}';
    final col = cbStatusColor(st);
    final px = price ?? (r['price'] as num?)?.toDouble();
    final gap = asMap(r['gap']);
    final gg = gap['grade'] as String?;
    final ex = (r['excluded'] as List? ?? const []).map((e) => '$e').toList();
    final reasons = (r['reasons'] as List? ?? const []).map((e) => '$e').toList();
    final why = (gap['why'] as List? ?? const []).map((e) => '$e').toList();
    final nl = r['news_level'] as String?;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      shape: st == '매수 후보'
          ? RoundedRectangleBorder(side: BorderSide(color: col, width: 1.5), borderRadius: BorderRadius.circular(12))
          : null,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.push(context,
            MaterialPageRoute(builder: (_) => StockDetailScreen(
                code: '${r['code']}', name: '${r['name']}', source: 'closingbet', intraday: r))),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            CircleAvatar(backgroundColor: col.withValues(alpha: 0.15), child: Text('$rank', style: TextStyle(color: col))),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(
                      child: StockName('${r['name']}', score: r['score'] as num?, scoreDigits: 1, style: t.titleMedium)),
                  const SizedBox(width: 6),
                  if (px != null)
                    Text.rich(TextSpan(children: [
                      TextSpan(text: '현재가 ', style: t.bodySmall?.copyWith(color: Colors.grey)),
                      TextSpan(text: won(px), style: t.bodyMedium?.copyWith(fontWeight: FontWeight.bold)),
                    ])),
                ]),
                StockInfoLine('${r['code']}'), // [시장][업종 · 테마][시총]
                const SizedBox(height: 3),
                infoBoxes([
                  InfoBox(st, color: col, bold: true, fill: true),
                  if (r['type'] != null && r['type'] != '-') InfoBox('${r['type']}'),
                  if (gg != null)
                    InfoBox('갭 위험 $gg${gap['gap_lo'] is num ? ' (${_sgn(gap['gap_lo'] as num)}~${_sgn(gap['gap_hi'] as num?)})' : ''}',
                        color: cbGapColor(gg), bold: gg == '높음'),
                  if (r['chg_pct'] is num) InfoBox('오늘 ${pct(r['chg_pct'] as num)}', color: (r['chg_pct'] as num) >= 0 ? upColor : downColor),
                  if (r['value'] is num) InfoBox('${((r['value'] as num) / 1e8).toStringAsFixed(0)}억'),
                  if (nl != null && nl != 'neutral')
                    InfoBox('뉴스 ${const {'pos': '호재', 'neg': '악재', 'severe': '심각 악재'}[nl] ?? nl}',
                        color: nl == 'pos' ? upColor : downColor, bold: nl == 'severe'),
                ]),
                const SizedBox(height: 3),
                infoBoxes([
                  InfoBox('매수 ${num0(r['buy_lo'] as num?)}~${num0(r['buy_hi'] as num?)}', bold: true),
                  InfoBox('1차 ${num0(r['t1'] as num?)}${r['t1_pct'] is num ? ' (+${r['t1_pct']}%)' : ''}', color: upColor),
                  InfoBox('2차 ${num0(r['t2'] as num?)}', color: upColor),
                  InfoBox('손절 ${num0(r['stop'] as num?)}${r['stop_pct'] is num ? ' (${r['stop_pct']}%)' : ''}', color: downColor),
                ]),
                for (final x in ex) Text('⛔ $x', style: t.bodySmall?.copyWith(color: Colors.red)),
                if (why.isNotEmpty) Text('갭 위험: ${why.join(' · ')}', style: t.bodySmall?.copyWith(color: Colors.orange)),
                if (reasons.isNotEmpty) Text(reasons.join(' · '), style: t.bodySmall?.copyWith(color: Colors.grey)),
                NewsLine(asList(r['news'])),
                if (showRules && st == '매수 후보') ...[
                  const SizedBox(height: 4),
                  Text('다음 날 오전 매도 (${r['exit_time'] ?? '10:30'} 까지)', style: t.bodySmall?.copyWith(fontWeight: FontWeight.bold)),
                  for (final e in (r['exit_rules'] as List? ?? const []).asMap().entries)
                    Text('${e.key + 1}. ${e.value}', style: t.bodySmall),
                ],
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

/// 관심 > 종가배팅 탭 — 1분마다 자동 새로고침
class ClosingbetTab extends StatefulWidget {
  const ClosingbetTab({super.key});
  @override
  State<ClosingbetTab> createState() => _ClosingbetTabState();
}

class _ClosingbetTabState extends State<ClosingbetTab> with AutomaticKeepAliveClientMixin {
  Json? _d;
  DateTime? _at;
  Timer? _t;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
    _t = Timer.periodic(const Duration(seconds: 60), (_) {
      if (liveWindow(closing: true)) _load(); // 14:50~15:25 에만 1분마다
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final d = await Api.closingbet();
    if (mounted) {
      setState(() {
        _d = d;
        _at = DateTime.now();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final t = Theme.of(context).textTheme;
    final d = _d;
    if (d == null) return const Center(child: CircularProgressIndicator());
    final items = asList(d['items']);
    final today = dtIsToday(d);
    final c = asMap(d['counts']);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 24), children: [
        if (useCloud && isAdminUser)
          Row(children: [
            Text('종가배팅', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            const Spacer(),
            DaytradeFindButton(closing: true, onDone: _load),
          ]),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 4),
          child: Text(
              today
                  ? '${lookupLabel(d, _at)}${d['final'] == true ? ' (오늘 마지막)' : liveWindow(closing: true) ? ' · 1분마다 갱신' : ''} · 후보 ${d['scanned'] ?? 0} · '
                      '매수 후보 ${c['매수 후보'] ?? 0} · 우선 관찰 ${c['우선 관찰'] ?? 0} · 관찰 ${c['관찰'] ?? 0}'
                  : '오늘 종가배팅 결과가 아직 없어요. 관리자가 [종목찾기]를 누르거나 PC 에서 16_closingbet.bat 을 켜 두면 올라와요 (매수 후보는 14:50~15:20).'
                      '${d['date'] != null ? ' (아래는 ${d['date']} ${d['time']} 결과)' : ''}',
              style: t.bodySmall),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 6),
          child: Text('80점 이상이어도 갭 위험이 높으면 매수 후보가 아니에요. 매수는 14:50~15:20 사이 매수 범위 안에서, '
              '다음 날 오전 10:30 까지 규칙대로 매도. 갭 위험 괄호는 평소 다음 날 시가 갭 범위(하위 20%~상위 20%). 주문은 하지 않는 알림용이에요.',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
        ),
        if (items.isEmpty)
          const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('조건에 맞는 종목이 없어요'))),
        ...items.asMap().entries.map((e) => ClosingbetTile(r: e.value, rank: e.key + 1, showRules: true)),
      ]),
    );
  }
}

/// 검증 > 종가배팅: 실전 기록 + 되돌려 보기(5년 일봉 · 과거 1분봉)
Future<Json> loadClosingbetValidation() => Api.latestBacktest(strategy: 'CLOSE');

class ClosingbetValidation extends StatelessWidget {
  const ClosingbetValidation({super.key, required this.future});
  final Future<Json> future;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return FutureBuilder<Json>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) return const SizedBox.shrink();
        final d = snap.data ?? const {};
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SectionTitle('종가배팅 검증', trailing: Text('${d['updated'] ?? ''}', style: t.bodySmall)),
          Text('날마다 매수 후보 점수 상위 3 → 그날 종가 매수 → 다음 날 오전(10:30 까지) 매도 규칙. 손익은 비용 0.25% 뺀 %. '
              '시가 매도 = 다음 날 시초가에 전부 팔았을 때. 갭 하락 = 시가가 매수가보다 낮았던 비율',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          const SizedBox(height: 6),
          _block(context, '실전 기록 (매일 15:20 후보)', asMap(d['forward']),
              empty: '아직 기록이 없어요. 오후에 후보가 나오면 다음 날 저녁 배치가 결과를 매겨요.'),
          _block(context, '되돌려 보기 · 과거 1분봉', asMap(d['minutes']),
              empty: '아직 없어요. PC 에서 17_closingbet_backtest.bat 을 실행하면 계산해요.'),
          _block(context, '되돌려 보기 · 5년 일봉 (근사)', asMap(d['daily']),
              empty: '아직 없어요. PC 에서 17_closingbet_backtest.bat 을 실행하면 계산해요.', years: true),
        ]);
      },
    );
  }

  Widget _block(BuildContext context, String title, Json r, {required String empty, bool years = false}) {
    final t = Theme.of(context).textTheme;
    final tot = asMap(r['total']);
    final byGap = asMap(r['by_gap']);
    final groups = <MapEntry<String, Json>>[
      MapEntry('전체', tot),
      for (final g in const ['낮음', '보통', '높음'])
        if (byGap[g] != null) MapEntry('갭 $g', asMap(byGap[g])),
      if (years) for (final e in asMap(r['by_year']).entries) MapEntry(e.key, asMap(e.value)),
    ];
    String p(dynamic v) => '${v ?? 0}%';
    String p2(dynamic a, dynamic b) => '${(((a as num?) ?? 0) + ((b as num?) ?? 0)).toStringAsFixed(1)}%';
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: t.titleSmall),
          if ((tot['n'] ?? 0) == 0)
            Padding(padding: const EdgeInsets.only(top: 4), child: Text(empty, style: t.bodySmall))
          else ...[
            Text('${r['first'] ?? ''} ~ ${r['last'] ?? ''} · ${r['days'] ?? 0}일 · 갭 하락 ${tot['gap_down'] ?? '-'}%'
                '${r['note'] != null ? ' · ${r['note']}' : ''}',
                style: t.bodySmall?.copyWith(color: Colors.grey)),
            const SizedBox(height: 6),
            Text('결과 비율', style: t.labelMedium),
            StatTable(header: const ['구분', '건수', '2차', '1차', '시간', '손절', '갭손절'], rows: [
              for (final g in groups)
                [StatCell(g.key), StatCell('${g.value['n'] ?? 0}'), StatCell(p(g.value['t2'])), StatCell(p(g.value['t1'])),
                 StatCell(p2(g.value['time'], g.value['open'])), StatCell(p(g.value['stop']), color: downColor),
                 StatCell(p(g.value['gap_stop']), color: downColor)],
            ]),
            const SizedBox(height: 8),
            Text('손익 (비용 0.25% 뺀 %)', style: t.labelMedium),
            StatTable(header: const ['구분', '승률', '시가', '평균', '이긴', '진', '누적'], rows: [
              for (final g in groups)
                [StatCell(g.key), StatCell(g.value['win'] == null ? '-' : '${g.value['win']}%'),
                 pnlCell(g.value['open_pnl'] as num?), pnlCell(g.value['pnl'] as num?, bold: true),
                 pnlCell(g.value['avg_win'] as num?), pnlCell(g.value['avg_loss'] as num?), pnlCell(g.value['pnl_sum'] as num?, d: 0)],
            ]),
            Text('시가 = 다음 날 시초가에 전부 판 경우 · 평균·이긴·진 = 매도 규칙대로 판 손익 · 누적 = 건마다 같은 금액 넣었을 때 % 합',
                style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
            if (asList(r['recent']).isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('최근 기록', style: t.labelMedium),
              StatTable(firstFlex: 1.2, boldFirst: false, header: const ['날짜', '종목', '결과', '규칙', '시가'], rows: [
                for (final x in asList(r['recent']).take(10))
                  [StatCell('${'${x['date'] ?? ''}'.length >= 10 ? '${x['date']}'.substring(5) : x['date']}'),
                   StatCell('${x['name'] ?? ''}'), StatCell(_out(x['outcome'] as String?)),
                   pnlCell(x['pnl'] as num?), pnlCell(x['open_pnl'] as num?)],
              ]),
            ],
          ],
        ]),
      ),
    );
  }

  static String _out(String? o) => switch (o) {
        't2' => '2차 익절',
        't1' => '1차 익절',
        'stop' => '손절',
        'gap_stop' => '갭 하락 손절',
        'time' => '10:30 청산',
        'open' => '시가 매도',
        _ => '-',
      };

}
