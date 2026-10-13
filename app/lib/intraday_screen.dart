import 'dart:async';

import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'api.dart';
import 'daytrade.dart' show DaytradeTile, DaytradeFindButton, dtIsToday, lookupLabel;
import 'format.dart';
import 'limitcatch.dart' show LimitcatchTile;
import 'live.dart';
import 'screens/stock_detail_screen.dart';
import 'voice.dart';
import 'widgets/common.dart';
import 'widgets/nav.dart';
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

bool _marketWindow() {
  final n = DateTime.now();
  if (n.weekday > 5) return false;
  final m = n.hour * 60 + n.minute;
  return m >= 9 * 60 && m <= 15 * 60 + 35;
}

class _IntradayScreenState extends State<IntradayScreen> {
  Json? _dt, _lc;
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
                _announce([...asList(_dt?['tracked']), ...asList(_lc?['tracked'])]);
                setState(() {});
              })
          .subscribe();
    } catch (_) {}
  }

  /// 실시간 상태를 1분 갱신본 위에 덮기 (상태가 같거나 더 나아간 것만 — 늦게 온 1분 갱신본이 되돌리지 않게)
  void _applyLive() {
    for (final (kind, d) in [('daytrade', _dt), ('limitcatch', _lc)]) {
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
    final r = await Future.wait([Api.daytrade(), Api.limitcatch()]);
    if (!mounted) return;
    _dt = r[0];
    _lc = r[1];
    _applyLive();
    // PC 꺼짐 대비: 진행 중인 고정 종목 지금가 (그 종목만 · 1분에 한 번)
    final open = <String>{
      for (final d in [_dt, _lc])
        if (_stale(d))
          for (final x in asList(d!['tracked']))
            if (x['done'] != true) '${x['code']}'
    };
    var q = <String, double>{};
    if (open.isNotEmpty) {
      try {
        final res = await Live.stocks(open.toList());
        q = {for (final e in res.quotes.entries) e.key: e.value.price};
      } catch (_) {}
    }
    if (!mounted) return;
    _announce([...asList(_dt!['tracked']), ...asList(_lc!['tracked'])]);
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
      if (t['date'] == today) buy.add(key);
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
                  const SizedBox(height: 18),
                  _Section(kind: 'limitcatch', d: _lc!, at: _at, onDone: _load, stale: _stale(_lc), quotes: _quotes, rtAt: _rtAt),
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
    final tracked = asList(d['tracked']);
    final fixed = {for (final x in tracked) '${x['code']}'};
    final items = today ? asList(d['items']).where((r) => !fixed.contains('${r['code']}')).toList() : <Json>[];
    final waitKey = _lc ? '강세 후보' : '진입 대기';
    final wait = items.where((r) => r['status'] == waitKey).toList();
    final watch = items.where((r) => r['status'] == '관찰').toList();
    // 기준 미달 (당일단타 대상 아님·진입 금지 / 상한가포착 조건 무효·제외) — [종목찾기] 'N개' 에 들어가지만 위 구분엔 안 맞는 것
    final rest = items.where((r) => !{waitKey, '관찰', '진입 조건 충족', '매수 검토'}.contains(r['status'])).toList();
    Widget sub(String title, int n, String note) => Padding(
          padding: const EdgeInsets.fromLTRB(4, 12, 4, 4),
          child: Text.rich(TextSpan(children: [
            TextSpan(text: '$title $n', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            TextSpan(text: '  $note', style: t.bodySmall?.copyWith(color: Colors.grey)),
          ])),
        );
    Widget tile(Json r, int i) => _lc
        ? LimitcatchTile(r: r, rank: i + 1)
        : DaytradeTile(r: r, rank: i + 1);
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
      sub('진입조건충족', tracked.length, '충족된 시간 순 · 고정'),
      if (tracked.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text('아직 없어요', style: t.bodySmall)),
      for (final x in tracked)
        _TrackCard(t: x, lc: _lc, quote: stale && x['done'] != true ? quotes['${x['code']}'] : null),
      sub('진입대기', wait.length, _lc ? '+20%↑ · 100억↑ · 75점↑ (바뀔 수 있음)' : '80점↑ · 진입 신호 전 (바뀔 수 있음)'),
      for (final (i, r) in wait.indexed) tile(r, i),
      sub('관찰', watch.length, '바뀔 수 있음'),
      for (final (i, r) in watch.take(10).indexed) tile(r, i),
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
            children: [for (final (i, r) in rest.take(10).indexed) tile(r, i)],
          ),
        ),
    ]);
  }
}

const _states = ['매수구간', '신규진입보류', '1차목표달성', '2차목표달성', '3차목표달성', '매도신호포착', '손절'];

Color _resultColor(String? r) => switch (r) {
      '이익실현' => upColor,
      '매수가매도' => Colors.orange,
      '손절' => downColor,
      _ => Colors.grey,
    };

/// 진입조건충족 한 종목: 종목명·점수·현재가 / 기존 상태설명(고정 카드) / 상태별 시각 / 매매 결과
class _TrackCard extends StatelessWidget {
  const _TrackCard({required this.t, required this.lc, this.quote});
  final Json t;
  final bool lc;
  final double? quote; // PC 꺼짐 대비 지금가 (있으면 이걸로 표시 · 결과는 저녁 확정)

  /// 지금가가 목표·손절의 어디쯤인지 (확정 아님)
  String? _where(double p) {
    double? n(String k) => (t[k] as num?)?.toDouble();
    final stop = t['be'] == true ? n('entry') : n('stop');
    if (stop != null && p <= stop) return t['be'] == true ? '본전 아래' : '손절가 아래';
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
    final where = quote == null ? null : _where(quote!);
    final pnl = done ? (t['pnl'] as num?)?.toDouble() : (last != null && entry > 0 ? (last / entry - 1) * 100 : null);
    final events = asList(t['events']);
    String? timeOf(String s) {
      for (final e in events) {
        final st = '${e['state']}';
        if (st == s || (s == '손절' && st == '본전 매도')) return '${e['time']}';
      }
      return null;
    }
    final closeT = timeOf('마감 청산');
    final card = {...asMap(t['card']), 'code': t['code'], 'name': t['name']};
    final cur = '${t['state'] ?? ''}';
    final prevDay = !dtIsToday({'date': t['date']});
    // 매수구간·매도신호포착 상태면 깜빡임 (끝난 종목은 끝난 뒤 10분까지만)
    final ended = DateTime.tryParse('${t['exit_time'] ?? ''}'.replaceFirst(' ', 'T'));
    final blink = (cur == '매수구간' || cur == '매도신호포착') &&
        (!done || (ended != null && DateTime.now().difference(ended).inMinutes < 10));
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 5),
      shape: RoundedRectangleBorder(
          side: BorderSide(color: done ? _resultColor(t['result'] as String?) : Colors.blueGrey, width: 1.2),
          borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          InkWell(
            onTap: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${t['code']}', name: '${t['name']}'))),
            child: Row(children: [
              Expanded(
                  child: StockName('${t['name']}', score: t['score'] as num?, scoreDigits: 1, style: tx.titleMedium)),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text(won(last), style: tx.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                Text('매수가 대비 ${pnl == null ? '-' : pct(pnl)}',
                    style: tx.bodySmall?.copyWith(color: (pnl ?? 0) >= 0 ? upColor : downColor)),
              ]),
            ]),
          ),
          const SizedBox(height: 4),
          infoBoxes([
            InfoBox('${prevDay ? '${'${t['date']}'.substring(5)} ' : ''}${t['time']} 포착', bold: true, fill: true),
            InfoBox('매수 ${num0(t['entry'] as num?)} (${num0(t['buy_lo'] as num?)}~${num0(t['buy_hi'] as num?)})'),
            InfoBox('손절 ${num0(t['stop'] as num?)}', color: downColor),
            InfoBox('1차 ${num0(t['t1'] as num?)}', color: upColor),
            InfoBox('2차 ${num0(t['t2'] as num?)}', color: upColor),
            if (t['t3'] != null) InfoBox('3차 ${num0(t['t3'] as num?)}', color: upColor),
          ]),
          const SizedBox(height: 6),
          // 기존 상태설명: 충족 순간의 카드 그대로
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              initiallyExpanded: false,
              title: Text('기존 상태설명 (${t['time']} 충족 때)', style: tx.bodyMedium),
              children: [lc ? LimitcatchTile(r: card, rank: 1) : DaytradeTile(r: card, rank: 1)],
            ),
          ),
          // 현재 상태 | 시간 | 매매결과
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              flex: 6,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('현재 상태', style: tx.labelMedium?.copyWith(color: Colors.grey)),
                for (final s in [..._states, if (closeT != null) '마감 청산'])
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 1.5),
                    child: Row(children: [
                      Expanded(
                          child: Blink(
                              on: cur == s && blink,
                              child: Text(s,
                                  style: tx.bodySmall?.copyWith(
                                      fontWeight: (cur == s || (s == '손절' && cur == '본전 매도')) ? FontWeight.bold : null,
                                      color: cur == s && blink
                                          ? (s == '매수구간' ? upColor : downColor)
                                          : (timeOf(s) == null ? Colors.grey : null))))),
                      SizedBox(
                          width: 46,
                          child: Text(timeOf(s) ?? '-', textAlign: TextAlign.right, style: tx.bodySmall)),
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
                  Text(pct(pnl), style: tx.titleSmall?.copyWith(color: (pnl ?? 0) >= 0 ? upColor : downColor)),
                  Text('평균 매도 ${num0(t['exit_price'] as num?)}', style: tx.bodySmall),
                  Text('${'${t['exit_time'] ?? ''}'.length >= 16 ? '${t['exit_time']}'.substring(11, 16) : ''} 끝',
                      style: tx.bodySmall?.copyWith(color: Colors.grey)),
                ] else ...[
                  Text('진행중', style: tx.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                  Blink(on: blink, child: Text(cur, style: tx.bodySmall?.copyWith(fontWeight: blink ? FontWeight.bold : null))),
                  Text(lc ? '다음 날 09:30 까지' : '15:20 까지', style: tx.bodySmall?.copyWith(color: Colors.grey)),
                  if (quote != null)
                    Text('지금가 기준${where == null ? '' : ' $where'} · 저녁 확정',
                        style: tx.bodySmall?.copyWith(color: Colors.orange)),
                ],
              ]),
            ),
          ]),
        ]),
      ),
    );
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
