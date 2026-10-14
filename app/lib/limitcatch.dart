import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'daytrade.dart' show dtIsToday, DaytradeFindButton, NewsLine, lookupLabel;
import 'format.dart';
import 'live.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 상한가포착 (LC-0.1) — PC 가 평일 09:05~15:20 1분마다 올리는 후보 (system_status 'limitcatch')
///   1단계 강세 후보: +20%↑ · 거래대금 100억↑ · 75점↑
///   2단계 매수 검토: 상한가 도달(잠김) 또는 +27%↑ · 풀림 0~1회(1회면 바로 재잠금) · 위험 신호 없음
///   도달 / 미도달 종목은 따로 보여줌. 당일 매수 → 다음 날 시가 절반 · 09:30 까지 청산. 주문은 하지 않음

/// 장중 1분 새로고침 시간 (09:00~15:25)
bool lcWindow() {
  final n = DateTime.now();
  if (n.weekday > 5) return false;
  final m = n.hour * 60 + n.minute;
  return m >= 9 * 60 && m <= 15 * 60 + 25;
}

Color lcStatusColor(String? s) => switch (s) {
      '매수 검토' => const Color(0xFFD32F2F),
      '강세 후보' => Colors.orange,
      '관찰' => Colors.teal,
      '조건 무효' => Colors.blueGrey,
      _ => Colors.grey,
    };

/// 메인·관심 탭 공용 카드: 순위 · 종목명 [점수] · 현재가 / 상태 · 도달·잠김 · 풀림 · 오늘 등락 · 거래대금 / 잔량 / 매수·무효 가격 / 근거
class LimitcatchTile extends StatelessWidget {
  const LimitcatchTile({super.key, required this.r, required this.rank, this.price, this.showRules = false});
  final Json r;
  final int rank;
  final double? price;
  final bool showRules;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final st = '${r['status'] ?? ''}';
    final col = lcStatusColor(st);
    final px = price ?? (r['price'] as num?)?.toDouble();
    final lk = asMap(r['lock']);
    final bk = asMap(r['book']);
    final reached = lk['reached'] == true;
    final locked = lk['locked_now'] == true;
    final rel = (lk['releases'] as num?)?.toInt() ?? 0;
    final risks = (r['risks'] as List? ?? const []).map((e) => '$e').toList();
    final ex = (r['excluded'] as List? ?? const []).map((e) => '$e').toList();
    final reasons = (r['reasons'] as List? ?? const []).map((e) => '$e').toList();
    final nl = r['news_level'] as String?;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      shape: st == '매수 검토'
          ? RoundedRectangleBorder(side: BorderSide(color: col, width: 1.5), borderRadius: BorderRadius.circular(12))
          : null,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.push(
            context, MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${r['code']}', name: '${r['name']}', news: asList(r['news'])))),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            CircleAvatar(backgroundColor: col.withValues(alpha: 0.15), child: Text('$rank', style: TextStyle(color: col))),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: StockName('${r['name']}', score: r['score'] as num?, scoreDigits: 1, style: t.titleMedium)),
                  const SizedBox(width: 6),
                  if (px != null)
                    Text.rich(TextSpan(children: [
                      TextSpan(text: '현재가 ', style: t.bodySmall?.copyWith(color: Colors.grey)),
                      TextSpan(text: won(px), style: t.bodyMedium?.copyWith(fontWeight: FontWeight.bold)),
                    ])),
                  ChgBadge(Live.last['${r['code']}']?.ratio ?? (r['chg_pct'] as num?)), // 오늘 등락률
                ]),
                StockInfoLine('${r['code']}'), // [시장][업종 · 테마][시총]
                const SizedBox(height: 3),
                infoBoxes([
                  InfoBox(st, color: col, bold: true, fill: true),
                  InfoBox(reached ? (locked ? '상한가 잠김' : '상한가 풀림') : '미도달',
                      color: reached ? (locked ? upColor : Colors.orange) : null, bold: locked),
                  if (reached) InfoBox('${lk['reach_time'] ?? '-'} 도달'),
                  if (reached) InfoBox('풀림 $rel회${(lk['release_min'] as num? ?? 0) > 0 ? ' (${lk['release_min']}분)' : ''}',
                      color: rel == 0 ? Colors.teal : (rel == 1 ? Colors.orange : Colors.red)),
                  if (r['chg_pct'] is num) InfoBox('오늘 ${pct(r['chg_pct'] as num)}', color: upColor),
                  if (r['value'] is num) InfoBox('${((r['value'] as num) / 1e8).toStringAsFixed(0)}억'),
                  if (nl != null)
                    InfoBox('뉴스 ${const {'pos': '호재', 'neg': '악재', 'severe': '심각 악재'}[nl] ?? nl}',
                        color: nl == 'pos' ? upColor : downColor, bold: nl == 'severe'),
                ]),
                if (bk['at_limit'] == true) ...[
                  const SizedBox(height: 3),
                  infoBoxes([
                    InfoBox('잔량 ${num0(bk['bid_qty'] as num?)}주', bold: true),
                    if (bk['bid_value_ratio'] is num)
                      InfoBox('거래대금의 ${((bk['bid_value_ratio'] as num) * 100).toStringAsFixed(0)}%'),
                    if (bk['bid_float_pct'] is num) InfoBox('상장주식의 ${(bk['bid_float_pct'] as num).toStringAsFixed(2)}%'),
                    if (bk['chg1'] is num)
                      InfoBox('1분 ${(bk['chg1'] as num) >= 0 ? '+' : ''}${((bk['chg1'] as num) * 100).toStringAsFixed(0)}%',
                          color: (bk['chg1'] as num) >= 0 ? upColor : downColor),
                  ]),
                ],
                const SizedBox(height: 3),
                infoBoxes([
                  InfoBox('매수 ${num0(r['entry'] as num?)}', bold: true),
                  InfoBox('무효 ${num0(r['stop'] as num?)}${r['loss_pct'] is num ? ' (${r['loss_pct']}%)' : ''}', color: downColor),
                  if (r['limit'] is num) InfoBox('상한가 ${num0(r['limit'] as num?)}'),
                ]),
                for (final x in ex) Text('⛔ $x', style: t.bodySmall?.copyWith(color: Colors.red)),
                NewsLine(asList(r['news'])), // 뉴스 제목 1개 (악재 먼저 · 전체는 눌러서 상세 화면)
                for (final x in risks) Text('⚠ $x', style: t.bodySmall?.copyWith(color: Colors.orange)),
                if (r['fill_warn'] != null) Text('ⓘ ${r['fill_warn']}', style: t.bodySmall?.copyWith(color: Colors.grey)),
                if (reasons.isNotEmpty) Text(reasons.join(' · '), style: t.bodySmall?.copyWith(color: Colors.grey)),
                if (showRules && st == '매수 검토') ...[
                  const SizedBox(height: 4),
                  Text('다음 날 매도 (${r['exit_time'] ?? '09:30'} 까지)', style: t.bodySmall?.copyWith(fontWeight: FontWeight.bold)),
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

/// 관심 > 상한가포착 탭 — 장중 1분마다 새로고침 · 도달 / 미도달 나눠서
class LimitcatchTab extends StatefulWidget {
  const LimitcatchTab({super.key});
  @override
  State<LimitcatchTab> createState() => _LimitcatchTabState();
}

class _LimitcatchTabState extends State<LimitcatchTab> with AutomaticKeepAliveClientMixin {
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
      if (lcWindow()) _load();
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final d = await Api.limitcatch();
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
    final hit = items.where((r) => r['group'] == '도달').toList();
    final near = items.where((r) => r['group'] != '도달').toList();
    Widget section(String title, String sub, List<Json> rows) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 10, 4, 2),
            child: Text.rich(TextSpan(children: [
              TextSpan(text: '$title ${rows.length}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              TextSpan(text: '  $sub', style: t.bodySmall?.copyWith(color: Colors.grey)),
            ])),
          ),
          if (rows.isEmpty) Padding(padding: const EdgeInsets.all(12), child: Text('없음', style: t.bodySmall)),
          ...rows.asMap().entries.map((e) => LimitcatchTile(r: e.value, rank: e.key + 1, showRules: true)),
        ]);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 24), children: [
        if (useCloud && isAdminUser)
          Row(children: [
            Text('상한가포착', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            const Spacer(),
            DaytradeFindButton(kind: 'limitcatch', onDone: _load),
          ]),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 4),
          child: Text(
              today
                  ? '${lookupLabel(d, _at)}${d['final'] == true ? ' (오늘 마지막)' : lcWindow() ? ' · 1분마다 갱신' : ''} · 대상 ${d['scanned'] ?? 0} · '
                      '매수 검토 ${c['매수 검토'] ?? 0} · 강세 후보 ${c['강세 후보'] ?? 0} · 관찰 ${c['관찰'] ?? 0} · 조건 무효 ${c['조건 무효'] ?? 0}'
                  : '오늘 상한가포착 결과가 아직 없어요. 평일 PC 에서 22_intraday.bat(당일매매 통합)을 켜 두면 09:05~15:20 동안 1분마다 올라와요. '
                      'PC 가 꺼진 날은 관리자 [종목찾기].${d['date'] != null ? ' (아래는 ${d['date']} ${d['time']} 결과)' : ''}',
              style: t.bodySmall),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 6),
          child: Text('강세 후보 = +20% 이상 · 거래대금 100억 이상 · 75점 이상. 매수 검토 = 그중 상한가에 잠겼거나 +27% 이상 · 풀림 0~1회'
              '(1회면 3분 안에 다시 잠김) · 잔량 급감 같은 위험 신호 없음. +27% 는 유지를 보장하지 않아요 — 잔량이 유지되는지 같이 보세요. '
              '상한가 줄에 서도 체결되지 않을 수 있어요. 무효 = 전일 종가 +20% (여기 아래로 밀리면 들고 가지 않음). 주문은 하지 않는 알림용이에요.',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
        ),
        if (items.isEmpty)
          const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('지금 +20% 이상인 종목이 없어요')))
        else ...[
          section('상한가 도달', '잠김·풀림·잔량으로 평가', hit),
          section('미도달', '+20% 이상 · 매수·매도 잔량과 최근 흐름으로 평가', near),
        ],
      ]),
    );
  }
}

/// 검증 > 상한가포착: 실전 기록 + 점수 구간별 유지율 + 되돌려 보기(과거 1분봉 · 5년 일봉)
Future<Json> loadLimitcatchValidation() => Api.latestBacktest(strategy: 'LIMIT');

class LimitcatchValidation extends StatelessWidget {
  const LimitcatchValidation({super.key, required this.future});
  final Future<Json> future;

  static const _assume = {'a1': '① +27% 첫 분 종가 체결', 'a2': '② 도달 후 풀렸을 때만 체결 (보수적)', 'a3': '③ 도달 분 무조건 체결 (낙관)'};

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return FutureBuilder<Json>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) return const SizedBox.shrink();
        final d = snap.data ?? const {};
        final mins = asMap(d['minutes']);
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SectionTitle('상한가포착 검증', trailing: Text('${d['updated'] ?? ''}', style: t.bodySmall)),
          Text('손익은 비용 0.25% 뺀 %. 규칙 = 다음 날 시가 절반 · 09:30 까지 고점 −3% · 09:30 청산 (그날 +20% 아래로 밀리면 무효 매도). '
              '잠김 = 그날 종가까지 상한가 유지 비율. 최대 하락 = 매수 뒤 그날 가장 낮은 가격',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          const SizedBox(height: 6),
          _block(context, '실전 기록 (처음 매수 검토된 시점)', asMap(d['forward']),
              empty: '아직 기록이 없어요. 장중에 매수 검토 종목이 나오면 다음 날 저녁 배치가 결과를 매겨요.', fill: true),
          _block(context, '점수 구간별 (마지막 목록 · 종가 매수 → 다음 날 시가)', asMap(d['finals']),
              empty: '아직 기록이 없어요.', openOnly: true),
          for (final e in _assume.entries)
            _block(context, '과거 1분봉 · ${e.value}', asMap(mins[e.key]),
                empty: '아직 없어요. PC 에서 20_limitcatch_backtest.bat 을 실행하면 계산해요.',
                note: mins['note'] as String?, unfilled: e.key == 'a2' ? mins['unfilled_a2'] as num? : null),
          _daily(context, asMap(d['daily'])),
        ]);
      },
    );
  }

  Widget _block(BuildContext context, String title, Json r,
      {required String empty, bool fill = false, bool openOnly = false, String? note, num? unfilled}) {
    final t = Theme.of(context).textTheme;
    final tot = asMap(r['total']);
    final groups = <MapEntry<String, Json>>[
      MapEntry('전체', tot),
      for (final e in asMap(r['by_score']).entries) MapEntry('점수 ${e.key}', asMap(e.value)),
      for (final e in asMap(r['by_time']).entries)
        if (e.key != '-') MapEntry('도달 ${e.key}', asMap(e.value)),
      for (final e in asMap(r['by_group']).entries)
        if (e.key == '미도달') MapEntry(e.key, asMap(e.value)),
      if (fill) for (final e in asMap(r['by_fill']).entries) MapEntry(e.key, asMap(e.value)),
    ];
    String p(dynamic v) => v == null ? '-' : '$v%';
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: t.titleSmall),
          if ((tot['n'] ?? 0) == 0)
            Padding(padding: const EdgeInsets.only(top: 4), child: Text(empty, style: t.bodySmall))
          else ...[
            Text('${r['first'] ?? ''} ~ ${r['last'] ?? ''} · ${r['days'] ?? 0}일${note != null ? ' · $note' : ''}'
                '${unfilled != null ? ' · 끝까지 잠겨 못 산 날 $unfilled건' : ''}',
                style: t.bodySmall?.copyWith(color: Colors.grey)),
            const SizedBox(height: 6),
            StatTable(
                header: openOnly
                    ? const ['구분', '건수', '잠김', '승률', '시가']
                    : const ['구분', '건수', '잠김', '승률', '평균', '시가', '최대↓', '무효'],
                rows: [
                  for (final g in groups)
                    openOnly
                        ? [StatCell(g.key), StatCell('${g.value['n'] ?? 0}'), StatCell(p(g.value['hold'])),
                           StatCell(p(g.value['win'])), pnlCell(g.value['open_pnl'] as num?, bold: true)]
                        : [StatCell(g.key), StatCell('${g.value['n'] ?? 0}'), StatCell(p(g.value['hold'])),
                           StatCell(p(g.value['win'])), pnlCell(g.value['pnl'] as num?, bold: true),
                           pnlCell(g.value['open_pnl'] as num?), pnlCell(g.value['max_dd'] as num?, d: 1),
                           StatCell(p(g.value['invalid']), color: downColor)],
                ]),
          ],
        ]),
      ),
    );
  }

  Widget _daily(BuildContext context, Json d) {
    final t = Theme.of(context).textTheme;
    if ((d['n'] ?? 0) == 0) return const SizedBox.shrink();
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('5년 일봉 참고 (상한가 도달일 · 거래대금 100억↑)', style: t.titleSmall),
          Text('${d['first'] ?? ''} ~ ${d['last'] ?? ''} · ${d['n']}건 · 종가까지 잠김 ${d['hold'] ?? '-'}%',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          const SizedBox(height: 6),
          StatTable(header: const ['구분', '건수', '승률', '상한가→시가', '종가→시가'], rows: [
            for (final k in const ['종가 잠김', '도달 후 풀림'])
              if (d[k] != null)
                [StatCell(k), StatCell('${asMap(d[k])['n']}'), StatCell('${asMap(d[k])['win']}%'),
                 pnlCell(asMap(d[k])['lim_pnl'] as num?, bold: true), pnlCell(asMap(d[k])['close_pnl'] as num?)],
          ]),
          Text('상한가→시가 = 상한가에 샀다고 보고 다음 날 시가에 판 경우 (체결 여부는 모름 — 위쪽 분봉 검증의 ② 참고)',
              style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
        ]),
      ),
    );
  }
}
