import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'plan_line.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';
import 'widgets/nav.dart';
import 'widgets/top_actions.dart';

/// StockEye V3 기준 전략 (🔒 고정 규칙)
///   V3B(8항목 100점) 상위 10 → 다음 거래일 시가 매수 → 20거래일 보유 (다시 선정되면 연장, 추가매수 없음)
///   매도 예정일 = 매수일을 1일째로 세어 20거래일째 (앞으로의 휴장일은 추정 → '예정')

/// 'YYYY-MM-DD' → '10/12(월)'
String mdw(String? ymd) {
  final d = ymd == null ? null : DateTime.tryParse(ymd);
  if (d == null) return ymd ?? '-';
  const w = ['월', '화', '수', '목', '금', '토', '일'];
  return '${d.month}/${d.day}(${w[d.weekday - 1]})';
}

/// 거래일 달력에서 start 를 1일째로 셀 때 n일째 (달력 밖이면 null)
String? nthTradingDay(List<String> cal, String start, int n) {
  final k = cal.indexWhere((d) => d.compareTo(start) >= 0);
  if (k < 0 || k + n - 1 >= cal.length) return null;
  return cal[k + n - 1];
}

/// 오늘부터 그날까지 남은 거래일 수 (오늘 제외)
int? tradingDaysLeft(List<String> cal, String today, String? until) {
  if (until == null) return null;
  return cal.where((d) => d.compareTo(today) > 0 && d.compareTo(until) <= 0).length;
}

/// 문자열 목록 (asList 는 항목을 Map 으로 바꾸므로 날짜·문장 목록에는 쓰면 안 됨)
List<String> strList(dynamic v) => v is List ? v.map((e) => '$e').toList() : <String>[];

List<String> v3Calendar(Json meta) => strList(meta['calendar']);

/// 점수 높은 순 (같으면 원래 순위 순) — 서버가 매긴 V3 순위와 같지만, 예전 데이터가 섞여도 화면은 항상 점수순
List<Json> sortByScore(List<Json> cands) {
  double sc(Json c) => (c['score'] as num?)?.toDouble() ?? -1;
  double rk(Json c) => (c['rank'] as num?)?.toDouble() ?? 999;
  return List<Json>.from(cands)..sort((a, b) => sc(b) != sc(a) ? sc(b).compareTo(sc(a)) : rk(a).compareTo(rk(b)));
}

/// 내 보유종목의 V3 규칙 기준 매도 예정일 (매수일 포함 20거래일째)
String? holdingSellDate(Json meta, String? buyDate) {
  if (buyDate == null || buyDate.isEmpty) return null;
  return nthTradingDay(v3Calendar(meta), buyDate, 20);
}

/// 선정 상태 한 줄: 오늘 선정일이면 매수·매도 예정일, 아니면 다음 선정일
class V3ScheduleLine extends StatelessWidget {
  const V3ScheduleLine({super.key, required this.v});
  final Json v; // 후보의 v3 또는 리포트 v3 메타
  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    if (v['entry_day'] == true) {
      return Text('오늘 선정 → ${mdw(v['buy_date'] as String?)} 시가 매수 · 매도 예정 ${mdw(v['sell_date'] as String?)}',
          style: t.bodySmall?.copyWith(color: Colors.teal, fontWeight: FontWeight.w600));
    }
    if (v['next_entry'] != null) {
      return Text('오늘은 선정일이 아님 (참고 순위) · 다음 선정일 ${mdw(v['next_entry'] as String?)}', style: t.bodySmall);
    }
    return const SizedBox.shrink();
  }
}

/// V3 후보 한 줄: 이름 · V3B 점수(60) · 변동성/재무/가격위치 · 매수·매도 예정일
class V3PickTile extends StatelessWidget {
  const V3PickTile({super.key, required this.c, required this.rank, this.price});
  final Json c;
  final int rank;
  final double? price; // 지금 시세 (없으면 분석일 종가)

  @override
  Widget build(BuildContext context) {
    final v = asMap(c['v3']);
    return WatchTile(
      c: c,
      price: price,
      tab: 'v3',
      leading: CircleAvatar(child: Text('$rank')),
      score: v['score'] as num?,
      scoreDigits: 0,
      onTap: () => Navigator.push(context,
          MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${c['code']}', name: '${c['name']}', source: 'v3'))),
    );
  }
}

/// 홈 화면 카드: 선정 상태 · 오늘 상위 3 · 모의 보유 요약 → 누르면 V3 화면
class V3HomeCard extends StatelessWidget {
  const V3HomeCard({super.key, required this.meta});
  final Json meta;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final top = asList(meta['top']);
    final pf = asMap(meta['portfolio']);
    final tr = asMap(pf['trading']);
    final hold = asList(pf['holdings']);
    final soon = hold.where((h) => ((h['days_left'] as num?) ?? 99) <= 3).toList();
    return Card(
      child: InkWell(
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const V3Screen())),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Icon(Icons.lock_outline, size: 16, color: Colors.teal),
              const SizedBox(width: 4),
              Text('V3 기준 전략', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(width: 6),
              Text('${meta['version'] ?? ''}', style: t.bodySmall),
              const Spacer(),
              const Icon(Icons.chevron_right),
            ]),
            const SizedBox(height: 4),
            V3ScheduleLine(v: meta),
            if (top.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text('상위: ${top.take(5).map((e) => e['name']).join(', ')}${top.length > 5 ? ' 외 ${top.length - 5}' : ''}',
                  style: t.bodyMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
            ],
            const SizedBox(height: 4),
            Text(
                '모의 보유 ${hold.length}종목'
                '${tr['trades'] != null && tr['trades'] != 0 ? ' · 고정 이후 ${tr['trades']}회 매매 · 기대값 ${pct(tr['expectancy_pct'] as num?)}' : ' · 고정 이후 기록 시작'}'
                '${soon.isNotEmpty ? ' · 3거래일 안에 매도 ${soon.length}종목' : ''}',
                style: t.bodySmall),
          ]),
        ),
      ),
    );
  }
}

/// V3 화면: 오늘 선정 · 모의 보유(매도 예정일) · 고정 이후 성과 · 과거 검증 (종목 선정력 / 실제 매매 분리)
class V3Screen extends StatefulWidget {
  const V3Screen({super.key});
  @override
  State<V3Screen> createState() => _V3ScreenState();
}

class _V3ScreenState extends State<V3Screen> {
  late Future<List<dynamic>> _f = _load();

  Future<List<dynamic>> _load() async {
    final meta = await Api.v3();
    Json? hist;
    try {
      hist = await Api.latestBacktest(strategy: 'V3B'); // 관리자만 (일반 회원은 권한 없음 → 생략)
    } catch (_) {
      hist = null;
    }
    return [meta, hist];
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(title: const LogoTitle('V3 기준 전략'), actions: topActions(context, onRefresh: () => setState(() => _f = _load()))),
      body: Loader<List<dynamic>>(
        future: _f,
        onRetry: () => setState(() => _f = _load()),
        builder: (context, r) {
          final meta = asMap(r[0]);
          final hist = r[1] == null ? null : asMap(r[1]);
          final t = Theme.of(context).textTheme;
          final pf = asMap(meta['portfolio']);
          final hold = asList(pf['holdings']);
          final trades = asList(pf['recent_trades']);
          final today = '${meta['date'] ?? ''}';
          if (meta.isEmpty) {
            return const Center(child: Text('아직 V3 결과가 없습니다.\n다음 저녁 배치 이후에 나타납니다.', textAlign: TextAlign.center));
          }
          return ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 32), children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const Icon(Icons.lock_outline, size: 16, color: Colors.teal),
                    const SizedBox(width: 4),
                    Text('규칙 고정 ${meta['version']} (${meta['locked_at']})', style: const TextStyle(fontWeight: FontWeight.bold)),
                  ]),
                  const SizedBox(height: 4),
                  ...strList(meta['rules']).map((s) => Text('• $s', style: t.bodySmall)),
                  const SizedBox(height: 4),
                  Text('검증 기간 동안 점수·조건을 바꾸지 않고 결과만 기록합니다 (진짜 표본 외 검증).', style: t.bodySmall),
                ]),
              ),
            ),
            SectionTitle('오늘 V3B 상위 10 (${mdw(today)} 분석)',
                trailing: TextButton(onPressed: () => goTab(context, 1, list: 'v3'), child: const Text('목록'))),
            Padding(padding: const EdgeInsets.symmetric(horizontal: 4), child: V3ScheduleLine(v: meta)),
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 2, 4, 4),
              child: Text(asList(meta['top']).map((e) => '${e['name']} ${e['score']}').join(' · '), style: t.bodySmall),
            ),
            SectionTitle('모의 보유 ${hold.length}종목 · 매도 예정일 순', trailing: Text('고정 이후 ${mdw(pf['since'] as String?)}~', style: t.bodySmall)),
            if (hold.isEmpty)
              const Padding(padding: EdgeInsets.all(12), child: Text('아직 보유 종목이 없습니다 (첫 선정일 다음 날 시가에 매수).')),
            ...hold.map((h) => Card(
                  margin: const EdgeInsets.symmetric(vertical: 3),
                  child: ListTile(
                    dense: true,
                    title: Text('${h['name']}', style: const TextStyle(fontWeight: FontWeight.bold)),
                    subtitle: Text('매수 ${mdw(h['entry'] as String?)} · ${h['days']}일째'
                        '${(h['extends'] as num? ?? 0) > 0 ? ' (연장 ${h['extends']}회)' : ''} · 비중 ${h['weight']}%'),
                    trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                      Text('매도 예정 ${mdw(h['sell_date'] as String?)}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12)),
                      Text(pct(h['ret'] as num?),
                          style: TextStyle(color: ((h['ret'] as num?) ?? 0) >= 0 ? upColor : downColor, fontWeight: FontWeight.bold)),
                    ]),
                    onTap: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${h['code']}', name: '${h['name']}'))),
                  ),
                )),
            const SectionTitle('고정 이후 성과 (진짜 표본 외)'),
            _SelectionTable(sel: asMap(pf['selection'])),
            _TradingTable(rows: [('고정 이후', asMap(pf['trading']))]),
            if (trades.isNotEmpty) ...[
              const SectionTitle('최근 매도'),
              ...trades.take(10).map((x) => ListTile(
                    dense: true,
                    title: Text('${x['name']}'),
                    subtitle: Text('${mdw(x['entry'] as String?)} → ${mdw(x['exit'] as String?)} · ${x['why']}'),
                    trailing: Text(pct(x['ret'] as num?),
                        style: TextStyle(color: ((x['ret'] as num?) ?? 0) >= 0 ? upColor : downColor, fontWeight: FontWeight.bold)),
                  )),
            ],
            if (hist != null) ...[
              const SectionTitle('과거 검증 (규칙 고정 전 데이터)'),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Text('${hist['note'] ?? ''}', style: t.bodySmall),
              ),
              for (final p in asList(hist['periods'])) ...[
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 12, 4, 2),
                  child: Text(
                      '${p['name']} · ${p['start']} ~ ${p['end']} · 선정 ${p['entries']}회'
                      '${_bench(asMap(hist['benchmark'])['${p['name']}'])}',
                      style: const TextStyle(fontWeight: FontWeight.bold)),
                ),
                _SelectionTable(sel: asMap(p['selection'])),
                _TradingTable(rows: [('${p['name']}', asMap(p['trading']))]),
              ],
            ],
            const SizedBox(height: 12),
            Text('모의 운용 결과이며 투자 권유가 아닙니다. 매도 예정일은 앞으로의 휴장일을 추정한 날짜라 바뀔 수 있습니다.', style: t.bodySmall),
          ]);
        },
      ),
    );
  }

  static String _bench(dynamic b) {
    final m = asMap(b);
    if (m.isEmpty) return '';
    return ' · 같은 기간 KOSPI ${pct(m['KOSPI'] as num?)} / KOSDAQ ${pct(m['KOSDAQ'] as num?)}';
  }
}

/// ① 종목 선정력: 상위10 / 후보 전체 / 랜덤10 × 5·10·20·40일 (평균 · 중앙값 · 승률) + 초과수익
class _SelectionTable extends StatelessWidget {
  const _SelectionTable({required this.sel});
  final Json sel;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    if (sel.isEmpty || sel.values.every((v) => asMap(v)['top10'] == null)) {
      return Padding(
          padding: const EdgeInsets.all(8), child: Text('① 종목 선정력: 아직 기간이 지나지 않아 계산할 수 없습니다.', style: t.bodySmall));
    }
    String cell(Json? m) => m == null ? '-' : '${pct(m['mean'] as num?)}\n${pct(m['median'] as num?)} · ${m['win']}%';
    TableRow row(List<Widget> c) => TableRow(children: c.map((w) => Padding(padding: const EdgeInsets.all(4), child: w)).toList());
    final hs = ['5', '10', '20', '40'];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('① 종목 선정력 — 잘 골랐나? (다음 날 시가 → h거래일 종가, 비용 제외)', style: t.bodySmall?.copyWith(fontWeight: FontWeight.bold)),
          Text('칸: 평균 / 중앙값 · 승률', style: t.bodySmall),
          Table(
            defaultVerticalAlignment: TableCellVerticalAlignment.middle,
            columnWidths: const {0: IntrinsicColumnWidth()},
            children: [
              row([const Text(''), ...hs.map((h) => Text('$h일', style: const TextStyle(fontWeight: FontWeight.bold)))]),
              for (final g in [('V3B 상위10', 'top10'), ('후보 전체', 'all'), ('랜덤 10', 'random10')])
                row([
                  Text(g.$1, style: const TextStyle(fontSize: 12)),
                  ...hs.map((h) => Text(cell(asMap(sel[h])[g.$2] == null ? null : asMap(asMap(sel[h])[g.$2])),
                      style: const TextStyle(fontSize: 11))),
                ]),
              row([
                const Text('초과수익', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
                ...hs.map((h) {
                  final e = asMap(sel[h])['excess'] as num?;
                  return Text(pct(e),
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: (e ?? 0) >= 0 ? upColor : downColor));
                }),
              ]),
            ],
          ),
        ]),
      ),
    );
  }
}

/// ② 실제 매매: 규칙 그대로 모의 운용 (비용 포함)
class _TradingTable extends StatelessWidget {
  const _TradingTable({required this.rows});
  final List<(String, Json)> rows;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('② 실제 매매 — 돈을 벌었나? (다음 날 시가 · 20일 보유 · 비용 포함)', style: t.bodySmall?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 6),
          for (final r in rows)
            if ((r.$2['trades'] ?? 0) == 0)
              Text('${r.$1}: 아직 끝난 매매가 없습니다.', style: t.bodySmall)
            else
              Wrap(spacing: 14, runSpacing: 6, children: [
                _kv('매매', '${r.$2['trades']}회'),
                _kv('기대값', pct(r.$2['expectancy_pct'] as num?)),
                _kv('PF', '${r.$2['profit_factor'] ?? '-'}'),
                _kv('승률', '${r.$2['win_rate'] ?? '-'}%'),
                _kv('평균 이익/손실', '${pct(r.$2['avg_win_pct'] as num?)} / ${pct(r.$2['avg_loss_pct'] as num?)}'),
                _kv('총수익', pct(r.$2['total_return_pct'] as num?)),
                _kv('CAGR', r.$2['cagr_pct'] == null ? '-' : pct(r.$2['cagr_pct'] as num?)),
                _kv('MDD', pct(r.$2['mdd_pct'] as num?)),
                _kv('연속손실', '${r.$2['max_consec_losses'] ?? '-'}회'),
                _kv('평균 투자비중', '${r.$2['invested_pct'] ?? '-'}%'),
              ]),
        ]),
      ),
    );
  }

  static Widget _kv(String k, String v) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(k, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        Text(v, style: const TextStyle(fontWeight: FontWeight.bold)),
      ]);
}
