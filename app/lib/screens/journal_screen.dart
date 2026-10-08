import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';

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
          bottom: const TabBar(tabs: [Tab(text: '기록'), Tab(text: '내 매매 분석')]),
        ),
        body: TabBarView(children: [
          _Records(key: ValueKey('r$_mode$_gen'), mode: _mode),
          _Analysis(key: ValueKey('a$_mode$_gen'), mode: _mode),
        ]),
      ),
    );
  }
}

class _Records extends StatelessWidget {
  const _Records({super.key, this.mode});
  final String? mode;

  @override
  Widget build(BuildContext context) {
    return Loader<List<Json>>(
      future: Api.journal(mode: mode),
      builder: (context, rows) {
        if (rows.isEmpty) return const Center(child: Text('아직 기록이 없습니다.\n매수/매도하면 자동으로 쌓입니다.', textAlign: TextAlign.center));
        return ListView(padding: const EdgeInsets.all(12), children: rows.map((p) => _EntryCard(p: p)).toList());
      },
    );
  }
}

class _EntryCard extends StatelessWidget {
  const _EntryCard({required this.p});
  final Json p;

  @override
  Widget build(BuildContext context) {
    final closed = p['status'] == 'closed';
    final ret = (p['ret_pct'] as num?)?.toDouble();
    final reasons = List<String>.from(p['reasons'] as List? ?? []);
    final t = Theme.of(context).textTheme;
    final result = p['result'] as String? ?? '';
    final resultColor = result == '성공' ? upColor : (result == '실패' ? downColor : Colors.grey);
    return Card(
      child: ExpansionTile(
        title: Row(children: [
          Expanded(child: Text('${p['name']}', style: const TextStyle(fontWeight: FontWeight.bold))),
          if (closed)
            Text(pct(ret), style: TextStyle(fontWeight: FontWeight.bold, color: (ret ?? 0) >= 0 ? upColor : downColor))
          else
            const Text('보유 중', style: TextStyle(color: Colors.teal)),
        ]),
        subtitle: Text('${_modes[p['mode']] ?? p['mode']} · ${strategyLabels[p['strategy']] ?? p['strategy'] ?? '-'} · '
            '${(p['entry_time'] as String).substring(0, 16)}', style: t.bodySmall),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _kv('매수가', won(p['entry_price'] as num?)),
          _kv('매수시간', (p['entry_time'] as String).substring(11, 16)),
          _kv('당시 점수', (p['score'] as num?)?.toStringAsFixed(0) ?? '-'),
          _kv('전략', strategyLabels[p['strategy']] ?? '${p['strategy'] ?? '-'}'),
          _kv('손절', won(p['stop'] as num?)),
          _kv('목표1', won(p['target1'] as num?)),
          _kv('목표2', won(p['target2'] as num?)),
          if (p['market_mood'] != null) _kv('시장 분위기', '${p['market_mood']}'),
          if (closed) ...[
            const Divider(),
            _kv('매도가', '${won(p['exit_price'] as num?)} (${p['exit_reason'] ?? ''})'),
            _kv('수익률', pct(ret)),
            _kv('보유기간', '${p['hold_days']}일'),
            Row(children: [
              const Expanded(child: Text('결과')),
              Text(result, style: TextStyle(color: resultColor, fontWeight: FontWeight.bold)),
            ]),
            if (p['late_stop'] == 1) const Text('⚠ 손절가보다 늦게 매도', style: TextStyle(color: Colors.orange)),
          ],
          _kv('보유 중 최대 손실 / 수익', '${pct(p['mae_pct'] as num?)} / ${pct(p['mfe_pct'] as num?)}'),
          if (reasons.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('매수 이유', style: t.labelLarge),
            Text(reasons.take(6).join(' + '), style: t.bodySmall),
          ],
        ],
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [Expanded(child: Text(k)), Text(v)]),
      );
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
