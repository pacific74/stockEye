import 'dart:async';

import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'api.dart';
import 'closingbet.dart' show ClosingbetTile;
import 'daytrade.dart' show DaytradeTile, DaytradeFindButton, dtIsToday, lookupLabel, dtMinuteBars;
import 'format.dart';
import 'limitcatch.dart' show LimitcatchTile;
import 'live.dart';
import 'screens/stock_detail_screen.dart';
import 'voice.dart';
import 'widgets/common.dart';
import 'widgets/nav.dart';
import 'widgets/price_chart.dart';
import 'widgets/top_actions.dart';

/// 하단 '당일매매' (관리자만) — 당일단타 · 상한가포착을 같은 방식으로
///   진입조건충족 : 처음 충족된 시각 순으로 고정 (그때 계획·카드 그대로) → 1분마다 상태·시각 → 매매 결과. 관리자 매매일지에 자동 기록
///   진입대기 · 관찰 : 조건에 따라 1분마다 바뀜 (매매일지 저장 안 함)
///   상한가포착은 진입조건충족 = '매수 검토', 진입대기 = '강세 후보', 관찰 = '관찰'
/// 실시간 (2026-10-13): PC 22_intraday.bat 이 KIS 실시간 체결로 고정 종목을 판단 → intraday_live 행 → 여기서 바로 반영(Realtime)
/// PC 가 꺼졌거나 멈춤(3분 넘게 갱신 없음): 고정 종목 지금가만 1분마다 네이버 시세로 보여 주고 목표·손절 위치 표시 → 결과는 저녁 배치가 1분봉으로 확정
class IntradayScreen extends StatefulWidget {
  const IntradayScreen({super.key});
  @override
  State<IntradayScreen> createState() => _IntradayScreenState();
}

/// 고정 종목 1분봉 (PC 가 1분마다 system_status 'intraday_bars' · 'closingbet_bars' 로 올림) — 종목코드 → [[HH:MM,시,고,저,종,량], ...]
Map<String, List> _minuteBars = {};

bool _marketWindow() {
  final n = DateTime.now();
  if (n.weekday > 5) return false;
  final m = n.hour * 60 + n.minute;
  return m >= 9 * 60 && m <= 15 * 60 + 35;
}

class _IntradayScreenState extends State<IntradayScreen> {
  Json? _dt, _lc, _cb; // 당일단타 · 상한가포착 · 종가배팅
  Json _cbm = {}; // 종가배팅 고정·매수 내역 (후보 실행 + 다음 날 추적 합친 것) {'tracked': [...]}
  DateTime? _at;
  Timer? _t;
  Set<String>? _buySeen, _sellSeen; // 이미 알린 매수(고정)·매도신호 — 처음 읽을 때는 알리지 않고 기억만
  RealtimeChannel? _ch;
  final Map<String, Json> _live = {}; // 실시간으로 받은 최신 추적 상태 ('종류:날짜:종목')
  DateTime? _rtAt; // 마지막 실시간 수신
  Map<String, double> _quotes = {}; // PC 꺼짐 대비: 고정 종목 지금가

  @override
  void initState() {
    super.initState();
    _load();
    _subscribe();
    _t = Timer.periodic(const Duration(seconds: 60), (_) {
      if (_marketWindow()) _load();
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    if (_ch != null) Supabase.instance.client.removeChannel(_ch!);
    super.dispose();
  }

  void _subscribe() {
    if (!useCloud) return;
    try {
      _ch = Supabase.instance.client
          .channel('intraday_live')
          .onPostgresChanges(
              event: PostgresChangeEvent.all,
              schema: 'public',
              table: 'intraday_live',
              callback: (p) {
                final r = p.newRecord;
                if (r.isEmpty || !mounted) return;
                final pl = asMap(r['payload']);
                if (pl['code'] == null) return;
                _live['${r['kind']}:${pl['date']}:${pl['code']}'] = {...pl, 'kind': r['kind']};
                _rtAt = DateTime.now();
                _applyLive();
                _announce([...asList(_dt?['tracked']), ...asList(_lc?['tracked']), ...asList(_cbm['tracked'])]);
                setState(() {});
              })
          .subscribe();
    } catch (_) {}
  }

  /// 실시간 상태를 1분 갱신본 위에 덮기 (상태가 같거나 더 나아간 것만 — 늦게 온 1분 갱신본이 되돌리지 않게)
  void _applyLive() {
    for (final (kind, d) in [('daytrade', _dt), ('limitcatch', _lc), ('closingbet', _cbm)]) {
      if (d == null) continue;
      final list = [...asList(d['tracked'])];
      for (final e in _live.entries.where((e) => e.key.startsWith('$kind:'))) {
        final pl = e.value;
        final i = list.indexWhere((x) => '${x['code']}' == '${pl['code']}' && '${x['date']}' == '${pl['date']}');
        if (i < 0) {
          if (dtIsToday({'date': pl['date']}) || pl['done'] != true) list.add(pl);
        } else if (asList(pl['events']).length >= asList(list[i]['events']).length &&
            !(list[i]['done'] == true && pl['done'] != true)) {
          list[i] = {...list[i], ...pl}; // 카드(기존 상태설명)는 1분 갱신본 것 유지
        }
      }
      list.sort((a, b) => '${a['date']} ${a['time']}'.compareTo('${b['date']} ${b['time']}'));
      d['tracked'] = list;
    }
  }

  /// 같은 종목·날짜는 더 진행된 것(끝남 > 상태 수 많음)으로
  static List<Json> _mergeTracks(List<Json> a, List<Json> b) {
    final m = <String, Json>{};
    int rank(Json t) => (t['done'] == true ? 1000 : 0) + asList(t['events']).length;
    for (final t in [...a, ...b]) {
      final k = '${t['date']}:${t['code']}';
      final o = m[k];
      if (o == null || rank(t) >= rank(o)) m[k] = {...?o, ...t};
    }
    return m.values.toList()..sort((x, y) => '${x['date']} ${x['time']}'.compareTo('${y['date']} ${y['time']}'));
  }

  /// PC 실시간이 멈췄는지: 장중(09:07 뒤)인데 3분 넘게 갱신·실시간 수신이 없고 진행 중인 고정 종목이 있음
  bool _stale(Json? d) {
    if (d == null || !_marketWindow()) return false;
    final n = DateTime.now();
    if (n.hour * 60 + n.minute < 9 * 60 + 7) return false;
    if (!asList(d['tracked']).any((x) => x['done'] != true)) return false;
    if (_rtAt != null && n.difference(_rtAt!).inMinutes < 3) return false;
    final up = DateTime.tryParse('${d['updated_at'] ?? ''}');
    return up == null || n.toUtc().difference(up.toUtc()).inMinutes >= 3;
  }

  Future<void> _load() async {
    final r = await Future.wait([Api.daytrade(), Api.limitcatch(), Api.closingbet(), Api.closingbetTrack(),
      Api.statusKey('intraday_bars'), Api.statusKey('closingbet_bars')]);
    if (!mounted) return;
    _minuteBars = {
      for (final b in [r[5], r[4]]) // 당일매매 통합 것이 우선
        if (dtIsToday(b)) ...asMap(b['bars']).map((k, v) => MapEntry(k, v is List ? v : const [])),
    };
    dtMinuteBars = _minuteBars; // 후보 카드(진입 대기·관찰)도 같은 1분봉으로 차트
    _dt = r[0];
    _lc = r[1];
    _cb = r[2];
    _cbm = {'tracked': _mergeTracks(asList(r[2]['tracked']), asList(r[3]['tracked']))};
    _applyLive();
    // PC 꺼짐 대비: 진행 중인 고정 종목 지금가 (그 종목만 · 1분에 한 번)
    final open = <String>{
      for (final d in [_dt, _lc])
        if (_stale(d))
          for (final x in asList(d!['tracked']))
            if (x['done'] != true) '${x['code']}'
    };
    // 고정 종목 전부 시세 (오늘 등락률 배지 · PC 꺼짐 대비 지금가) — 종목 수만큼만, 1분에 한 번
    final all = <String>{
      ...open,
      for (final d in [_dt, _lc, _cbm])
        for (final x in asList(d?['tracked'])) '${x['code']}',
    };
    var q = <String, double>{};
    if (all.isNotEmpty) {
      try {
        final res = await Live.stocks(all.toList());
        q = {for (final e in res.quotes.entries) if (open.contains(e.key)) e.key: e.value.price};
      } catch (_) {}
    }
    if (!mounted) return;
    _announce([...asList(_dt!['tracked']), ...asList(_lc!['tracked']), ...asList(_cbm['tracked'])]);
    setState(() {
      _quotes = q;
      _at = DateTime.now();
    });
  }

  /// 새로 고정된 종목 → "매수발생"(여성) · 새 매도신호포착 → "매도발생"(남성)
  void _announce(List<Json> tracked) {
    final now = DateTime.now();
    final today = '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
    final buy = <String>{}, sell = <String>{};
    for (final t in tracked) {
      final key = '${t['kind']}:${t['code']}:${t['date']}';
      // 종가배팅은 고정이 아니라 매수 범위에 들어와 '매수' 됐을 때
      final bought = t['kind'] != 'closingbet' || asList(t['events']).any((e) => e['state'] == '매수');
      if (t['date'] == today && bought) buy.add(key);
      if (asList(t['events']).any((e) => e['state'] == '매도신호포착')) sell.add(key);
    }
    final first = _buySeen == null;
    final newBuy = first ? <String>{} : buy.difference(_buySeen!);
    final newSell = first ? <String>{} : sell.difference(_sellSeen!);
    _buySeen = {...?_buySeen, ...buy};
    _sellSeen = {...?_sellSeen, ...sell};
    () async {
      if (newBuy.isNotEmpty) await VoiceAlert.buy();
      if (newSell.isNotEmpty) await VoiceAlert.sell();
    }();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const LogoTitle('당일매매'), actions: topActions(context, onRefresh: _load)),
      body: (_dt == null || _lc == null)
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 32),
                children: [
                  _Section(kind: 'daytrade', d: _dt!, at: _at, onDone: _load, stale: _stale(_dt), quotes: _quotes, rtAt: _rtAt),
                  const SizedBox(height: 12),
                  _Section(kind: 'limitcatch', d: _lc!, at: _at, onDone: _load, stale: _stale(_lc), quotes: _quotes, rtAt: _rtAt),
                  const SizedBox(height: 12),
                  _ClosingSection(d: _cb ?? const <String, dynamic>{}, tracked: asList(_cbm['tracked']), at: _at, onDone: _load),
                  const SizedBox(height: 12),
                  Text('진입조건충족 종목은 처음 충족된 시각의 진입가·손절·목표로 고정하고, 그 시각에 산 것으로 보고 결과를 매겨요 (모의 · 주문 없음). '
                      '결과가 나오면 매매일지(구분: 당일매매 자동)에 기록돼요. 진입대기·관찰은 조건에 따라 바뀌고 기록하지 않아요.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey)),
                ],
              ),
            ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(
      {required this.kind,
      required this.d,
      required this.at,
      required this.onDone,
      this.stale = false,
      this.quotes = const {},
      this.rtAt});
  final String kind;
  final Json d;
  final DateTime? at;
  final VoidCallback onDone;
  final bool stale; // PC 실시간이 멈춤 → 지금가만 표시
  final Map<String, double> quotes;
  final DateTime? rtAt;

  bool get _lc => kind == 'limitcatch';

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final today = dtIsToday(d);
    // 고정 종목: 오늘 것 + 오늘 끝난 것 + (상한가포착만) 전날부터 아직 추적 중인 것 (오늘 09:30 까지). 당일단타는 어제 것이 마감 처리 못 된 채 남아도 안 보임 (2026-10-28)
    final todayStr = '${DateTime.now().year}-${DateTime.now().month.toString().padLeft(2, '0')}-${DateTime.now().day.toString().padLeft(2, '0')}';
    final tracked = asList(d['tracked'])
        .where((x) => dtIsToday({'date': x['date']}) || (_lc && x['done'] != true) || '${x['exit_time'] ?? ''}'.startsWith(todayStr))
        .toList();
    final fixed = {for (final x in tracked) '${x['code']}'};
    // 당일단타 후보 10개 (2026-10-30): 전광판처럼 카드로 — 조건이 맞으면 고정되어 아래 '진입조건충족' 으로 내려감
    final cands = today && !_lc ? asList(d['cands']).where((r) => !fixed.contains('${r['code']}')).toList() : <Json>[];
    final candCodes = {for (final r in cands) '${r['code']}'};
    final candRankOf = <String, int>{
      for (final x in asList(asMap(d['shortlist'])['list'])) '${x['code']}': (x['rank'] as num?)?.toInt() ?? 0
    }..removeWhere((k, v) => v <= 0);
    final items = today ? asList(d['items']).where((r) => !fixed.contains('${r['code']}') && !candCodes.contains('${r['code']}')).toList() : <Json>[];
    final waitKey = _lc ? '강세 후보' : '진입 대기';
    final wait = items.where((r) => r['status'] == waitKey).toList();
    final watch = items.where((r) => r['status'] == '관찰').toList();
    // 기준 미달 (당일단타 대상 아님·진입 금지 / 상한가포착 조건 무효·제외) — [종목찾기] 'N개' 에 들어가지만 위 구분엔 안 맞는 것
    final rest = items.where((r) => !{waitKey, '관찰', '진입 조건 충족', '매수 검토'}.contains(r['status'])).toList();
    Widget sub(String title, int n, String note) => Padding(
          padding: const EdgeInsets.fromLTRB(4, 8, 4, 2),
          child: Text.rich(TextSpan(children: [
            TextSpan(text: '$title $n', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            TextSpan(text: '  $note', style: t.bodySmall?.copyWith(color: Colors.grey)),
          ])),
        );
    Widget tile(Json r, int i, {bool compact = false}) => _lc
        ? LimitcatchTile(r: r, rank: i + 1)
        : DaytradeTile(r: r, rank: i + 1, compact: compact);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Text(_lc ? '상한가포착' : '당일단타', style: t.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
        const SizedBox(width: 8),
        Expanded(
            child: Text(today ? lookupLabel(d, at) : '오늘 결과 없음',
                overflow: TextOverflow.ellipsis, style: t.bodySmall?.copyWith(color: Colors.grey))),
        DaytradeFindButton(kind: kind, onDone: onDone),
      ]),
      if (d['scan_closed'] == true)
        Text('새 종목 찾기는 끝났고 고정 종목만 추적 중이에요', style: t.bodySmall?.copyWith(color: Colors.teal)),
      if (stale)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('⚠ PC 실시간이 멈춰 있어요 (PC 꺼짐·창 닫힘). 고정 종목의 지금가만 1분마다 보여 주고, 목표·손절 결과는 저녁 배치가 1분봉으로 확정해요.',
              style: t.bodySmall?.copyWith(color: Colors.orange)),
        )
      else if (rtAt != null && DateTime.now().difference(rtAt!).inMinutes < 3 && tracked.any((x) => x['done'] != true))
        Text('● 실시간 (체결 때마다 목표·손절 판단)', style: t.bodySmall?.copyWith(color: Colors.green)),
      // 상한가 예비 (2026-10-16): +10~20% 급등 초입 — 상한가 갈 만한 종목을 미리 (표시+기록만)
      if (_lc) _PreSection(items: today ? asList(d['pre']) : const []),
      if (!_lc) _Shortlist(sl: today ? asMap(d['shortlist']) : const {}, chips: cands.isEmpty),
      _grid([for (final (i, r) in cands.indexed) tile(r, ((r['cand_rank'] as num?)?.toInt() ?? 0) > 0 ? (r['cand_rank'] as num).toInt() - 1 : i, compact: true)]),
      sub('진입조건충족', tracked.length, '충족된 시간 순 · 고정'),
      if (tracked.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text('아직 없어요', style: t.bodySmall)),
      _grid([
        for (final x in tracked)
          _TrackCard(
              t: x,
              kind: kind,
              quote: stale && x['done'] != true ? quotes['${x['code']}'] : null,
              candRank: _lc ? null : candRankOf['${x['code']}']),
      ], width: _trackW),
      sub('진입대기', wait.length, _lc ? '+20%↑ · 100억↑ · 75점↑ (바뀔 수 있음)' : '80점↑ · 진입 신호 전 (바뀔 수 있음)'),
      _grid([for (final (i, r) in wait.indexed) tile(r, i)]),
      if (watch.isNotEmpty)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            dense: true,
            tilePadding: const EdgeInsets.symmetric(horizontal: 4),
            title: Text.rich(TextSpan(children: [
              TextSpan(text: '관찰 ${watch.length}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              TextSpan(text: '  바뀔 수 있음 (눌러서 펼치기)', style: t.bodySmall?.copyWith(color: Colors.grey)),
            ])),
            children: [_grid([for (final (i, r) in watch.take(10).indexed) tile(r, i)])],
          ),
        ),
      if (rest.isNotEmpty)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: const EdgeInsets.symmetric(horizontal: 4),
            title: Text.rich(TextSpan(children: [
              TextSpan(text: '기준 미달 ${rest.length}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              TextSpan(
                  text: _lc ? '  조건 무효·제외 (참고)' : '  70점 미만·진입 금지 (참고)',
                  style: t.bodySmall?.copyWith(color: Colors.grey)),
            ])),
            children: [_grid([for (final (i, r) in rest.take(10).indexed) tile(r, i)])],
          ),
        ),
    ]);
  }
}

/// 당일단타 '오늘의 후보' (2026-10-29) — 09:10 에 점수 상위 10개 고정, 진입은 후보 안의 눌림목형만. 상위 5개가 우선
/// 되돌려 보기(20거래일): 상위 5개 평균 +0.78% · 10개 +0.27% · 전체 −0.32% (수급 없이, 한 달 한 장세 — 참고용)
class _Shortlist extends StatelessWidget {
  const _Shortlist({required this.sl, this.chips = true});
  final Json sl;
  final bool chips; // 후보 카드(전광판)가 없을 때만 이름표로

  @override
  Widget build(BuildContext context) {
    if (sl.isEmpty) return const SizedBox.shrink();
    final t = Theme.of(context).textTheme;
    final list = asList(sl['list']);
    final top = (sl['top'] as num?)?.toInt() ?? 5;
    final done = '${sl['state']}' == '확정';
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 8, 4, 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text.rich(TextSpan(children: [
          TextSpan(text: '당일단타 후보 ${done ? list.length : 0}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          TextSpan(
              text: done
                  ? '  ${sl['at']} 확정 · 진입은 이 안에서만 (앞 $top개 우선)'
                  : '  ${sl['freeze_at'] ?? '09:10'} 에 점수 상위 ${sl['n'] ?? 10}개를 골라요 · 그 전엔 진입 대기',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
        ])),
        if (done && chips)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Wrap(spacing: 6, runSpacing: 2, children: [
              for (final x in list)
                ActionChip(
                  visualDensity: VisualDensity.compact,
                  backgroundColor: ((x['rank'] as num?) ?? 99) <= top ? Colors.teal.withValues(alpha: 0.15) : null,
                  label: Text('${x['rank']} ${x['name']} ${(x['score'] as num?)?.toStringAsFixed(0) ?? ''}',
                      style: t.bodySmall?.copyWith(fontWeight: ((x['rank'] as num?) ?? 99) <= top ? FontWeight.bold : FontWeight.normal)),
                  onPressed: () => Navigator.push(context,
                      MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${x['code']}', name: '${x['name']}'))),
                ),
            ]),
          ),
      ]),
    );
  }
}

/// 종가배팅 (14:50~15:20 · PC 16_closingbet.bat) — 매수 후보 · 우선 관찰 · 관찰. 고정·추적 없이 1분마다 바뀜
/// 결과(종가 매수 → 다음 날 10:30 매도)는 다음 날 저녁 배치가 검증 탭에 올림
class _ClosingSection extends StatelessWidget {
  const _ClosingSection({required this.d, required this.tracked, required this.at, required this.onDone});
  final Json d;
  final List<Json> tracked; // 고정·매수 내역 (전날 · 오늘)
  final DateTime? at;
  final VoidCallback onDone;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final today = dtIsToday(d);
    final fixed = {for (final x in tracked) if (dtIsToday({'date': x['date']})) '${x['code']}'};
    final items = today ? asList(d['items']).where((r) => !fixed.contains('${r['code']}')).toList() : <Json>[];
    final c = asMap(d['counts']);
    final todayT = tracked.where((x) => dtIsToday({'date': x['date']})).toList();
    // 전날 내역: 오늘보다 앞선 날짜 중 가장 최근 하루 (다음 날 10:30 까지 매도 추적)
    // 전일 종가배팅: 아직 추적 중인 것만 (이익실현·매수가매도·손절·미체결 등 결과가 확정된 것은 안 보임 — 2026-10-16)
    final prevT = tracked.where((x) => !dtIsToday({'date': x['date']}) && x['done'] != true).toList();
    final prevDates = prevT.map((x) => '${x['date']}').toSet().toList()..sort();
    // 당일단타·상한가포착과 같은 구분: 진입대기 = 우선 관찰 · 관찰 · 기준 미달(대상 아님·진입 금지)
    final wait = items.where((r) => r['status'] == '우선 관찰').toList();
    final watch = items.where((r) => r['status'] == '관찰').toList();
    final rest = items.where((r) => !{'우선 관찰', '관찰', '매수 후보'}.contains(r['status'])).toList();
    Widget sub(String title, int n, String note) => Padding(
          padding: const EdgeInsets.fromLTRB(4, 8, 4, 2),
          child: Text.rich(TextSpan(children: [
            TextSpan(text: '$title $n', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            TextSpan(text: '  $note', style: t.bodySmall?.copyWith(color: Colors.grey)),
          ])),
        );
    Widget fold(String title, String note, List<Widget> children) => Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            dense: true,
            tilePadding: const EdgeInsets.symmetric(horizontal: 4),
            title: Text.rich(TextSpan(children: [
              TextSpan(text: title, style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              TextSpan(text: '  $note', style: t.bodySmall?.copyWith(color: Colors.grey)),
            ])),
            children: [_grid(children)],
          ),
        );
    Widget tile(Json r, int i) => ClosingbetTile(r: r, rank: i + 1, showRules: true);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Text('종가배팅', style: t.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
        const SizedBox(width: 8),
        Expanded(
            child: Text(today ? lookupLabel(d, at) : '오늘 결과 없음',
                overflow: TextOverflow.ellipsis, style: t.bodySmall?.copyWith(color: Colors.grey))),
        DaytradeFindButton(closing: true, onDone: onDone),
      ]),
      if (today && d['final'] == true)
        Text('새 종목 찾기는 끝났고 고정 종목만 추적 중이에요 (다음 날 10:30 까지)', style: t.bodySmall?.copyWith(color: Colors.teal))
      else
        Text(
            today
                ? '14:50~15:20 1분마다 · 후보 ${d['scanned'] ?? 0} · 매수 후보 ${c['매수 후보'] ?? 0} · 우선 관찰 ${c['우선 관찰'] ?? 0} · 관찰 ${c['관찰'] ?? 0}'
                : '평일 14:50~15:20 PC 16_closingbet.bat(작업 스케줄러 14:45) 또는 [종목찾기]로 올라와요',
            style: t.bodySmall?.copyWith(color: Colors.grey)),
      sub('진입조건충족', todayT.length, '매수 후보 처음 뜬 시각 순 · 고정 · 14:50~15:20 매수 범위에 들어오면 매수'),
      if (todayT.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text('아직 없어요', style: t.bodySmall)),
      _grid([for (final x in todayT) _TrackCard(t: x, kind: 'closingbet')], width: _trackW),
      if (prevT.isNotEmpty) ...[
        sub('전일 진입조건충족', prevT.length,
            '${prevDates.last.length >= 10 ? prevDates.last.substring(5) : prevDates.last} 고정 · 다음 날 10:30 까지 매도'),
        _grid([for (final x in prevT) _TrackCard(t: x, kind: 'closingbet')], width: _trackW),
      ],
      sub('진입대기', wait.length, '우선 관찰 · 80점↑ 이지만 갭 위험 높음 (바뀔 수 있음)'),
      _grid([for (final (i, r) in wait.indexed) tile(r, i)]),
      if (watch.isNotEmpty)
        fold('관찰 ${watch.length}', '70점↑ · 바뀔 수 있음 (눌러서 펼치기)', [for (final (i, r) in watch.take(10).indexed) tile(r, i)]),
      if (rest.isNotEmpty)
        fold('기준 미달 ${rest.length}', '70점 미만·진입 금지 (참고)', [for (final (i, r) in rest.take(10).indexed) tile(r, i)]),
    ]);
  }
}


const _states = ['매수구간', '신규진입보류', '1차목표달성', '2차목표달성', '3차목표달성', '매도신호포착', '손절'];
const _cbStates = ['매수대기', '매수', '1차목표달성', '2차목표달성', '손절']; // 종가배팅

/// 예전 기록의 '본전 매도' → '매수가매도' (2026-10-14 이름 바꿈)
String _st(String s) => s == '본전 매도' ? '매수가매도' : s;

Color _resultColor(String? r) => switch (r) {
      '이익실현' => upColor,
      '매수가매도' => Colors.orange,
      '손절' => downColor,
      _ => Colors.grey,
    };

/// 매수·1·2·3차·매수가매도·손절 순간의 종합지수(코스피/코스닥)·업종지수 (PC 22 가 기록: t['ix'][키] = [종합%, 업종%, 시각, 시장])
///   매수: 전일 대비 등락 · 그 뒤: 매수 때보다 얼마나 움직였나
Widget? _ixLine(BuildContext context, Json t) {
  final ix = asMap(t['ix']);
  if (ix.isEmpty) return null;
  num? at(String k, int i) {
    final l = ix[k];
    return l is List && l.length > i && l[i] is num ? l[i] as num : null;
  }

  String sg(num? v) => v == null ? '-' : '${v > 0 ? '+' : (v < 0 ? '−' : '')}${v.abs().toStringAsFixed(2)}%';
  num? since(num? b, num? e) => b == null || e == null ? null : ((1 + e / 100) / (1 + b / 100) - 1) * 100;
  Color? col(num? v) => v == null ? null : (v > 0 ? upColor : (v < 0 ? downColor : null));
  final anyKey = ix.values.firstWhere((v) => v is List && v.length > 3, orElse: () => const []) as List;
  final mk = anyKey.length > 3 && '${anyKey[3]}' == 'KOSDAQ' ? '코스닥' : '코스피';
  final st = Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 11.5);
  final spans = <InlineSpan>[];
  for (final (k, label) in const [
    ('buy', '매수'), ('t1', '1차'), ('t2', '2차'), ('t3', '3차'), ('even', '매수가매도'), ('stop', '손절'), ('close', '마감'),
  ]) {
    if (ix[k] is! List) continue;
    final hm = (ix[k] as List).length > 2 ? '${(ix[k] as List)[2]}' : '';
    final m = k == 'buy' ? at(k, 0) : since(at('buy', 0), at(k, 0));
    final sc = k == 'buy' ? at(k, 1) : since(at('buy', 1), at(k, 1));
    if (spans.isNotEmpty) spans.add(TextSpan(text: '   ·   ', style: st?.copyWith(color: Colors.grey)));
    spans.addAll([
      TextSpan(text: '$label $hm ', style: st?.copyWith(fontWeight: FontWeight.bold)),
      TextSpan(text: '$mk ', style: st?.copyWith(color: Colors.grey)),
      TextSpan(text: sg(m), style: st?.copyWith(color: col(m))),
      TextSpan(text: ' 업종 ', style: st?.copyWith(color: Colors.grey)),
      TextSpan(text: sg(sc), style: st?.copyWith(color: col(sc))),
    ]);
  }
  if (spans.isEmpty) return null;
  return Padding(
    padding: const EdgeInsets.only(top: 4),
    child: Text.rich(TextSpan(children: [
      TextSpan(text: '지수  ', style: st?.copyWith(color: Colors.grey)),
      ...spans,
    ])),
  );
}

/// 진입조건충족 한 종목: 종목명·점수·현재가 / 기존 상태설명(고정 카드) / 상태별 시각 / 매매 결과
class _TrackCard extends StatelessWidget {
  const _TrackCard({required this.t, required this.kind, this.quote, this.candRank});
  final Json t;
  final String kind; // daytrade · limitcatch · closingbet
  bool get lc => kind == 'limitcatch';
  bool get cb => kind == 'closingbet';
  final int? candRank; // 당일단타 후보 순위 (09:10 확정 · 종목명 앞에 표시)
  final double? quote; // PC 꺼짐 대비 지금가 (있으면 이걸로 표시 · 결과는 저녁 확정)

  /// 지금가가 목표·손절의 어디쯤인지 (확정 아님)
  String? _where(double p) {
    double? n(String k) => (t[k] as num?)?.toDouble();
    final stop = t['be'] == true ? n('entry') : n('stop');
    if (stop != null && p <= stop) return t['be'] == true ? '매수가 아래' : '손절가 아래';
    for (final k in ['t3', 't2', 't1']) {
      final v = n(k);
      if (v != null && p >= v) return '${k.substring(1)}차 목표 위';
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final tx = Theme.of(context).textTheme;
    final entry = (t['entry'] as num?)?.toDouble() ?? 0;
    final last = quote ?? (t['last'] as num?)?.toDouble();
    final done = t['done'] == true;
    final bought = t['bought'] != false; // 종가배팅은 매수 범위에 들어와야 매수
    final where = quote == null ? null : _where(quote!);
    final pnl = done
        ? (t['pnl'] as num?)?.toDouble()
        : (bought && last != null && entry > 0 ? (last / entry - 1) * 100 : null);
    final events = asList(t['events']);
    final card = {...asMap(t['card']), 'code': t['code'], 'name': t['name']};
    // '매수구간' 은 들어온 시각 기록일 뿐 → 지금가가 구간 밖이면 '매수구간 이탈'로 보여 주고 깜빡이지 않음
    final lo = (t['buy_lo'] as num?)?.toDouble(), hi = (t['buy_hi'] as num?)?.toDouble();
    final inZone = last != null && lo != null && hi != null && last >= lo && last <= hi;
    final rawCur = _st('${t['state'] ?? ''}');
    final cur = (rawCur == '매수구간' && !done && !inZone) ? '매수구간 이탈' : rawCur;
    final prevDay = !dtIsToday({'date': t['date']});
    // 매수구간·매도신호포착 상태면 깜빡임 (끝난 종목은 끝난 뒤 10분까지만)
    final ended = DateTime.tryParse('${t['exit_time'] ?? ''}'.replaceFirst(' ', 'T'));
    final blink = (cur == '매수구간' || cur == '매도신호포착' || cur == '매수대기') &&
        (!done || (ended != null && DateTime.now().difference(ended).inMinutes < 10));
    // 1분봉 차트 (최근 2시간) · 마지막 봉은 실시간 현재가로 덧그림
    final raw = _minuteBars['${t['code']}'] ?? const [];
    final mb = <Json>[
      for (final r in raw)
        if (r is List && r.length >= 6)
          {
            'date': '${r[0]}',
            'open': (r[1] as num).toDouble(),
            'high': (r[2] as num).toDouble(),
            'low': (r[3] as num).toDouble(),
            'close': (r[4] as num).toDouble(),
            'volume': (r[5] as num).toDouble(),
          },
    ];
    if (mb.isNotEmpty && !done && last != null && last > 0) {
      final b = mb.last;
      b['close'] = last;
      if (last > (b['high'] as double)) b['high'] = last;
      if (last < (b['low'] as double)) b['low'] = last;
    }
    double? n(String k) => (t[k] as num?)?.toDouble();
    // 공통 규칙: 1차 목표 뒤엔 손절가 대신 매수가(본전) — 닿으면 남은 몫 전량 매도 ('손절'로 표시하지 않음)
    // 단, 3차(종가배팅은 2차)까지 가서 전량 매도로 끝난 종목은 본전 매도가 없음 → 보유 중이거나 실제로 본전 매도로 끝난 것만
    final be = t['be'] == true && (!done || events.any((e) => _st('${e['state']}') == '매수가매도'));
    final lastSt = be ? '매수가매도' : '손절';
    final chart = mb.length < 3
        ? null
        : Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
            SizedBox(
              height: 190,
              child: PriceChart(bars: mb, showMa: false, levels: [
                if (bought && n('entry') != null) PriceLevel(be ? '매수가매도' : '매수', n('entry')!, be ? Colors.orange : Colors.grey),
                if (!be && n('stop') != null) PriceLevel('손절', n('stop')!, downColor),
                if (n('t1') != null) PriceLevel('1차', n('t1')!, upColor),
              ]),
            ),
            // 언제 차트인지: 첫 봉 ~ 마지막 봉 시각 (마지막 봉은 실시간 현재가로 덧그림)
            Text('1분봉 ${mb.first['date']} ~ ${mb.last['date']}${!done && last != null ? ' · 현재가 실시간' : ''}',
                textAlign: TextAlign.right,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
          ]);
    final narrow = MediaQuery.sizeOf(context).width < 640;
    // 오늘 등락률: 받아 둔 시세 → 없으면 포착 때 가격·등락률로 전일 종가를 거꾸로 구해 지금가와 비교 (같은 날만)
    final cardPx = (asMap(t['card'])['price'] as num?)?.toDouble(), cardChg = (asMap(t['card'])['chg_pct'] as num?)?.toDouble();
    final num? todayChg = Live.last['${t['code']}']?.ratio ??
        (!prevDay && last != null && cardPx != null && cardChg != null && cardChg > -100
            ? (last / (cardPx / (1 + cardChg / 100)) - 1) * 100
            : null);
    String? timeOf(String s) {                       // 그 상태가 처음 생긴 시각
      for (final e in events) {
        final st = '${e['state']}';
        if (_st(st) == s) return '${e['time']}';
      }
      return null;
    }
    String? whyOf(String s) {                        // 상태가 생긴 이유 (신규진입보류: 점수·구간 이탈·급락·VWAP·거래량)
      for (final e in events) {
        if (_st('${e['state']}') == s && e['why'] != null) return '${e['why']}';
      }
      return null;
    }
    final closeT = timeOf('마감 청산');
    final noFillT = timeOf('미체결');
    // 웹(넓은 화면)에서 당일단타 카드: 높이 통일(460, 넘치면 카드 안에서 스크롤) · 시장·업종 칩을 종목명 옆으로 (2026-10-30)
    final wide = MediaQuery.sizeOf(context).width >= 900;
    final fixedH = wide && kind == 'daytrade';
    Widget fix(Widget w) => fixedH ? SizedBox(height: 460, child: SingleChildScrollView(child: w)) : w;
    final code = '${t['code']}';
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      shape: RoundedRectangleBorder(
          side: BorderSide(color: done ? _resultColor(t['result'] as String?) : Colors.blueGrey, width: 1.2),
          borderRadius: BorderRadius.circular(12)),
      child: fix(Padding(
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          InkWell(
            onTap: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => StockDetailScreen(
                    code: '${t['code']}', name: '${t['name']}', news: asList(asMap(t['card'])['news'])))),
            child: Row(crossAxisAlignment: wide ? CrossAxisAlignment.start : CrossAxisAlignment.center, children: [
              if (candRank != null) ...[
                CircleAvatar(
                    radius: 11,
                    backgroundColor: Colors.teal.withValues(alpha: 0.18),
                    child: Text('$candRank', style: const TextStyle(color: Colors.tealAccent, fontSize: 12, fontWeight: FontWeight.bold))),
                const SizedBox(width: 8),
              ],
              Expanded(
                  child: wide
                      ? Wrap(spacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                          Row(mainAxisSize: MainAxisSize.min, children: [
                            Flexible(child: Text('${t['name']}', overflow: TextOverflow.ellipsis, style: tx.titleMedium)),
                            const SizedBox(width: 6),
                            ScoreBadge(t['score'] as num?, digits: 1),
                          ]),
                          StockInfoLine(code, showRest: false), // [코스닥][업종 · 테마] 종목명 옆
                        ])
                      : StockName('${t['name']}', score: t['score'] as num?, scoreDigits: 1, style: tx.titleMedium)),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Row(mainAxisSize: MainAxisSize.min, children: [
                  Text(won(last), style: tx.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                  ChgBadge(todayChg), // 오늘 등락률
                ]),
                Text(bought ? '매수가 대비 ${pnl == null ? '-' : pct(pnl)}' : (done ? '미체결' : '매수 전'),
                    style: tx.bodySmall?.copyWith(color: (pnl ?? 0) >= 0 ? upColor : downColor)),
              ]),
            ]),
          ),
          StockInfoLine(code, sectorIdx: true, showHead: !wide), // [시장][업종 · 테마][시총] — 웹은 시장·업종이 종목명 옆
          const SizedBox(height: 4),
          infoBoxes([
            InfoBox('${prevDay ? '${'${t['date']}'.substring(5)} ' : ''}${t['time']} 포착', bold: true, fill: true),
            if (cb && t['buy_time'] != null) InfoBox('${t['buy_time']} 매수', color: upColor, bold: true),
            InfoBox('${cb && !bought ? '매수범위' : '매수 ${num0(t['entry'] as num?)}'} (${num0(lo)}~${num0(hi)})'),
            be
                ? InfoBox('1차 뒤 매수가매도 ${num0(t['entry'] as num?)} (전량)', color: Colors.orange, bold: true)
                : InfoBox('손절 ${num0(t['stop'] as num?)}', color: downColor),
            InfoBox('1차 ${num0(t['t1'] as num?)}', color: upColor),
            InfoBox('2차 ${num0(t['t2'] as num?)}', color: upColor),
            if (t['t3'] != null) InfoBox('3차 ${num0(t['t3'] as num?)}', color: upColor),
            if (rrBox(t['entry'] as num?, t['stop'] as num?, t['t1'] as num?, t['t2'] as num?) case final rr?) rr,
          ]),
          if (_ixLine(context, t) case final ix?) ix, // 매수·매도 순간 종합지수·업종지수
          // 왼쪽: 기존 상태설명 · 현재 상태 | 매매 결과   /   오른쪽: 1분봉 차트 (최근 2시간 · 현재가 실시간)
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              flex: 3,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                // 기존 상태설명: 충족 순간의 카드 그대로
                Theme(
                  data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                  child: ExpansionTile(
                    dense: true,
                    tilePadding: EdgeInsets.zero,
                    childrenPadding: EdgeInsets.zero,
                    title: Text('기존 상태설명 (${t['time']} 충족 때)', style: tx.bodyMedium),
                    children: [
                      cb
                          ? ClosingbetTile(r: card, rank: 1, showRules: true)
                          : lc
                              ? LimitcatchTile(r: card, rank: 1)
                              : DaytradeTile(r: card, rank: 1, chart: false)
                    ],
                  ),
                ),
                // 현재 상태 (상태마다 처음 생긴 시각) | 매매 결과
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    flex: 6,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('현재 상태', style: tx.labelMedium?.copyWith(color: Colors.grey)),
                      for (final s in [...(cb ? _cbStates : _states).map((x) => x == '손절' ? lastSt : x), if (closeT != null) '마감 청산', if (noFillT != null) '미체결'])
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 1.5),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Row(children: [
                              Expanded(
                                  child: Blink(
                                      on: cur == s && blink,
                                      child: Text(s,
                                          style: tx.bodySmall?.copyWith(
                                              fontWeight: cur == s ? FontWeight.bold : null,
                                              color: cur == s && blink
                                                  ? (s == '매도신호포착' ? downColor : upColor)
                                                  : (timeOf(s) == null ? Colors.grey : null))))),
                              SizedBox(width: 46, child: Text(timeOf(s) ?? '-', textAlign: TextAlign.right, style: tx.bodySmall)),
                            ]),
                            if (s == '신규진입보류' && whyOf(s) != null)
                              Text(whyOf(s)!, style: tx.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
                          ]),
                        ),
                    ]),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    flex: 4,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('매매 결과', style: tx.labelMedium?.copyWith(color: Colors.grey)),
                      const SizedBox(height: 4),
                      if (done) ...[
                        Text('${t['result']}',
                            style: tx.titleMedium?.copyWith(fontWeight: FontWeight.bold, color: _resultColor(t['result'] as String?))),
                        if (pnl != null) Text(pct(pnl), style: tx.titleSmall?.copyWith(color: pnl >= 0 ? upColor : downColor)),
                        if (t['exit_price'] != null) Text('평균 매도 ${num0(t['exit_price'] as num?)}', style: tx.bodySmall),
                        Text('${'${t['exit_time'] ?? ''}'.length >= 16 ? '${t['exit_time']}'.substring(11, 16) : ''} 끝',
                            style: tx.bodySmall?.copyWith(color: Colors.grey)),
                      ] else ...[
                        Text('진행중', style: tx.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                        Blink(on: blink, child: Text(cur, style: tx.bodySmall?.copyWith(fontWeight: FontWeight.bold))),
                        if (cur == '매수구간 이탈' && last != null)
                          Text('지금가가 구간 ${last > (hi ?? 0) ? '위' : '아래'}', style: tx.bodySmall?.copyWith(color: Colors.grey)),
                        Text(cb ? (bought ? '다음 날 10:30 까지' : '오늘 15:20 까지 매수 범위 대기') : lc ? '다음 날 09:30 까지' : '15:20 까지',
                            style: tx.bodySmall?.copyWith(color: Colors.grey)),
                        if (quote != null)
                          Text('지금가 기준${where == null ? '' : ' $where'} · 저녁 확정', style: tx.bodySmall?.copyWith(color: Colors.orange)),
                      ],
                    ]),
                  ),
                ]),
              ]),
            ),
            if (chart != null && !narrow)
              ...[const SizedBox(width: 8), Expanded(flex: 2, child: Padding(padding: const EdgeInsets.only(top: 8), child: chart))],
          ]),
          if (chart != null && narrow) Padding(padding: const EdgeInsets.only(top: 6), child: chart), // 폰: 차트는 아래 전체 폭
        ]),
      )),
    );
  }
}

/// 카드 배치: 종목 카드 폭을 정해(약 460) 옆으로 붙이고, 화면이 좁아지면 아래로 내림
///   한 줄에 들어가는 개수만큼 남는 폭을 고르게 나눔 (휴대폰처럼 좁으면 한 줄에 하나 · 전체 폭)
const _cardW = 460.0;   // 후보 카드
const _trackW = 600.0;  // 고정 종목 카드 (오른쪽 1분봉 차트 포함)
Widget _grid(List<Widget> children, {double width = _cardW}) => LayoutBuilder(builder: (context, c) {
      if (children.isEmpty) return const SizedBox.shrink();
      final n = ((c.maxWidth + 8) / (width + 8)).floor().clamp(1, 6);
      if (n == 1) return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
      final w = (c.maxWidth - 8 * (n - 1)) / n;
      // 화면 폭 전체를 차지하고 왼쪽부터 채움 (1건만 있어도 가운데로 가지 않게)
      return SizedBox(
        width: c.maxWidth,
        child: Wrap(spacing: 8, alignment: WrapAlignment.start, crossAxisAlignment: WrapCrossAlignment.start, children: [
          for (final x in children) SizedBox(width: w, child: x),
        ]),
      );
    });

/// 상한가포착 위: '상한가 예비' 목록 + 지난 기록(상한가 도달·종가 잠김 비율)
class _PreSection extends StatefulWidget {
  const _PreSection({required this.items});
  final List<Json> items;
  @override
  State<_PreSection> createState() => _PreSectionState();
}

class _PreSectionState extends State<_PreSection> {
  static Future<Json>? _stats; // 하루 한 번 바뀜 → 앱 켜 있는 동안 한 번만 받음
  @override
  void initState() {
    super.initState();
    _stats ??= Api.statusKey('limit_pre_stats').catchError((_) => <String, dynamic>{});
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final pre = widget.items.where((r) => r['status'] == '상한가 예비').toList();
    final watch = widget.items.where((r) => r['status'] == '관찰').toList();
    Widget chip(String s, Color c) => Container(
          margin: const EdgeInsets.only(right: 4, top: 3),
          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
          decoration: BoxDecoration(border: Border.all(color: c.withValues(alpha: 0.5)), borderRadius: BorderRadius.circular(4)),
          child: Text(s, style: t.bodySmall?.copyWith(fontSize: 11, color: c)),
        );
    Widget tile(Json r) => Card(
          margin: const EdgeInsets.symmetric(vertical: 3),
          child: InkWell(
            onTap: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${r['code']}', name: '${r['name']}', news: asList(r['news'])))),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: StockName('${r['name']}', score: r['score'] as num?, scoreDigits: 1, style: t.titleSmall)),
                  Text(won((r['price'] as num?)?.toDouble()), style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                  ChgBadge(r['chg_pct'] as num?),
                ]),
                StockInfoLine('${r['code']}'),
                Wrap(children: [
                  if (r['first_time'] != null) chip('${r['first_time']} 처음 포착', Colors.teal),
                  if (r['limit'] is num && r['price'] is num)
                    chip('상한가 ${num0(r['limit'] as num)} (+${(((r['limit'] as num) / (r['price'] as num) - 1) * 100).toStringAsFixed(1)}% 남음)',
                        Colors.grey),
                  for (final s in (r['reasons'] as List? ?? const []).map((e) => '$e')) chip(s, upColor),   // 글자 목록 — asList(맵 변환) 쓰면 오류 → 회색 박스
                  for (final s in (r['warn'] as List? ?? const []).map((e) => '$e')) chip(s, Colors.orange),
                ]),
              ]),
            ),
          ),
        );
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(4, 8, 4, 2),
        child: Text.rich(TextSpan(children: [
          TextSpan(text: '상한가 예비 ${pre.length}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          TextSpan(text: '  +10~20% 급등 초입 · 09:05~14:30 · 60점↑ (가설 · 검증 중)', style: t.bodySmall?.copyWith(color: Colors.grey)),
        ])),
      ),
      FutureBuilder<Json>(
        future: _stats,
        builder: (context, snap) {
          final a = asMap(asMap(snap.data?['stats'])['all']);
          if ((a['n'] as num? ?? 0) == 0) {
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Text('지난 기록 아직 없음 — 쌓이면 상한가 도달·종가 잠김 비율이 여기 나와요',
                  style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
            );
          }
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Text(
                '지난 기록 ${a['n']}건 · 그날 상한가 도달 ${a['reached']}% · 종가 잠김 ${a['closed']}%'
                '${a['close_ret'] is num ? ' · 신호 뒤 종가 ${(a['close_ret'] as num) >= 0 ? '+' : ''}${a['close_ret']}%' : ''}',
                style: t.bodySmall?.copyWith(color: Colors.teal, fontSize: 11)),
          );
        },
      ),
      if (pre.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text('지금은 없어요', style: t.bodySmall)),
      _grid([for (final r in pre) tile(r)]),
      if (watch.isNotEmpty)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            dense: true,
            tilePadding: const EdgeInsets.symmetric(horizontal: 4),
            title: Text.rich(TextSpan(children: [
              TextSpan(text: '예비 관찰 ${watch.length}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              TextSpan(text: '  기본 조건은 맞지만 60점 미만 (눌러서 펼치기)', style: t.bodySmall?.copyWith(color: Colors.grey)),
            ])),
            children: [_grid([for (final r in watch) tile(r)])],
          ),
        ),
      const Divider(height: 16),
    ]);
  }
}

/// 깜빡이는 표시 (on 이 false 면 그대로)
class Blink extends StatefulWidget {
  const Blink({super.key, required this.on, required this.child});
  final bool on;
  final Widget child;
  @override
  State<Blink> createState() => _BlinkState();
}

class _BlinkState extends State<Blink> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 600), lowerBound: 0.15, upperBound: 1.0);

  @override
  void initState() {
    super.initState();
    if (widget.on) _c.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(Blink old) {
    super.didUpdateWidget(old);
    if (widget.on && !_c.isAnimating) {
      _c.repeat(reverse: true);
    } else if (!widget.on && _c.isAnimating) {
      _c.stop();
      _c.value = 1.0;
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      widget.on ? FadeTransition(opacity: _c, child: widget.child) : widget.child;
}
