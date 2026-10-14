import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../closingbet.dart';
import '../daytrade.dart';
import '../limitcatch.dart';
import '../format.dart';
import '../live.dart';
import '../plan_line.dart';
import '../today_picks.dart';
import '../v3.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'admin_screen.dart';
import 'candidate_list_screen.dart';
import 'sector_screen.dart';
import 'stock_detail_screen.dart';

/// 메인 화면 = 오늘, 지금 기준
///   지금 시장 → 돈이 몰리는 업종 (오늘 | 어제) → 금일 관심주 (후보 탭별 3개, 지금 시세) → 내 보유종목 지금
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
  Map<String, List<Json>> _picks = const {}; // 금일 관심주: 후보 탭별 상위 3
  LiveResult? _idx, _stk;
  Json _secLive = const {}; // 업종 '오늘' (sector-live 작업이 1시간마다)
  bool _liveBusy = false;
  DateTime? _liveAt; // 마지막으로 시세를 받은 기기 시각
  Timer? _timer;
  Timer? _intraTimer; // 당일단타·종가배팅 1분 새로고침 (그 시간대만)
  final Map<String, Json> _intraMeta = {}; // 'daytrade'/'closingbet'/'limitcatch' → {date,time} 계산 시각
  static const _intraKeys = {'daytrade', 'closingbet', 'limitcatch'}; // PC 가 장중에 올리는 탭
  final Map<String, DateTime> _intraAt = {}; // 앱이 읽은 시각
  int _lastTap = tabTap.value;

  @override
  void initState() {
    super.initState();
    _load();
    tabTap.addListener(_onTab);
    _intraTimer = Timer.periodic(const Duration(seconds: 60), (_) {
      // 당일단타·상한가포착·종가배팅은 하단 '당일매매'(관리자)로 옮김 (2026-10-13)
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _intraTimer?.cancel();
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

  /// 종가배팅 [종목찾기] 끝 → 종가배팅 3개만 다시 읽기
  Future<void> _reloadClosingbet() async {
    final d = await Api.closingbet();
    if (!mounted) return;
    setState(() {
      _picks = {..._picks, 'closingbet': dtIsToday(d) ? asList(d['items']).take(3).toList() : <Json>[]};
      _intraMeta['closingbet'] = d;
      _intraAt['closingbet'] = DateTime.now();
    });
  }

  /// 상한가포착 메인 3개: 매수 검토 → 강세 후보 → 관찰 순 (조건 무효·제외는 빼고)
  static List<Json> _lcTop(Json d) => dtIsToday(d)
      ? asList(d['items']).where((r) => const ['매수 검토', '강세 후보', '관찰'].contains(r['status'])).take(3).toList()
      : <Json>[];

  /// 상한가포착 [종목찾기] 끝 · 장중 1분마다 → 상한가포착 3개만 다시 읽기
  Future<void> _reloadLimitcatch() async {
    final d = await Api.limitcatch();
    if (!mounted) return;
    setState(() {
      _picks = {..._picks, 'limitcatch': _lcTop(d)};
      _intraMeta['limitcatch'] = d;
      _intraAt['limitcatch'] = DateTime.now();
    });
  }

  /// 당일단타 [종목찾기] 끝 → 당일단타 3개만 다시 읽기
  Future<void> _reloadDaytrade() async {
    final d = await Api.daytrade();
    if (!mounted) return;
    setState(() {
      _picks = {..._picks, 'daytrade': dtIsToday(d) ? asList(d['items']).take(3).toList() : <Json>[]};
      _intraMeta['daytrade'] = d;
      _intraAt['daytrade'] = DateTime.now();
    });
  }

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
    // 금일 관심주: 후보 메뉴의 탭마다 점수 높은 3개 (새 탭이 생기면 자동으로 같이)
    //   관심 목록과 똑같이: 저장 순위(rank)로 30개를 받아 점수순으로 다시 정렬 → 상위 3
    //   (예전엔 rank 순 10개만 받아 정렬해서, rank 11~30 에 점수 높은 종목이 있으면 목록 탭과 달랐음)
    // 당일단타·상한가포착은 메인에서 뺌 → 하단 '당일매매' (관리자)
    final keys = CandidateListScreen.keys.where((k) => !_intraKeys.contains(k)).toList();
    final lists = await Future.wait(keys.map((k) => _intraKeys.contains(k)
        // 당일단타·상한가포착·종가배팅: PC 가 올린 오늘 후보 상위 3 (오늘 것이 아니면 비움)
        ? (switch (k) { 'daytrade' => Api.daytrade(), 'limitcatch' => Api.limitcatch(), _ => Api.closingbet() }).then((d) {
            _intraMeta[k] = d;
            _intraAt[k] = DateTime.now();
            if (k == 'limitcatch') return _lcTop(d);
            return dtIsToday(d) ? asList(d['items']).take(3).toList() : <Json>[];
          }, onError: (_) => <Json>[])
        : Api.candidates(k)
        .then((d) => sortByScore(asList(d['candidates'])).take(3).toList(), onError: (_) => <Json>[])));
    _picks = {for (var i = 0; i < keys.length; i++) keys[i]: lists[i]};
    await _refreshLive();
  }

  Future<void> _refreshLive() async {
    if (_liveBusy || _report == null || !mounted) return;
    setState(() => _liveBusy = true);
    // 모두에게 같은 종목 묶음(후보·업종 대표) / 내 보유종목은 따로 → 서버 캐시를 같이 씀
    final common = <String>{
      ...asList(_report!['top10']).map((c) => '${c['code']}'),
      for (final l in _picks.values) ...l.map((c) => '${c['code']}'),
      ..._pool.map((c) => '${c['code']}'),
    }.toList();
    final mine = _holdings.map((h) => '${h['code']}').where((c) => !common.contains(c)).toList();
    final r = await Future.wait([Live.indices(), Live.stocks(common), Live.stocks(mine)]);
    final sl = await Api.sectorsLive().catchError((_) => <String, dynamic>{});
    if (!mounted) return;
    setState(() {
      _secLive = sl;
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
          final top10 = sortByScore(asList(d['top10'])); // V3 점수 높은 순
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
                // (매매 모드 배너 · V3 기준 전략 카드는 홈에서 뺌 — 후보 탭 'V3 기준'에서 확인)
                const SectionTitle('지금 시장'),
                _LiveMarketCard(live: _idx, yesterday: m, busy: _liveBusy && _idx == null, weak: weak),
                SectionTitle('업종/테마 강도',
                    trailing: TextButton(
                        onPressed: () =>
                            Navigator.push(context, MaterialPageRoute(builder: (_) => const SectorListScreen())),
                        child: const Text('전체'))),
                () {
                  // 왼쪽 = 오늘: sector-live (업종 전체 종목 · 시가총액 가중, 1시간마다). 아직 안 돌았으면 비워 둠
                  //   (예전엔 대표 종목 5개 평균을 보여줬는데 업종 전체와 달라서 뺌 — 2026-10-13)
                  final byName = {for (final g in sectors) '${g['group']}': g};
                  final liveToday = dtIsToday(_secLive) && asList(_secLive['groups']).isNotEmpty;
                  final today = liveToday
                      ? [
                          for (final x in asList(_secLive['groups']))
                            if ((x['chg_pct'] as num?) != null)
                              ({...(byName['${x['group']}'] ?? {'group': x['group']}), 'today': x, 'today_time': _secLive['time']},
                               (x['chg_pct'] as num).toDouble()),
                        ]
                      : <(Json, double)>[];
                  final prevDate = '${d['sectors_prev_date'] ?? repDate}';
                  final prev = [
                    for (final g in asList(d['sectors_prev']))
                      if ((g['ret1_pct'] as num?) != null) (g, (g['ret1_pct'] as num).toDouble()),
                  ]..sort((a, b) => b.$2.compareTo(a.$2));
                  final pl = _dateLabel(prevDate, clock.now);
                  return _SectorCompare(
                    today: today,
                    todayLabel: liveToday ? '오늘 ${_secLive['time']}' : (_liveAt == null ? '오늘' : '오늘 ${_hm(_liveAt!)}'),
                    todaySub: liveToday ? '업종 전체 종목 · 시가총액 가중 · 1시간마다' : '09:10부터 1시간마다 업종 전체 집계 (아직 전)',
                    prev: prev,
                    prevLabel: pl.startsWith('오늘') ? '$pl 마감' : '전일($pl) 마감',
                    prevSub: '업종 전체 종목 · 시가총액 가중',
                  );
                }(),
                if (_stk?.error != null && quotes.isEmpty)
                  _Notice('지금 시세를 가져오지 못해 $repBasis 가격으로 보여줍니다. (${_stk!.error})'),
                // 후보 탭별 3개 (탭 데이터를 못 받으면 V3 상위 3)
                for (final k in (_picks.isEmpty ? const ['v3'] : _picks.keys)) ...[
                  Padding(
                    padding: const EdgeInsets.fromLTRB(4, 8, 0, 0),
                    child: Row(children: [
                      Text(strategyLabels[k] ?? k, style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                      const SizedBox(width: 6),
                      // 조회 시각(당일단타·종가배팅)은 가운데를 채우고, 버튼은 맨 오른쪽에
                      Expanded(
                          child: _intraKeys.contains(k) && _intraMeta[k] != null
                              ? Text(lookupLabel(_intraMeta[k]!, _intraAt[k]),
                                  overflow: TextOverflow.ellipsis, style: t.bodySmall?.copyWith(color: Colors.grey))
                              : const SizedBox.shrink()),
                      if (k == 'daytrade') DaytradeFindButton(onDone: _reloadDaytrade),
                      if (k == 'closingbet') DaytradeFindButton(closing: true, onDone: _reloadClosingbet),
                      if (k == 'limitcatch') DaytradeFindButton(kind: 'limitcatch', onDone: _reloadLimitcatch),
                      TextButton(onPressed: () => goTab(context, 1, list: k), child: const Text('전체')),
                    ]),
                  ),
                  if ((_picks[k] ?? (k == 'v3' ? top10.take(3).toList() : const <Json>[])).isEmpty)
                    Padding(
                        padding: const EdgeInsets.fromLTRB(8, 0, 8, 4),
                        child: Text(
                            k == 'daytrade'
                                ? '평일 09:00~10:00 PC 에서 당일단타를 켜 두면 여기에 나와요'
                                : k == 'closingbet'
                                    ? '종가배팅 [종목찾기]를 누르거나 PC 에서 켜 두면 여기에 나와요'
                                    : k == 'limitcatch'
                                        ? (dtIsToday(_intraMeta[k] ?? const <String, dynamic>{})
                                            ? '지금 +20% 이상 · 거래대금 100억 이상인 종목이 없어요'
                                            : '평일 장중 PC 에서 상한가포착을 켜 두거나 [종목찾기]를 누르면 여기에 나와요')
                                        : '오늘 조건을 만족한 종목이 없습니다',
                            style: t.bodySmall)),
                  if (k == 'daytrade')
                    ...(_picks[k] ?? const <Json>[]).asMap().entries.map((e) =>
                        DaytradeTile(r: e.value, rank: e.key + 1, price: quotes['${e.value['code']}']?.price))
                  else if (k == 'closingbet')
                    ...(_picks[k] ?? const <Json>[]).asMap().entries.map((e) =>
                        ClosingbetTile(r: e.value, rank: e.key + 1, price: quotes['${e.value['code']}']?.price))
                  else if (k == 'limitcatch')
                    ...(_picks[k] ?? const <Json>[]).asMap().entries.map((e) =>
                        LimitcatchTile(r: e.value, rank: e.key + 1, price: quotes['${e.value['code']}']?.price))
                  else
                  ...(_picks[k] ?? (k == 'v3' ? top10.take(3).toList() : const <Json>[])).asMap().entries.map((e) =>
                      _LiveCandidateTile(
                          c: {...e.value, 'rank': e.key + 1, '_tab': k}, q: quotes['${e.value['code']}'], clock: clock)),
                ],
                if (_holdings.isNotEmpty) ...[
                  SectionTitle('보유종목',
                      trailing: TextButton(onPressed: () => goTab(context, 2), child: const Text('전체'))),
                  _HoldingsTable(holdings: _holdings, quotes: quotes, meta: _meta),
                ],
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

  /// 관심 목록 카드와 같은 점수 (탭별 점수)
  static num? _score(Json c, String? tab) {
    if (tab != null && c[tab] is Map && asMap(c[tab])['score'] is num) return asMap(c[tab])['score'] as num;
    return c['score'] as num?;
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final tab = c['_tab'] as String?;
    final nxt = q != null && !clock.open && q!.overStatus == 'OPEN' && q!.overPrice != null;
    // 관심 목록(WatchTile)과 같은 모양: 순위 · 종목명 · 현재가 · 점수 · 경고 · 매수구간 · 목표/손절/손익비
    return WatchTile(
      c: c,
      price: q?.price,
      tab: tab,
      leading: CircleAvatar(child: Text('${c['rank']}')),
      score: _score(c, tab),
      scoreDigits: tab == 'v3' ? 0 : 1,
      extra: nxt
          ? Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text('넥스트레이드 ${num0(q!.overPrice)} (${pct(q!.overRatio)})', style: t.bodySmall))
          : null,
      onTap: () => Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => StockDetailScreen(code: c['code'] as String, name: c['name'] as String, source: tab))),
    );
  }
}


/// 업종/테마 강도: 왼쪽 = 오늘(업종 전체 종목 등락, 1시간마다), 오른쪽 = 전일 마감 (같은 방식) — 높은 순 6개
class _SectorCompare extends StatelessWidget {
  const _SectorCompare(
      {required this.today,
      required this.todayLabel,
      required this.todaySub,
      required this.prev,
      required this.prevLabel,
      required this.prevSub});
  final List<(Json, double)> today, prev;
  final String todayLabel, todaySub, prevLabel, prevSub;

  void _open(BuildContext context, Json g) =>
      Navigator.push(context, MaterialPageRoute(builder: (_) => SectorDetailScreen(g: g)));

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    Widget row(int rank, Json g, double v) => InkWell(
          onTap: () => _open(context, g),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(children: [
              SizedBox(width: 18, child: Text('$rank', style: const TextStyle(fontWeight: FontWeight.bold))),
              Expanded(child: Text('${g['group']}', maxLines: 1, overflow: TextOverflow.ellipsis)),
              Text(pct(v), style: TextStyle(fontWeight: FontWeight.bold, color: v >= 0 ? upColor : downColor)),
            ]),
          ),
        );
    Widget box(String title, String sub, List<(Json, double)> rows) => Expanded(
          child: Card(
            margin: const EdgeInsets.symmetric(horizontal: 2, vertical: 4),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(10, 10, 10, 6),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Text('업종 상위', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                  const Spacer(),
                  Flexible(
                      child: Text(title,
                          overflow: TextOverflow.ellipsis, style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold))),
                ]),
                Text(sub, style: t.bodySmall?.copyWith(color: Colors.grey)),
                const SizedBox(height: 4),
                if (rows.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text('-', style: t.bodySmall)),
                for (final (i, r) in rows.take(6).indexed) row(i + 1, r.$1, r.$2),
              ]),
            ),
          ),
        );
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      box(todayLabel, todaySub, today),
      box(prevLabel, prevSub, prev),
    ]);
  }
}

/// 보유종목 표: 종목명(시장·점수 / 지금 매수구간·관심 출처) | 매수가 | 현재가(오늘 등락) | 수익률(손익)
class _HoldingsTable extends StatelessWidget {
  const _HoldingsTable({required this.holdings, required this.quotes, required this.meta});
  final List<Json> holdings;
  final Map<String, LiveQuote> quotes;
  final Map<String, Json> meta;

  /// 관심 탭에서 산 종목이면 [n차 매수구간 lo~hi] · [손절가 아래] · [탭 이름]
  static List<String> _tags(Json h, double? price) {
    final o = asMap(h['origin'] ?? asMap(h['plan'])['origin']);
    final out = <String>[];
    if (price != null) {
      final stop = (o['stop'] as num?)?.toDouble();
      // 공통 규칙: 1차 목표 뒤(보유 중 최고가 ≥ 1차)엔 손절가 대신 매수가(본전) → 닿으면 남은 수량 전량 매도
      final t1 = ((o['target1'] ?? h['target1']) as num?)?.toDouble();
      final entry = (h['entry_price'] as num?)?.toDouble();
      final be = t1 != null && entry != null && (((h['max_price'] as num?)?.toDouble() ?? 0) >= t1 || price >= t1);
      if (be && price <= entry) {
        out.add('1차 뒤 본전 ${num0(entry)} 이탈 · 전량 매도');
      } else if (!be && stop != null && price <= stop) {
        out.add('손절가 ${num0(stop)} 아래');
      } else {
        for (final z in asList(o['zones'])) {
          final lo = (z['low'] as num?)?.toDouble(), hi = (z['high'] as num?)?.toDouble();
          if (lo != null && hi != null && price >= lo && price <= hi) {
            out.add('${z['name'] ?? ''} 매수구간 ${num0(lo)}~${num0(hi)}'.trim());
            break;
          }
        }
      }
    }
    for (final n in (o['names'] as List? ?? const [])) {
      out.add('$n');
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final line = Theme.of(context).dividerColor.withValues(alpha: 0.35);
    final head = t.bodySmall?.copyWith(color: Colors.grey);
    Color c(double v) => v >= 0 ? upColor : downColor;
    Widget pad(Widget w, {Alignment al = Alignment.centerRight}) =>
        Padding(padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 3), child: Align(alignment: al, child: w));
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
        child: Table(
          columnWidths: const {0: FlexColumnWidth(3.2), 1: FlexColumnWidth(1.5), 2: FlexColumnWidth(1.7), 3: FlexColumnWidth(1.5)},
          defaultVerticalAlignment: TableCellVerticalAlignment.middle,
          children: [
            TableRow(
              decoration: BoxDecoration(border: Border(bottom: BorderSide(color: line))),
              children: [
                pad(Text('종목명', style: head), al: Alignment.centerLeft),
                pad(Text('매수가', style: head)),
                pad(Text('현재가', style: head)),
                pad(Text('수익률', style: head)),
              ],
            ),
            for (final h in holdings)
              () {
                final code = '${h['code']}';
                final q = quotes[code];
                final m = meta[code] ?? const {};
                final entry = (h['entry_price'] as num?)?.toDouble();
                final qty = (h['qty'] as num?)?.toDouble();
                final price = q?.price;
                final pnl = (price != null && entry != null && entry > 0) ? (price / entry - 1) * 100 : null;
                final pnlWon = (price != null && entry != null && qty != null) ? (price - entry) * qty : null;
                final tags = _tags(h, price);
                void open() => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => StockDetailScreen(code: code, name: '${h['name'] ?? code}')));
                Widget tap(Widget w, {Alignment al = Alignment.centerRight}) =>
                    TableRowInkWell(onTap: open, child: pad(w, al: al));
                return TableRow(
                  decoration: BoxDecoration(border: Border(bottom: BorderSide(color: line.withValues(alpha: 0.25)))),
                  children: [
                    tap(
                        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          StockName('${h['name'] ?? code}',
                              market: (m['market'] ?? h['market']) as String?, score: m['score'] as num?),
                          if (tags.isNotEmpty)
                            Text(tags.map((x) => '[$x]').join(' '),
                                style: t.bodySmall?.copyWith(fontSize: 11, color: Colors.grey)),
                        ]),
                        al: Alignment.centerLeft),
                    tap(Text(num0(entry), style: t.bodySmall)),
                    tap(Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                      Text(price == null ? '-' : num0(price), style: const TextStyle(fontWeight: FontWeight.bold)),
                      if (q != null)
                        Text('${q.ratio >= 0 ? '▲' : '▼'} ${q.ratio.abs().toStringAsFixed(2)}%',
                            style: TextStyle(fontSize: 11, color: c(q.ratio))),
                    ])),
                    tap(Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                      Text(pct(pnl),
                          style: TextStyle(fontWeight: FontWeight.bold, color: pnl == null ? null : c(pnl))),
                      if (pnlWon != null)
                        Text('${pnlWon >= 0 ? '+' : ''}${num0(pnlWon.round())}',
                            style: TextStyle(fontSize: 11, color: c(pnlWon))),
                    ])),
                  ],
                );
              }(),
          ],
        ),
      ),
    );
  }
}


