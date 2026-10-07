import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets/common.dart';

/// 전략별 후보 목록 (탭으로 전환)
class CandidateListScreen extends StatelessWidget {
  const CandidateListScreen({super.key, this.list = 'overall', this.title = '후보'});
  final String list;
  final String title;

  static const keys = ['overall', 'A', 'B', 'C', 'D', 'E'];

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: keys.length,
      initialIndex: keys.contains(list) ? keys.indexOf(list) : 0,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('매수 후보'),
          bottom: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: keys.map((k) => Tab(text: strategyLabels[k])).toList(),
          ),
        ),
        body: TabBarView(children: keys.map((k) => _ListTab(listKey: k)).toList()),
      ),
    );
  }
}

class _ListTab extends StatefulWidget {
  const _ListTab({required this.listKey});
  final String listKey;

  @override
  State<_ListTab> createState() => _ListTabState();
}

enum _Sort { score, strategy, rank }

class _ListTabState extends State<_ListTab> with AutomaticKeepAliveClientMixin {
  late Future<Json> _f = Api.candidates(widget.listKey);
  _Sort _sort = _Sort.score; // 기본: 종합 점수 높은 순

  bool get _isStrategy => widget.listKey != 'overall';

  List<Json> _sorted(List<Json> cands) {
    final out = List<Json>.from(cands);
    double v(Json c, String k) => (c[k] as num?)?.toDouble() ?? -1;
    switch (_sort) {
      case _Sort.score:
        out.sort((a, b) => v(b, 'score').compareTo(v(a, 'score')));
        break;
      case _Sort.strategy:
        out.sort((a, b) => v(b, 'strategy_score').compareTo(v(a, 'strategy_score')));
        break;
      case _Sort.rank:
        out.sort((a, b) => v(a, 'rank').compareTo(v(b, 'rank')));
        break;
    }
    return out;
  }

  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Loader<Json>(
      future: _f,
      onRetry: () => setState(() => _f = Api.candidates(widget.listKey)),
      builder: (context, d) {
        final cands = _sorted(asList(d['candidates']));
        return ListView(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
          children: [
            if (d['description'] != null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('${d['name']}', style: const TextStyle(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 4),
                    Text('${d['description']}'),
                    if (d['limitation'] != null) ...[
                      const SizedBox(height: 4),
                      Text('※ ${d['limitation']}', style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ]),
                ),
              ),
            if (_isStrategy && cands.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: SegmentedButton<_Sort>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: _Sort.score, label: Text('종합점수순')),
                    ButtonSegment(value: _Sort.strategy, label: Text('전략점수순')),
                    ButtonSegment(value: _Sort.rank, label: Text('추천순')),
                  ],
                  selected: {_sort},
                  onSelectionChanged: (v) => setState(() => _sort = v.first),
                ),
              ),
            if (cands.isEmpty)
              const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('오늘 조건을 만족한 종목이 없습니다'))),
            ...cands.asMap().entries.map((e) => CandidateTile(
                c: e.value,
                rank: e.key + 1,
                showStrategyScore: _isStrategy,
                bigStrategy: _sort == _Sort.strategy)),
          ],
        );
      },
    );
  }
}
