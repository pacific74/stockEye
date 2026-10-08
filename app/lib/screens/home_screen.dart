import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../live.dart';
import '../today_picks.dart';
import '../v3.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'admin_screen.dart';
import 'orders_screen.dart';
import 'sector_screen.dart';
import 'stock_detail_screen.dart';

/// 메인 화면 = 오늘, 지금 기준
///   지금 시장 → 오늘 살 만한 후보(지금 가격 기준) → TOP 10 지금 시세 → 내 보유종목 지금
///   → 돈이 몰리는 업종 (오늘 | 어제) → 후보 보기
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<Json> _f;
  Json? _report;
  List<Json> _holdings = const [];
  Map<String, Json> _meta = const {}; // 보유종목 점수·시장 (최근 분석)
  List<Json> _pool = const []; // 어제 분석의 모든 후보 (지금 매수구간 계산용)
  LiveResult? _idx, _stk;
  bool _liveBusy = false;
  DateTime? _liveAt; // 마지막으로 시세를 받은 기기 시각
  Timer? _timer;
  int _lastTap = tabTap.value;

  @override
  void initState() {
    super.initState();
    _load();
    tabTap.addListener(_onTab);
  }

  @override
  void dispose() {
    _timer?.cancel();
    tabTap.removeListener(_onTab);
    super.dispose();
  }

  /// 하단 '오늘' 탭을 누르면 지금 시세를 다시 받기
  void _onTab() {
    if (tabTap.value == _lastTap) return;
    _lastTap = tabTap.value;
    if (tabIndex.value == 0 && _report != null) _refreshLive();
  }

  void _load() {
    _f = Api.dashboard();
    _f.then(_afterReport, onError: (_) {});
  }

  void _reload() => setState(_load);

  Future<void> _afterReport(Json d) async {
    _report = d;
    try {
      _holdings = await Api.journal(status: 'open');
    } catch (_) {
      _holdings = const [];
    }
    _meta = await Api.stockMeta(_holdings.map((h) => '${h['code']}').toList());
    try {
      _pool = await Api.allCandidates();
    } catch (_) {
      _pool = const [];
    }
    await _refreshLive();
  }

  Future<void> _refreshLive() async {
    if (_liveBusy || _report == null || !mounted) return;
    setState(() => _liveBusy = true);
    // 모두에게 같은 종목 묶음(후보·업종 대표) / 내 보유종목은 따로 → 서버 캐시를 같이 씀
    final common = <String>{
      ...asList(_report!['top10']).map((c) => '${c['code']}'),
      ..._pool.map((c) => '${c['code']}'),
      for (final g in asList(_report!['sectors'])) ...asList(g['top']).map((m) => '${m['code']}'),
    }.toList();
    final mine = _holdings.map((h) => '${h['code']}').where((c) => !common.contains(c)).toList();
    final r = await Future.wait([Live.indices(), Live.stocks(common), Live.stocks(mine)]);
    if (!mounted) return;
    setState(() {
      _idx = r[0];
      _stk = Live.merge([r[1], r[2]]);
      _liveAt = DateTime.now();
      _liveBusy = false;
    });
    _schedule();
  }

  MarketClock get _clock {
    final k = _idx?.quotes['KOSPI'];
    return MarketClock(MarketClock.kstNow(), indexStatus: k?.status, lastTrade: k?.tradedAt);
  }

  /// 장중 1분, 장 전후 5분마다 시세 자동 새로고침 (다른 탭을 보고 있을 땐 쉼)
  void _schedule() {
    _timer?.cancel();
    final every = _clock.refreshEvery;
    if (every == null) return;
    _timer = Timer(every, () {
      if (!mounted) return;
      if (tabIndex.value == 0 && ModalRoute.of(context)?.isCurrent != false) {
        _refreshLive();
      } else {
        _schedule();
      }
    });
  }

  Future<void> _pullRefresh() async {
    _load();
    setState(() {});
    try {
      await _f;
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const LogoTitle('StockEye', bold: true),
        actions: topActions(context, onRefresh: _reload),
      ),
      body: Loader<Json>(
        future: _f,
        onRetry: _reload,
        builder: (context, d) {
          final m = asMap(d['market']);
          final sectors = asList(d['sectors']);
          final top10 = asList(d['top10']);
          final clock = _clock;
          final repDate = '${d['date']}';
          final intraday = asMap(d['market'])['intraday'] as String?; // 장중 재분석 시각 ("11:00")
          final repLabel = intraday != null
              ? '${_dateLabel(repDate, clock.now)} $intraday 장중'
              : _dateLabel(repDate, clock.now);
          final repBasis = intraday != null ? repLabel : '$repLabel 마감'; // "오늘(10/8) 11:00 장중" / "10/7 마감"
          final quotes = _stk?.quotes ?? const <String, LiveQuote>{};
          const weak = <String>{}; // V3: 시장 필터 없음 (비중 고정)
          final t = Theme.of(context).textTheme;
          return RefreshIndicator(
            onRefresh: _pullRefresh,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 32),
              children: [
                _NowHeader(clock: clock, busy: _liveBusy, at: _liveAt, onRefresh: _refreshLive),
                const PendingUsersBanner(),
                const _TradingBanner(),
                if (asMap(m['v3']).isNotEmpty) ...[
                  SectionTitle('V3 기준 전략',
                      trailing: TextButton(onPressed: () => goTab(context, 1, list: 'v3'), child: const Text('상위 10'))),
                  V3HomeCard(meta: asMap(m['v3'])),
                ],
                const SectionTitle('지금 시장'),
                _LiveMarketCard(live: _idx, yesterday: m, busy: _liveBusy && _idx == null, weak: weak),
                SectionTitle('V3 상위 10 · 지금 시세', trailing: Text('$repLabel 분석', style: t.bodySmall)),
                if (_stk?.error != null && quotes.isEmpty)
                  _Notice('지금 시세를 가져오지 못해 $repBasis 가격으로 보여줍니다. (${_stk!.error})'),
                ...top10.map((c) => _LiveCandidateTile(c: c, q: quotes['${c['code']}'], clock: clock)),
                if (_holdings.isNotEmpty) ...[
                  SectionTitle('내 보유종목 · 지금',
                      trailing: TextButton(onPressed: () => goTab(context, 2), child: const Text('보유 탭'))),
                  ..._holdings.map((h) => _HoldingNowTile(
                      h: h,
                      q: quotes['${h['code']}'],
                      meta: _meta['${h['code']}'] ?? const {},
                      sellDate: holdingSellDate(asMap(m['v3']), '${h['entry_time'] ?? ''}'.length >= 10 ? '${h['entry_time']}'.substring(0, 10) : null),
                      today: repDate)),
                ],
                SectionTitle('돈이 몰리는 업종',
                    trailing: TextButton(
                        onPressed: () =>
                            Navigator.push(context, MaterialPageRoute(builder: (_) => const SectorListScreen())),
                        child: const Text('전체'))),
                _SectorCompare(
                    today: sectorsToday(sectors, quotes),
                    yesterday: sectors,
                    todayLabel: _liveAt == null ? '오늘' : '오늘 ${_hm(_liveAt!)}',
                    yesterdayLabel: repBasis),
                const SizedBox(height: 16),
                Text('규칙 기반 분석 결과이며 투자 권유가 아닙니다. 최종 판단과 책임은 본인에게 있습니다. '
                    '지금 시세는 네이버 금융 기준이며 약간 늦을 수 있습니다.',
                    style: t.bodySmall),
              ],
            ),
          );
        },
      ),
    );
  }

  static String _hm(DateTime t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  /// '2026-10-07' → 오늘이면 '오늘(10/8)', 아니면 '10/7'
  static String _dateLabel(String ymd, DateTime now) {
    final d = DateTime.tryParse(ymd);
    if (d == null) return ymd;
    final md = '${d.month}/${d.day}';
    return (d.year == now.year && d.month == now.month && d.day == now.day) ? '오늘($md)' : md;
  }
}

/// 맨 위: 10월 8일 (목) 09:12 기준 · 장중
class _NowHeader extends StatelessWidget {
  const _NowHeader({required this.clock, required this.busy, required this.at, required this.onRefresh});
  final MarketClock clock;
  final bool busy;
  final DateTime? at;
  final VoidCallback onRefresh;

  static const _wd = ['월', '화', '수', '목', '금', '토', '일'];

  @override
  Widget build(BuildContext context) {
 // 시세를 받은 시각 (한국 시간), 아직 못 받았으면 지금
    final n = at == null ? clock.now : at!.toUtc().add(const Duration(hours: 9));
    final hm = '${n.hour.toString().padLeft(2, '0')}:${n.minute.toString().padLeft(2, '0')}';
    final label = clock.label;
    final color = label == '장중' ? upColor : (label == '휴장' ? Colors.grey : Colors.orange);
    final every = clock.refreshEvery;
    final t = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 4, 0, 0),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('${n.month}월 ${n.day}일 (${_wd[n.weekday - 1]}) $hm 기준',
                  style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(6)),
                child: Text(label, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.bold)),
              ),
            ]),
            Text(
                every == null
                    ? '시세는 새로고침할 때 갱신됩니다'
                    : '시세 ${every.inMinutes}분마다 자동 갱신',
                style: t.bodySmall),
          ]),
        ),
        busy
            ? const Padding(
                padding: EdgeInsets.all(12),
                child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)))
            : IconButton(tooltip: '지금 시세 다시 받기', icon: const Icon(Icons.sync), onPressed: onRefresh),
      ]),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 4),
        child: Text(text, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.orange)),
      );
}

/// 지금 시장: 코스피·코스닥 실시간 (못 받으면 지난 마감 값)
class _LiveMarketCard extends StatelessWidget {
  const _LiveMarketCard({required this.live, required this.yesterday, required this.busy, this.weak = const {}});
  final LiveResult? live;
  final Json yesterday;
  final bool busy;
  final Set<String> weak; // 지수가 60일선 아래인 시장

  /// V2 시장 상태 {state: A/B/C, label, why}
  Json? _state(String code) => null; // V3: 시장 상태로 매수를 막지 않음 (비중 고정)

  /// 어제 마감 기준 지수 60일선 값
  double? _ma(String code) => null;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final q = live?.quotes ?? const <String, LiveQuote>{};
    if (q.isEmpty) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: busy
              ? const Center(child: Padding(padding: EdgeInsets.all(8), child: CircularProgressIndicator()))
              : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('지금 지수를 가져오지 못했습니다', style: t.titleSmall),
                  if (live?.error != null) Text('${live!.error}', style: t.bodySmall),
                  const SizedBox(height: 8),
                  if (weak.isNotEmpty)
                    Text('시장 필터: ${weak.map(marketName).join('·')} 60일선 아래 (마감 기준) → 신규 매수 쉬기',
                        style: t.bodySmall?.copyWith(color: Colors.orange)),
                ]),
        ),
      );
    }
    final list = [q['KOSPI'], q['KOSDAQ']].whereType<LiveQuote>().toList();
    final avg = list.isEmpty ? 0.0 : list.map((e) => e.ratio).reduce((a, b) => a + b) / list.length;
    final mood = avg >= 0.5 ? '강세' : (avg <= -0.5 ? '약세' : '보합');
    final moodIcon = avg >= 0.5 ? '☀️' : (avg <= -0.5 ? '🌧️' : '⛅');
    final moodColor = mood == '강세' ? upColor : (mood == '약세' ? downColor : Colors.orange);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(children: [
          ...list.map((i) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(children: [
                  Expanded(
                      child: Row(children: [
                    Text(i.code, style: const TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(width: 6),
                    if (_state(i.code) != null)
                      _StateChip(_state(i.code)!)
                    else if (_ma(i.code) != null)
                      Text(weak.contains(i.code) ? '60일선 아래' : '60일선 위',
                          style: TextStyle(fontSize: 11, color: weak.contains(i.code) ? downColor : Colors.green)),
                  ])),
                  Text(i.price.toStringAsFixed(2), style: const TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(width: 10),
                  SizedBox(
                    width: 64,
                    child: Text('${i.change >= 0 ? '+' : ''}${i.change.toStringAsFixed(2)}',
                        textAlign: TextAlign.right, style: TextStyle(color: i.change >= 0 ? upColor : downColor)),
                  ),
                  SizedBox(
                    width: 64,
                    child: Text(pct(i.ratio),
                        textAlign: TextAlign.right,
                        style: TextStyle(color: i.ratio >= 0 ? upColor : downColor, fontWeight: FontWeight.bold)),
                  ),
                ]),
              )),
          const Divider(),
          Row(children: [
            const Expanded(child: Text('지금 분위기')),
            Text('$moodIcon $mood', style: TextStyle(color: moodColor, fontWeight: FontWeight.bold, fontSize: 16)),
          ]),
          if (weak.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(top: 8),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                  color: Colors.orange.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(8)),
              child: Row(children: [
                const Icon(Icons.pause_circle_outline, size: 18, color: Colors.orange),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                      asMap(yesterday['v2']).isNotEmpty
                          ? '${weak.map(marketName).join('·')} 하락장 → 그 시장 종목은 신규 매수 중단 (보유 종목 관리는 그대로)'
                          : '시장 필터: ${weak.map(marketName).join('·')} 지수가 60일선 아래 → '
                              '${weak.map(marketName).join('·')} 종목은 신규 매수 쉬기 (보유 종목 관리는 그대로)',
                      style: const TextStyle(fontSize: 12)),
                ),
              ]),
            ),
          if (live!.stale)
            Align(
              alignment: Alignment.centerLeft,
              child: Text('※ 최신 시세를 못 받아 조금 전 값입니다', style: t.bodySmall?.copyWith(color: Colors.orange)),
            ),
        ]),
      ),
    );
  }
}

/// 시장 상태 칩: 🟢 상승장 / 🟡 중립 / 🔴 하락장 (V2)
class _StateChip extends StatelessWidget {
  const _StateChip(this.s);
  final Json s;

  @override
  Widget build(BuildContext context) {
    final st = '${s['state']}';
    final color = st == 'A' ? Colors.green : (st == 'C' ? downColor : Colors.orange);
    final icon = st == 'A' ? '🟢' : (st == 'C' ? '🔴' : '🟡');
    return Tooltip(
      message: (s['why'] as List? ?? const []).join(' · '),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(6)),
        child: Text('$icon ${s['label'] ?? st}', style: TextStyle(fontSize: 11, color: color)),
      ),
    );
  }
}

/// TOP 10 한 줄: 지금 가격 · 오늘 등락 · 매매계획 대비 위치
class _LiveCandidateTile extends StatelessWidget {
  const _LiveCandidateTile({required this.c, required this.q, required this.clock, this.weak = false});
  final Json c;
  final LiveQuote? q;
  final MarketClock clock;
  final bool weak; // 이 종목의 시장이 60일선 아래 (시장 필터)

  @override
  Widget build(BuildContext context) {
    final plan = asMap(c['plan']);
    final score = (c['score'] as num?)?.toDouble() ?? 0;
    final verdict = '${plan['verdict'] ?? ''}';
    final t = Theme.of(context).textTheme;
    final v3 = asMap(c['v3']);
    final posText = v3['entry_day'] == true
        ? '매수 ${mdw(v3['buy_date'] as String?)} 시가 → 매도 예정 ${mdw(v3['sell_date'] as String?)}'
        : (v3['next_entry'] != null ? '참고 순위 · 다음 선정일 ${mdw(v3['next_entry'] as String?)}' : null);
    final posColor = v3['entry_day'] == true ? Colors.teal : Colors.grey;
    final nxt = q != null && !clock.open && q!.overStatus == 'OPEN' && q!.overPrice != null;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        leading: CircleAvatar(child: Text('${c['rank']}')),
        title: StockName('${c['name']}', market: c['market'] as String?, score: score),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(verdict, style: t.bodySmall?.copyWith(color: Colors.teal)),
          if (posText != null)
            Container(
              margin: const EdgeInsets.only(top: 3),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(color: posColor.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(6)),
              child: Text(posText, style: TextStyle(fontSize: 11, color: posColor)),
            ),
          if (nxt) Text('넥스트레이드 ${num0(q!.overPrice)} (${pct(q!.overRatio)})', style: t.bodySmall),
        ]),
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: q == null
              ? [
                  Text(num0(plan['price'] as num?), style: const TextStyle(fontWeight: FontWeight.bold)),
                  Text('분석일 종가', style: t.bodySmall),
                ]
              : [
                  Text(num0(q!.price), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  Text(pct(q!.ratio),
                      style: TextStyle(color: q!.ratio >= 0 ? upColor : downColor, fontWeight: FontWeight.bold)),
                ],
        ),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => StockDetailScreen(code: c['code'] as String, name: c['name'] as String))),
      ),
    );
  }

}

/// 내 보유종목 지금 손익
class _HoldingNowTile extends StatelessWidget {
  const _HoldingNowTile({required this.h, required this.q, this.meta = const {}, this.sellDate, this.today});
  final Json h;
  final LiveQuote? q;
  final Json meta; // {score, market}
  final String? sellDate; // V3 기준 매도 예정일 (매수일 포함 20거래일째)
  final String? today;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final entry = (h['entry_price'] as num?)?.toDouble();
    final qty = (h['qty'] as num?)?.toDouble();
    final price = q?.price;
    final pnl = (price != null && entry != null && entry > 0) ? (price / entry - 1) * 100 : null;
    final pnlWon = (price != null && entry != null && qty != null) ? (price - entry) * qty : null;
    String? warn;
    Color warnColor = Colors.grey;
    if (sellDate != null) {
      final due = today != null && sellDate!.compareTo(today!) <= 0;
      warn = due ? '매도 예정일 도래 (${mdw(sellDate)})' : '매도 예정 ${mdw(sellDate)}';
      warnColor = due ? Colors.orange : Colors.teal;
    }
    Color c(double v) => v >= 0 ? upColor : downColor;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        dense: true,
        title: StockName('${h['name'] ?? h['code']}',
            market: (meta['market'] ?? h['market']) as String?, score: meta['score'] as num?),
        subtitle: Text(
            [
              '매수가 ${num0(entry)}${qty == null ? '' : ' · ${num0(qty)}주'}',
              if (warn != null) warn,
            ].join(' · '),
            style: warn != null ? t.bodySmall?.copyWith(color: warnColor) : t.bodySmall),
        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
          // 오늘 시세
          Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(price == null ? '-' : num0(price), style: const TextStyle(fontWeight: FontWeight.bold)),
            Text(q == null ? '오늘 -' : '오늘 ${pct(q!.ratio)}',
                style: TextStyle(fontSize: 11, color: q == null ? Colors.grey : c(q!.ratio))),
          ]),
          Container(
              width: 1, height: 30, margin: const EdgeInsets.symmetric(horizontal: 10), color: Colors.grey.withValues(alpha: 0.3)),
          // 매수가 대비
          SizedBox(
            width: 70,
            child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(pct(pnl),
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: pnl == null ? null : c(pnl))),
              Text(pnlWon == null ? '매수가 대비' : '${pnlWon >= 0 ? '+' : ''}${num0(pnlWon.round())}',
                  style: TextStyle(fontSize: 11, color: pnlWon == null ? Colors.grey : c(pnlWon))),
            ]),
          ),
        ]),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => StockDetailScreen(code: '${h['code']}', name: '${h['name'] ?? h['code']}'))),
      ),
    );
  }
}

/// 돈이 몰리는 업종: 왼쪽 = 오늘 지금 (대표 종목 등락률 평균), 오른쪽 = 어제 마감 점수
class _SectorCompare extends StatelessWidget {
  const _SectorCompare(
      {required this.today, required this.yesterday, required this.todayLabel, required this.yesterdayLabel});
  final List<SectorToday> today;
  final List<Json> yesterday;
  final String todayLabel, yesterdayLabel;

  void _open(BuildContext context, Json g) =>
      Navigator.push(context, MaterialPageRoute(builder: (_) => SectorDetailScreen(g: g)));

  Widget _row(BuildContext context, int rank, Json g, Widget value) => InkWell(
        onTap: () => _open(context, g),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(children: [
            SizedBox(width: 18, child: Text('$rank', style: const TextStyle(fontWeight: FontWeight.bold))),
            Expanded(child: Text('${g['group']}', maxLines: 1, overflow: TextOverflow.ellipsis)),
            value,
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    Widget box(String title, String sub, List<Widget> rows) => Expanded(
          child: Card(
            margin: const EdgeInsets.symmetric(horizontal: 2, vertical: 4),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(10, 10, 10, 6),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                Text(sub, style: t.bodySmall),
                const SizedBox(height: 4),
                if (rows.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text('-', style: t.bodySmall)),
                ...rows,
              ]),
            ),
          ),
        );
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      box(todayLabel, '대표종목 등락 평균', [
        for (final (i, s) in today.take(6).indexed)
          _row(
              context,
              i + 1,
              s.g,
              Text(pct(s.avg),
                  style: TextStyle(fontWeight: FontWeight.bold, color: s.avg >= 0 ? upColor : downColor))),
      ]),
      box(yesterdayLabel, '강도 점수', [
        for (final (i, g) in yesterday.take(6).indexed)
          _row(context, i + 1, g, Text('${g['score']}', style: const TextStyle(fontWeight: FontWeight.bold))),
      ]),
    ]);
  }
}

class _TradingBanner extends StatelessWidget {
  const _TradingBanner();

  static const _modeNames = {'alert': '알림만', 'paper': '모의투자 자동', 'semi_auto': '반자동 (승인 후 주문)'};

  @override
  Widget build(BuildContext context) {
    if (useCloud && !isAdminUser) return const SizedBox.shrink(); // 실시간 매매는 관리자 계좌용
    return FutureBuilder<Json>(
      future: Api.tradingStatus(),
      builder: (context, snap) {
        if (!snap.hasData) return const SizedBox.shrink();
        final t = snap.data!;
        final pending = t['pending_orders'] as int? ?? 0;
        return Card(
          color: pending > 0 ? Colors.orange.withValues(alpha: 0.15) : null,
          child: ListTile(
            dense: true,
            leading: Icon(pending > 0 ? Icons.notifications_active : Icons.sensors,
                color: pending > 0 ? Colors.orange : null),
            title: Text(pending > 0 ? '승인 대기 주문 $pending건' : '매매 모드: ${_modeNames[t['mode']] ?? t['mode']}'),
            subtitle: Text('보유 ${t['open_positions']}종목 · 알림 ${List<String>.from(t['notify_channels'] as List).join(', ')}'
                '${t['mode'] == 'paper' ? ' · 모의 현금 ${won(t['paper_cash'] as num?)}' : ''}'),
            trailing: pending > 0 ? const Icon(Icons.chevron_right) : null,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const OrdersScreen())),
          ),
        );
      },
    );
  }
}
