import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../live.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'stock_detail_screen.dart';

const _modes = {null: '전체', 'paper': '모의', 'kis_paper': 'KIS 모의', 'real': '실전', 'manual': '직접 입력', 'signal': '당일매매 자동'};

/// 관심 구분 (positions.list_key — 당일매매 자동은 daytrade·limitcatch)
const _kinds = {
  null: '전체 구분', 'v3': 'V3', 'nextday': '익일유망주', 'early': '상승초기', 'reversal': '추세전환', 'uplimit': '상파',
  'daytrade': '당일단타', 'limitcatch': '상한가포착', 'closingbet': '종가배팅', '_none': '기타·직접',
};

String _kindOf(Json p) {
  final k = p['list_key'] as String?;
  if (k != null && k.isNotEmpty && k != 'overall') return k;
  final o = asMap(asMap(p['plan'])['origin']);
  final tabs = (o['tabs'] as List? ?? const []);
  return tabs.isNotEmpty ? '${tabs.first}' : '_none';
}

/// 매매내역·분석 공통 검색 조건 (일별 · 기간별 · 관심 구분 · 종목명)
class JournalFilter {
  const JournalFilter({this.from, this.to, this.kind, this.q = ''});
  final DateTime? from, to; // 매수일 기준 (둘 다 같으면 일별)
  final String? kind;
  final String q;
  bool get isEmpty => from == null && to == null && kind == null && q.trim().isEmpty;

  bool match(Json p) {
    final d = DateTime.tryParse('${p['entry_time'] ?? ''}'.replaceFirst(' ', 'T'));
    if (from != null && (d == null || d.isBefore(DateTime(from!.year, from!.month, from!.day)))) return false;
    if (to != null && (d == null || !d.isBefore(DateTime(to!.year, to!.month, to!.day).add(const Duration(days: 1))))) {
      return false;
    }
    if (kind != null && _kindOf(p) != kind) return false;
    final s = q.trim();
    if (s.isNotEmpty && !'${p['name'] ?? ''}'.contains(s) && !'${p['code'] ?? ''}'.startsWith(s)) return false;
    return true;
  }

  String label() {
    String f(DateTime d) => '${d.month}/${d.day}';
    if (from == null && to == null) return '전체 기간';
    if (from != null && to != null && f(from!) == f(to!) && from!.year == to!.year) return '${f(from!)} 하루';
    return '${from == null ? '처음' : f(from!)} ~ ${to == null ? '오늘' : f(to!)}';
  }
}

/// 매매일지 + 내 매매 분석 (위쪽 검색 조건을 두 탭에 같이 적용)
class JournalScreen extends StatefulWidget {
  const JournalScreen({super.key});

  @override
  State<JournalScreen> createState() => _JournalScreenState();
}

class _JournalScreenState extends State<JournalScreen> {
  String? _mode;
  int _gen = 0; // 새로고침할 때마다 +1 → 기록·분석을 다시 불러옴
  JournalFilter _f = const JournalFilter();
  final _qc = TextEditingController();
  late Future<List<Json>> _closed = _loadClosed();

  Future<List<Json>> _loadClosed() async =>
      (await Api.journal(status: 'closed', mode: _mode)).toList()
        ..sort((a, b) => '${b['exit_time'] ?? ''}'.compareTo('${a['exit_time'] ?? ''}'));

  void _reload() => setState(() {
        _gen++;
        _closed = _loadClosed();
      });

  @override
  void dispose() {
    _qc.dispose();
    super.dispose();
  }

  Future<void> _pickDay() async {
    final now = DateTime.now();
    final d = await showDatePicker(
        context: context, initialDate: _f.from ?? now, firstDate: DateTime(2024), lastDate: now, helpText: '매수일 (하루)');
    if (d != null) setState(() => _f = JournalFilter(from: d, to: d, kind: _f.kind, q: _f.q));
  }

  Future<void> _pickRange() async {
    final now = DateTime.now();
    final r = await showDateRangePicker(
        context: context,
        firstDate: DateTime(2024),
        lastDate: now,
        initialDateRange: _f.from != null ? DateTimeRange(start: _f.from!, end: _f.to ?? now) : null,
        helpText: '매수일 기간');
    if (r != null) setState(() => _f = JournalFilter(from: r.start, to: r.end, kind: _f.kind, q: _f.q));
  }

  void _quick(int days) {
    final now = DateTime.now();
    setState(() => _f = JournalFilter(
        from: days == 0 ? now : now.subtract(Duration(days: days)), to: now, kind: _f.kind, q: _f.q));
  }

  Widget _filterBar(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: Column(children: [
        Row(children: [
          Expanded(
            child: TextField(
              controller: _qc,
              decoration: const InputDecoration(
                  isDense: true, prefixIcon: Icon(Icons.search, size: 20), hintText: '종목명·코드 검색', border: OutlineInputBorder()),
              onChanged: (v) => setState(() => _f = JournalFilter(from: _f.from, to: _f.to, kind: _f.kind, q: v)),
            ),
          ),
          const SizedBox(width: 8),
          DropdownButton<String?>(
            value: _f.kind,
            underline: const SizedBox.shrink(),
            items: _kinds.entries.map((e) => DropdownMenuItem(value: e.key, child: Text(e.value))).toList(),
            onChanged: (v) => setState(() => _f = JournalFilter(from: _f.from, to: _f.to, kind: v, q: _f.q)),
          ),
        ]),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final (label, onTap) in <(String, VoidCallback)>[
              ('전체', () => setState(() => _f = JournalFilter(kind: _f.kind, q: _f.q))),
              ('오늘', () => _quick(0)),
              ('1주', () => _quick(7)),
              ('1개월', () => _quick(30)),
              ('3개월', () => _quick(91)),
              ('일별', _pickDay),
              ('기간', _pickRange),
            ])
              Padding(
                padding: const EdgeInsets.only(right: 4),
                child: ActionChip(label: Text(label), onPressed: onTap, visualDensity: VisualDensity.compact),
              ),
            const SizedBox(width: 6),
            Text(_f.label(), style: t.bodySmall?.copyWith(fontWeight: FontWeight.bold)),
            if (!_f.isEmpty)
              IconButton(
                  tooltip: '검색 조건 지우기',
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: () => setState(() {
                        _qc.clear();
                        _f = const JournalFilter();
                      })),
          ]),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const LogoTitle('매매일지'),
          actions: topActions(context, onRefresh: _reload, extra: [
            PopupMenuButton<String?>(
              tooltip: '매매 구분',
              initialValue: _mode,
              icon: const Icon(Icons.filter_list),
              onSelected: (v) => setState(() {
                _mode = v;
                _closed = _loadClosed();
              }),
              itemBuilder: (_) => _modes.entries.map((e) => PopupMenuItem(value: e.key, child: Text(e.value))).toList(),
            ),
          ]),
          bottom: const TabBar(tabs: [Tab(text: '매매내역'), Tab(text: '내 매매 분석')]),
        ),
        body: Column(children: [
          _filterBar(context),
          Expanded(
            child: TabBarView(children: [
              _Records(key: ValueKey('r$_mode$_gen'), future: _closed, filter: _f),
              _Analysis(key: ValueKey('a$_mode$_gen'), mode: _mode, future: _closed, filter: _f),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// 매매내역: 종목명 · 매수일 · 매도일 · 수익률 (위 검색 조건 적용)
class _Records extends StatelessWidget {
  const _Records({super.key, required this.future, required this.filter});
  final Future<List<Json>> future;
  final JournalFilter filter;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Loader<List<Json>>(
      future: future,
      builder: (context, all) {
        if (all.isEmpty) {
          return const Center(child: Text('아직 매도한 매매가 없습니다.\n보유종목에서 [매도]를 누르면 여기에 쌓입니다.', textAlign: TextAlign.center));
        }
        final rows = all.where(filter.match).toList();
        final head = t.bodySmall?.copyWith(color: Colors.grey);
        final rets = [for (final p in rows) (p['ret_pct'] as num?)?.toDouble()].whereType<double>().toList();
        final win = rets.where((r) => r > 0).length;
        return ListView(padding: const EdgeInsets.all(12), children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 6),
            child: Text(
                '${rows.length}건${rets.isEmpty ? '' : ' · 승률 ${(win / rets.length * 100).toStringAsFixed(1)}% · 평균 ${pct(rets.reduce((a, b) => a + b) / rets.length)}'}',
                style: t.bodySmall?.copyWith(fontWeight: FontWeight.bold)),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: Row(children: [
              Expanded(flex: 4, child: Text('종목명', style: head)),
              Expanded(flex: 3, child: Text('매수일', style: head, textAlign: TextAlign.center)),
              Expanded(flex: 3, child: Text('매도일', style: head, textAlign: TextAlign.center)),
              Expanded(flex: 3, child: Text('수익률', style: head, textAlign: TextAlign.right)),
            ]),
          ),
          if (rows.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('조건에 맞는 매매가 없어요'))),
          ...rows.map((p) => _EntryRow(p: p)),
        ]);
      },
    );
  }
}

class _EntryRow extends StatelessWidget {
  const _EntryRow({required this.p, this.q});
  final Json p;
  final LiveQuote? q;

  static String _d(dynamic v) {
    final s = '${v ?? ''}';
    if (s.length < 10) return '-';
    final now = DateTime.now().year.toString();
    return s.startsWith(now) ? '${int.parse(s.substring(5, 7))}/${int.parse(s.substring(8, 10))}' : s.substring(2, 10).replaceAll('-', '/');
  }

  @override
  Widget build(BuildContext context) {
    final closed = p['status'] == 'closed';
    final entry = (p['entry_price'] as num?)?.toDouble();
    double? ret = (p['ret_pct'] as num?)?.toDouble();
    if (!closed && entry != null && entry > 0 && q != null && q!.price > 0) ret = (q!.price / entry - 1) * 100;
    // 매수 당시: 어떤 후보 탭·몇 위·몇 점·상태 (저녁/장중 배치가 positions.plan.entry_info 에 기록)
    final info = asMap(asMap(p['plan'])['entry_info']);
    final kind = _kindOf(p);
    final summary = (info['summary'] as String?) ??
        (p['mode'] == 'signal'
            ? '${_kinds[kind] ?? kind} ${'${p['signal_time'] ?? p['entry_time']}'.length >= 16 ? '${p['signal_time'] ?? p['entry_time']}'.substring(11, 16) : ''} 포착 · ${p['exit_reason'] ?? ''}'
            : null);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 3),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.push(context,
            MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${p['code']}', name: '${p['name']}'))),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
                flex: 4,
                child: Text('${p['name']}',
                    style: const TextStyle(fontWeight: FontWeight.bold), overflow: TextOverflow.ellipsis)),
            Expanded(flex: 3, child: Text(_d(p['entry_time']), textAlign: TextAlign.center)),
            Expanded(
                flex: 3,
                child: Text(closed ? _d(p['exit_time']) : '보유 중',
                    textAlign: TextAlign.center, style: closed ? null : const TextStyle(color: Colors.teal))),
            Expanded(
                flex: 3,
                child: Text(pct(ret),
                    textAlign: TextAlign.right,
                    style: TextStyle(fontWeight: FontWeight.bold, color: (ret ?? 0) >= 0 ? upColor : downColor))),
          ]),
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
                summary == null
                    ? '매수 당시 정보: 다음 배치 때 기록됩니다'
                    : '매수 당시${info['report_date'] == null ? '' : '(${_d(info['report_date'])} 분석)'}: $summary',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: summary == null ? Colors.grey : null)),
          ),
          ]),
        ),
      ),
    );
  }
}

class _Analysis extends StatefulWidget {
  const _Analysis({super.key, this.mode, required this.future, required this.filter});
  final String? mode;
  final Future<List<Json>> future; // 매도까지 끝난 매매 (매매내역과 같은 목록)
  final JournalFilter filter;

  @override
  State<_Analysis> createState() => _AnalysisState();
}

class _AnalysisState extends State<_Analysis> {
  late final Future<Json> _f = Api.journalAnalysis(mode: widget.mode);
  Json? _ai;
  bool _aiLoading = false;

  Future<void> _loadAI() async {
    setState(() => _aiLoading = true);
    try {
      final r = await Api.journalAI(mode: widget.mode);
      setState(() => _ai = asMap(r['summary']));
    } catch (e) {
      setState(() => _ai = {'text': '$e', 'source': 'error'});
    } finally {
      setState(() => _aiLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // 검색 조건이 있으면: 매매내역과 같은 목록을 조건으로 걸러서 여기서 바로 분석 (전체일 때는 저녁 배치 분석 + 코치)
    if (!widget.filter.isEmpty) {
      return Loader<List<Json>>(
        future: widget.future,
        builder: (context, all) => _view(context, localAnalysis(all.where(widget.filter.match).toList(),
            label: widget.filter.label()), local: true),
      );
    }
    return Loader<Json>(future: _f, builder: (context, a) => _view(context, a));
  }

  Widget _view(BuildContext context, Json a, {bool local = false}) {
    final t = Theme.of(context).textTheme;
    if ((a['closed'] as int? ?? 0) == 0) {
      return Center(child: Text('${a['message'] ?? '완료된 매매가 없습니다'}'));
    }
    final s = asMap(a['summary']);
    final insights = List<String>.from(a['insights'] as List? ?? []);
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('완료 ${a['closed']}건 · ${a['period']}', style: t.titleSmall),
              const Divider(),
              _kv('승률', '${s['win_rate']}%', bold: true),
              _kv('평균 수익률', pct(s['avg_ret'] as num?)),
              _kv('평균 이익 / 평균 손실', '${pct(s['avg_win'] as num?)} / ${pct(s['avg_loss'] as num?)}'),
              _kv('Profit Factor', '${s['profit_factor'] ?? '-'}'),
              _kv('총 손익', won(s['total_pnl'] as num?)),
              _kv('평균 보유', '${s['avg_hold_days']}일'),
              _kv('최대 연속 손실', '${s['max_consec_losses']}회'),
            ]),
          ),
        ),
        if (!local) Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Icon(Icons.auto_awesome, size: 18),
                const SizedBox(width: 6),
                Text('코치 요약', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              ]),
              const SizedBox(height: 8),
              ...insights.map((x) => Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('• $x'))),
              const SizedBox(height: 4),
              if (_ai != null)
                Text('${_ai!['text']}', style: const TextStyle(height: 1.5))
              else if (_aiLoading)
                const LinearProgressIndicator()
              else
                TextButton.icon(
                    onPressed: _loadAI, icon: const Icon(Icons.psychology), label: const Text('AI 에게 내 매매 분석 받기')),
            ]),
          ),
        ),
        if (local) _table(context, '관심 구분별', a['by_kind']),
        _table(context, '전략별', a['by_strategy']),
        _table(context, '진입 시간대별', a['by_time']),
        _table(context, '진입 점수별', a['by_score']),
        _table(context, '시장 분위기별', a['by_mood']),
        _table(context, '보유기간별', a['by_hold']),
        _table(context, '매도 사유별', a['by_exit_reason']),
        _table(context, '요일별', a['by_weekday']),
        const SizedBox(height: 8),
        Text('* 표시는 표본 ${a['min_n']}건 미만 — 우연일 수 있으니 참고만', style: t.bodySmall),
      ],
    );
  }

  Widget _kv(String k, String v, {bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(k)),
          Text(v, style: TextStyle(fontWeight: bold ? FontWeight.bold : FontWeight.normal)),
        ]),
      );

  Widget _table(BuildContext context, String title, dynamic raw) {
    final rows = asList(raw);
    if (rows.isEmpty) return const SizedBox.shrink();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 6),
          ...rows.map((g) {
            final avg = (g['avg_ret'] as num).toDouble();
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                Expanded(flex: 4, child: Text('${g['group']}${g['low_confidence'] == true ? ' *' : ''}')),
                Expanded(flex: 2, child: Text('${g['n']}건', textAlign: TextAlign.right)),
                Expanded(flex: 3, child: Text('승률 ${g['win_rate']}%', textAlign: TextAlign.right)),
                Expanded(
                    flex: 3,
                    child: Text(pct(avg), textAlign: TextAlign.right, style: TextStyle(color: avg >= 0 ? upColor : downColor))),
              ]),
            );
          }),
        ]),
      ),
    );
  }
}


/// 검색 조건으로 거른 매매로 바로 계산하는 분석 (저녁 배치 분석과 같은 칸 이름)
Json localAnalysis(List<Json> rows, {String label = ''}) {
  final rets = [for (final p in rows) (p['ret_pct'] as num?)?.toDouble() ?? 0.0];
  if (rows.isEmpty) return {'closed': 0, 'message': '조건에 맞는 완료된 매매가 없어요'};
  final wins = rets.where((r) => r > 0).toList(), losses = rets.where((r) => r <= 0).toList();
  double avg(List<double> v) => v.isEmpty ? 0 : v.reduce((a, b) => a + b) / v.length;
  double r2(double v) => (v * 100).roundToDouble() / 100;
  final gw = wins.fold<double>(0, (a, b) => a + b), gl = -losses.fold<double>(0, (a, b) => a + b);
  int run = 0, maxRun = 0;
  final byTime = [...rows]..sort((a, b) => '${a['exit_time']}'.compareTo('${b['exit_time']}'));
  for (final p in byTime) {
    if (((p['ret_pct'] as num?) ?? 0) <= 0) {
      run++;
      if (run > maxRun) maxRun = run;
    } else {
      run = 0;
    }
  }
  List<Json> group(String Function(Json) key) {
    final m = <String, List<double>>{};
    for (final p in rows) {
      m.putIfAbsent(key(p), () => []).add(((p['ret_pct'] as num?) ?? 0).toDouble());
    }
    return [
      for (final e in m.entries)
        {'group': e.key, 'n': e.value.length, 'win_rate': r2(e.value.where((r) => r > 0).length / e.value.length * 100),
         'avg_ret': r2(avg(e.value)), 'low_confidence': e.value.length < 5}
    ]..sort((a, b) => (b['n'] as int).compareTo(a['n'] as int));
  }
  String slot(Json p) {
    final s = '${p['entry_time'] ?? ''}';
    final h = s.length >= 13 ? int.tryParse(s.substring(11, 13)) ?? 0 : 0;
    return h < 9 ? '장 전' : (h < 10 ? '09시' : (h < 12 ? '10~11시' : (h < 14 ? '12~13시' : '14시 이후')));
  }
  const wd = ['월', '화', '수', '목', '금', '토', '일'];
  return {
    'closed': rows.length,
    'period': label,
    'min_n': 5,
    'summary': {
      'win_rate': r2(wins.length / rows.length * 100), 'avg_ret': r2(avg(rets)), 'avg_win': r2(avg(wins)),
      'avg_loss': r2(avg(losses)), 'profit_factor': gl > 0 ? r2(gw / gl) : null,
      'total_pnl': rows.fold<double>(0, (a, p) => a + (((p['pnl'] as num?) ?? 0).toDouble())),
      'avg_hold_days': r2(avg([for (final p in rows) ((p['hold_days'] as num?) ?? 0).toDouble()])),
      'max_consec_losses': maxRun,
    },
    'insights': const <String>[],
    'by_kind': group((p) => _kinds[_kindOf(p)] ?? _kindOf(p)),
    'by_strategy': group((p) => '${p['strategy'] ?? '-'}'),
    'by_time': group(slot),
    'by_exit_reason': group((p) => '${p['exit_reason'] ?? '-'}'),
    'by_hold': group((p) {
      final d = ((p['hold_days'] as num?) ?? 0).toInt();
      return d == 0 ? '당일' : (d <= 2 ? '1~2일' : (d <= 10 ? '3~10일' : '11일 이상'));
    }),
    'by_weekday': group((p) {
      final d = DateTime.tryParse('${p['entry_time'] ?? ''}'.replaceFirst(' ', 'T'));
      return d == null ? '-' : wd[d.weekday - 1];
    }),
  };
}
