import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../live.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'stock_detail_screen.dart';

const _modes = {null: '전체', 'paper': '모의', 'kis_paper': 'KIS 모의', 'real': '실전', 'manual': '직접 입력'};

/// 매매일지 + 내 매매 분석
class JournalScreen extends StatefulWidget {
  const JournalScreen({super.key});

  @override
  State<JournalScreen> createState() => _JournalScreenState();
}

class _JournalScreenState extends State<JournalScreen> {
  String? _mode;
  int _gen = 0; // 새로고침할 때마다 +1 → 기록·분석을 다시 불러옴

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const LogoTitle('매매일지'),
          actions: topActions(context, onRefresh: () => setState(() => _gen++), extra: [
            PopupMenuButton<String?>(
              tooltip: '매매 구분',
              initialValue: _mode,
              icon: const Icon(Icons.filter_list),
              onSelected: (v) => setState(() => _mode = v),
              itemBuilder: (_) => _modes.entries.map((e) => PopupMenuItem(value: e.key, child: Text(e.value))).toList(),
            ),
          ]),
          bottom: const TabBar(tabs: [Tab(text: '매매내역'), Tab(text: '내 매매 분석')]),
        ),
        body: TabBarView(children: [
          _Records(key: ValueKey('r$_mode$_gen'), mode: _mode),
          _Analysis(key: ValueKey('a$_mode$_gen'), mode: _mode),
        ]),
      ),
    );
  }
}

/// 매매내역: 종목명 · 매수일 · 매도일 · 수익률 (보유 중이면 지금 시세로 수익률)
class _Records extends StatelessWidget {
  const _Records({super.key, this.mode});
  final String? mode;

  Future<(List<Json>, Map<String, LiveQuote>)> _load() async {
    // 매도까지 끝난 매매만 · 매도일 최신순
    final rows = (await Api.journal(status: 'closed', mode: mode)).toList()
      ..sort((a, b) => '${b['exit_time'] ?? ''}'.compareTo('${a['exit_time'] ?? ''}'));
    final open = rows.where((p) => p['status'] != 'closed').map((p) => '${p['code']}').toSet().toList();
    Map<String, LiveQuote> q = const {};
    if (open.isNotEmpty) {
      try {
        q = (await Live.stocks(open)).quotes;
      } catch (_) {}
    }
    return (rows, q);
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Loader<(List<Json>, Map<String, LiveQuote>)>(
      future: _load(),
      builder: (context, d) {
        final (rows, quotes) = d;
        if (rows.isEmpty) return const Center(child: Text('아직 매도한 매매가 없습니다.\n보유종목에서 [매도]를 누르면 여기에 쌓입니다.', textAlign: TextAlign.center));
        final head = t.bodySmall?.copyWith(color: Colors.grey);
        return ListView(padding: const EdgeInsets.all(12), children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: Row(children: [
              Expanded(flex: 4, child: Text('종목명', style: head)),
              Expanded(flex: 3, child: Text('매수일', style: head, textAlign: TextAlign.center)),
              Expanded(flex: 3, child: Text('매도일', style: head, textAlign: TextAlign.center)),
              Expanded(flex: 3, child: Text('수익률', style: head, textAlign: TextAlign.right)),
            ]),
          ),
          ...rows.map((p) => _EntryRow(p: p, q: quotes['${p['code']}'])),
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
    final summary = info['summary'] as String?;
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
  const _Analysis({super.key, this.mode});
  final String? mode;

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
    final t = Theme.of(context).textTheme;
    return Loader<Json>(
      future: _f,
      builder: (context, a) {
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
            Card(
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
      },
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
