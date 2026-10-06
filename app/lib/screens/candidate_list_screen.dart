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
      initialIndex: keys.indexOf(list) < 0 ? 0 : keys.indexOf(list),
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

class _ListTabState extends State<_ListTab> with AutomaticKeepAliveClientMixin {
  late Future<Json> _f = Api.candidates(widget.listKey);

  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Loader<Json>(
      future: _f,
      onRetry: () => setState(() => _f = Api.candidates(widget.listKey)),
      builder: (context, d) {
        final cands = asList(d['candidates']);
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
            if (cands.isEmpty)
              const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('오늘 조건을 만족한 종목이 없습니다'))),
            ...cands.map((c) => CandidateTile(c: c, showStrategyScore: widget.listKey != 'overall')),
          ],
        );
      },
    );
  }
}
