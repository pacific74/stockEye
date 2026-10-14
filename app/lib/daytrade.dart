import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 당일단타 (DT-0.1) — PC 가 평일 09:00~10:00 1분마다 올리는 후보 (system_status 'daytrade')
///   상태: 진입 조건 충족(80↑+신호) / 진입 대기(80↑) / 관찰(70↑) / 진입 금지(필수 제외)
///   주문은 하지 않음 — 알림·관찰용

Color dtStatusColor(String? s) => switch (s) {
      '진입 조건 충족' => const Color(0xFFD32F2F),
      '진입 대기' => Colors.orange,
      '관찰' => Colors.teal,
      _ => Colors.grey,
    };

/// 1분 자동 새로고침 시간대 (평일): 당일단타 09:00~10:05 · 종가배팅 14:50~15:25 — 그 밖엔 새로 읽지 않음 (서버 부하 없음)
bool liveWindow({bool closing = false}) {
  final n = DateTime.now();
  if (n.weekday > 5) return false;
  final m = n.hour * 60 + n.minute;
  return closing ? (m >= 14 * 60 + 50 && m <= 15 * 60 + 25) : (m >= 9 * 60 && m <= 10 * 60 + 5);
}

String _hm2(DateTime t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

/// '10:01 계산 · 10:02 조회' (오늘 것이 아니면 계산 날짜도 '10/09 15:20 계산')
String lookupLabel(Json d, DateTime? fetchedAt) {
  final parts = <String>[];
  if (d['time'] != null) {
    final date = '${d['date'] ?? ''}';
    final day = !dtIsToday(d) && date.length >= 10 ? '${date.substring(5, 7)}/${date.substring(8, 10)} ' : '';
    parts.add('$day${d['time']} 계산');
  }
  if (fetchedAt != null) parts.add('${_hm2(fetchedAt)} 조회');
  return parts.join(' · ');
}

/// 오늘 데이터인지 (어제 것이면 '오늘 아직 없음')
bool dtIsToday(Json d) {
  final now = DateTime.now();
  final today = '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
  return d['date'] == today;
}

/// 카드 안 뉴스 한 줄 (장중 카드가 찾은 뉴스 · 악재 먼저) — 제목 1개 + 나머지 건수. 전체는 눌러서 상세 화면
class NewsLine extends StatelessWidget {
  const NewsLine(this.items, {super.key});
  final List<Json> items;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    final f = items.first;
    final tone = (f['tone'] as num?)?.toInt() ?? 0;
    final c = tone < 0 ? downColor : (tone > 0 ? upColor : Colors.grey);
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Row(children: [
        Icon(tone < 0 ? Icons.warning_amber_rounded : Icons.article_outlined, size: 14, color: c),
        const SizedBox(width: 4),
        Expanded(
            child: Text('${f['title']}',
                maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodySmall)),
        if (items.length > 1)
          Text(' 외 ${items.length - 1}건', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey)),
      ]),
    );
  }
}

/// 후보 카드: 순위 · 종목명 [점수] · 현재가 / 상태 · 유형 · VWAP · 거래대금 / 진입 · 손절 · 1·2차 / 근거
class DaytradeTile extends StatelessWidget {
  const DaytradeTile({super.key, required this.r, required this.rank, this.price});
  final Json r;
  final int rank;
  final double? price; // 지금 시세 (없으면 계산 때 가격)

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final st = '${r['status'] ?? ''}';
    final col = dtStatusColor(st);
    final px = price ?? (r['price'] as num?)?.toDouble();
    final ex = (r['excluded'] as List? ?? const []).map((e) => '$e').toList();
    final warns = (r['warnings'] as List? ?? const []).map((e) => '$e').toList();
    final reasons = (r['reasons'] as List? ?? const []).map((e) => '$e').toList();
    final vg = r['vwap_gap_pct'] as num?;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      shape: st == '진입 조건 충족'
          ? RoundedRectangleBorder(side: BorderSide(color: col, width: 1.5), borderRadius: BorderRadius.circular(12))
          : null,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.push(context,
            MaterialPageRoute(builder: (_) => StockDetailScreen(
                code: '${r['code']}', name: '${r['name']}', source: 'daytrade', intraday: r))),
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
                  if (r['type'] != null) InfoBox('${r['type']}형'),
                  if (vg != null) InfoBox('VWAP ${vg >= 0 ? '+' : ''}${vg.toStringAsFixed(1)}%', color: vg >= 3 ? Colors.orange : null),
                  if (r['value'] is num) InfoBox('오전 ${((r['value'] as num) / 1e8).toStringAsFixed(0)}억'),
                  if (r['chg_pct'] is num) InfoBox('오늘 ${pct(r['chg_pct'] as num)}', color: (r['chg_pct'] as num) >= 0 ? upColor : downColor),
                ]),
                const SizedBox(height: 3),
                infoBoxes([
                  InfoBox('진입 ${num0(r['entry'] as num?)}', bold: true),
                  InfoBox('손절 ${num0(r['stop'] as num?)}${r['risk_pct'] is num ? ' (−${(r['risk_pct'] as num).toStringAsFixed(1)}%)' : ''}',
                      color: downColor),
                  InfoBox('1차 ${num0(r['t1'] as num?)}${r['t1_pct'] is num ? ' (+${r['t1_pct']}%)' : ''}', color: upColor),
                  InfoBox('2차 ${num0(r['t2'] as num?)}${r['t2_pct'] is num ? ' (+${r['t2_pct']}%)' : ''}', color: upColor),
                  if (r['adr_pct'] is num) InfoBox('평소 하루 폭 ${r['adr_pct']}%'),
                ]),
                for (final x in ex) Text('⛔ $x', style: t.bodySmall?.copyWith(color: Colors.red)),
                for (final x in warns) Text('⚠ $x', style: t.bodySmall?.copyWith(color: Colors.orange)),
                if (reasons.isNotEmpty) Text(reasons.join(' · '), style: t.bodySmall?.copyWith(color: Colors.grey)),
                NewsLine(asList(r['news'])),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

/// 관심 > 당일단타 탭 — 1분마다 자동 새로고침
class DaytradeTab extends StatefulWidget {
  const DaytradeTab({super.key});
  @override
  State<DaytradeTab> createState() => _DaytradeTabState();
}

class _DaytradeTabState extends State<DaytradeTab> with AutomaticKeepAliveClientMixin {
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
      if (liveWindow()) _load(); // 09:00~10:05 에만 1분마다
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final d = await Api.daytrade();
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
            Text('당일단타', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            const Spacer(),
            DaytradeFindButton(onDone: _load),
          ]),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 4),
          child: Text(
              today
                  ? '${lookupLabel(d, _at)}${d['closed'] == true ? ' (오늘 탐색 끝)' : liveWindow() ? ' · 1분마다 갱신' : ''} · 후보 ${d['scanned'] ?? 0} · '
                      '충족 ${c['진입 조건 충족'] ?? 0} · 대기 ${c['진입 대기'] ?? 0} · 관찰 ${c['관찰'] ?? 0}'
                  : '오늘 당일단타 결과가 아직 없어요. 평일 PC 에서 22_intraday.bat(당일매매 통합)을 켜 두면 09:00~10:00 동안 1분마다 올라와요. PC 가 꺼진 날은 관리자 [종목찾기].'
                      '${d['date'] != null ? ' (아래는 ${d['date']} ${d['time']} 결과)' : ''}',
              style: t.bodySmall),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 6),
          child: Text('점수가 높아도 진입 신호(돌파·눌림목)가 없으면 사지 않아요. 손절은 진입가 −1.5% 이내, 목표는 1차 +3% 이상(절반)·2차 +5% 이상, '
              '평소 하루 5% 넘게 움직이는 종목만. 장 마감 전 청산. 주문은 하지 않는 알림용이에요.',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
        ),
        if (items.isEmpty)
          const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('조건에 맞는 종목이 없어요'))),
        ...items.asMap().entries.map((e) => DaytradeTile(r: e.value, rank: e.key + 1)),
        ..._signals(context, d),
      ]),
    );
  }

  List<Widget> _signals(BuildContext context, Json d) {
    final s = asList(d['signals']);
    if (s.isEmpty) return const [];
    final t = Theme.of(context).textTheme;
    return [
      const SectionTitle('오늘 신호 기록'),
      for (final x in s)
        Text('${x['time']} ${x['name']} ${x['type']}형 · 진입 ${num0(x['entry'] as num?)} · 손절 ${num0(x['stop'] as num?)}'
            ' · 1차 ${num0(x['t1'] as num?)} · 2차 ${num0(x['t2'] as num?)}',
            style: t.bodySmall),
    ];
  }
}

/// [종목찾기] — 관리자만 (당일단타·종가배팅·상한가포착 공용). GitHub 이 지금 시세로 한 번 계산(1~3분) → 끝나면 onDone 으로 다시 읽기
class DaytradeFindButton extends StatefulWidget {
  const DaytradeFindButton({super.key, this.onDone, this.closing = false, this.kind});
  final VoidCallback? onDone;
  final bool closing; // true = 종가배팅 [종목찾기]
  final String? kind; // 'daytrade' · 'closingbet' · 'limitcatch' (없으면 closing 으로 정함)
  String get k => kind ?? (closing ? 'closingbet' : 'daytrade');
  @override
  State<DaytradeFindButton> createState() => _DaytradeFindButtonState();
}

class _DaytradeFindButtonState extends State<DaytradeFindButton> {
  bool _busy = false;
  bool _pcLive = false; // PC 가 지금 1분마다 올리는 중이면 버튼 숨김
  Timer? _poll;
  Timer? _watch;

  @override
  void initState() {
    super.initState();
    if (useCloud && isAdminUser) {
      _checkPc();
      _watch = Timer.periodic(const Duration(seconds: 60), (_) => _checkPc());
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    _watch?.cancel();
    super.dispose();
  }

  /// PC 실행 중 = 최근 결과가 PC 것이고 3분 안에 갱신됐고 아직 끝나지 않음
  Future<void> _checkPc() async {
    final d = await switch (widget.k) {
      'closingbet' => Api.closingbet(),
      'limitcatch' => Api.limitcatch(),
      _ => Api.daytrade(),
    };
    final at = DateTime.tryParse('${d['updated_at'] ?? ''}');
    final live = d['runner'] == 'pc' &&
        d['closed'] != true &&
        at != null &&
        DateTime.now().difference(at.toLocal()).inMinutes < 3;
    if (mounted && live != _pcLive) setState(() => _pcLive = live);
  }

  void _snack(String m) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _find() async {
    setState(() => _busy = true);
    try {
      final r = await switch (widget.k) {
        'closingbet' => Api.requestClosingbet(),
        'limitcatch' => Api.requestLimitcatch(),
        _ => Api.requestDaytrade(),
      };
      _snack(r['ok'] == true ? '종목을 찾는 중이에요 (1~3분)' : '${r['message'] ?? '이미 찾는 중입니다'}');
    } catch (e) {
      _snack('요청 실패: ${'$e'.replaceFirst('Exception: ', '')}');
      if (mounted) setState(() => _busy = false);
      return;
    }
    final t0 = DateTime.now();
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 10), (_) async {
      final j = await switch (widget.k) {
        'closingbet' => Api.closingbetJob(),
        'limitcatch' => Api.limitcatchJob(),
        _ => Api.daytradeJob(),
      };
      final st = '${j['status'] ?? ''}';
      final late = DateTime.now().difference(t0).inMinutes >= 6;
      if (st == 'done' || st == 'failed' || late) {
        _poll?.cancel();
        if (!mounted) return;
        setState(() => _busy = false);
        _snack(st == 'done'
            ? '종목찾기 끝 · ${j['found'] ?? 0}개'
            : st == 'failed'
                ? '종목찾기 실패${j['error'] != null ? ': ${j['error']}' : ' — GitHub Actions 기록을 확인하세요'}'
                : '아직 끝나지 않았어요 — 잠시 뒤 당겨서 새로고침');
        widget.onDone?.call();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!useCloud || !isAdminUser || (_pcLive && !_busy)) return const SizedBox.shrink();
    return TextButton.icon(
      onPressed: _busy ? null : _find,
      icon: _busy
          ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
          : const Icon(Icons.search, size: 18),
      label: Text(_busy ? '찾는 중' : '종목찾기'),
    );
  }
}

/// 검증 > 당일단타: 실전 기록(매일 신호 결과) + 되돌려 보기(과거 1분봉)
Future<Json> loadDaytradeValidation() => Api.latestBacktest(strategy: 'DAYT');

class DaytradeValidation extends StatelessWidget {
  const DaytradeValidation({super.key, required this.future});
  final Future<Json> future;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return FutureBuilder<Json>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) return const SizedBox.shrink();
        final d = snap.data ?? const {};
        final fw = asMap(d['forward']), bt = asMap(d['backtest']);
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SectionTitle('당일단타 검증', trailing: Text('${d['updated'] ?? ''}', style: t.bodySmall)),
          Text('결과: 2차 익절 · 1차 익절(뒤 본전·마감) · 손절 · 장 마감 청산. 손익은 비용 0.2% 뺀 %. 승률 = 익절 ÷ (익절 + 손절)',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          const SizedBox(height: 6),
          _block(context, '실전 기록 (매일 아침 신호)', fw,
              empty: '아직 기록이 없어요. 아침에 신호가 나오면 그날 저녁 배치가 결과를 매겨요.'),
          _block(context, '되돌려 보기 (과거 1분봉)', bt,
              empty: '아직 없어요. PC 에서 15_daytrade_backtest.bat 을 실행하면 최근 20거래일로 계산해요.',
              note: bt['note'] as String?),
        ]);
      },
    );
  }

  Widget _block(BuildContext context, String title, Json r, {required String empty, String? note}) {
    final t = Theme.of(context).textTheme;
    final tot = asMap(r['total']);
    final groups = <MapEntry<String, Json>>[
      MapEntry('전체', tot),
      for (final e in asMap(r['by_type']).entries) MapEntry('${e.key}형', asMap(e.value)),
    ];
    String p(dynamic v) => '${v ?? 0}%';
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: t.titleSmall),
          if ((tot['n'] ?? 0) == 0)
            Padding(padding: const EdgeInsets.only(top: 4), child: Text(empty, style: t.bodySmall))
          else ...[
            Text('${r['first'] ?? ''} ~ ${r['last'] ?? ''} · ${r['days'] ?? 0}일${note != null ? ' · $note' : ''}',
                style: t.bodySmall?.copyWith(color: Colors.grey)),
            const SizedBox(height: 6),
            Text('결과 비율', style: t.labelMedium),
            StatTable(header: const ['구분', '건수', '2차', '1차', '손절', '마감'], rows: [
              for (final g in groups)
                [StatCell(g.key), StatCell('${g.value['n'] ?? 0}'), StatCell(p(g.value['t2'])), StatCell(p(g.value['t1'])),
                 StatCell(p(g.value['stop']), color: downColor), StatCell(p(g.value['close']))],
            ]),
            const SizedBox(height: 8),
            Text('손익 (비용 0.2% 뺀 %)', style: t.labelMedium),
            StatTable(header: const ['구분', '승률', '평균', '이긴 평균', '진 평균', '누적'], rows: [
              for (final g in groups)
                [StatCell(g.key), StatCell(g.value['win'] == null ? '-' : '${g.value['win']}%'), pnlCell(g.value['pnl'] as num?, bold: true),
                 pnlCell(g.value['avg_win'] as num?), pnlCell(g.value['avg_loss'] as num?), pnlCell(g.value['pnl_sum'] as num?, d: 1)],
            ]),
            Text('누적 = 신호마다 같은 금액을 넣었을 때 손익 % 합', style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
            if (asList(r['recent']).isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('최근 기록', style: t.labelMedium),
              StatTable(firstFlex: 1.6, boldFirst: false, header: const ['날짜', '종목', '유형', '결과', '손익'], rows: [
                for (final x in asList(r['recent']).take(10))
                  [StatCell('${'${x['date'] ?? ''}'.length >= 10 ? '${x['date']}'.substring(5) : x['date']} ${x['time'] ?? ''}'),
                   StatCell('${x['name'] ?? ''}'), StatCell('${x['type'] ?? ''}'), StatCell(_out(x['outcome'] as String?)),
                   pnlCell(x['pnl'] as num?)],
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
        'close' => '마감 청산',
        _ => '-',
      };

}
