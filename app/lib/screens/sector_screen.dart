import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'stock_detail_screen.dart';

class SectorListScreen extends StatefulWidget {
  const SectorListScreen({super.key});

  @override
  State<SectorListScreen> createState() => _SectorListScreenState();
}

class _SectorListScreenState extends State<SectorListScreen> {
  late Future<Json> _f = Api.sectors();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(
          title: const LogoTitle('업종 · 테마 강도'),
          actions: topActions(context, onRefresh: () => setState(() => _f = Api.sectors()))),
      body: Loader<Json>(
        future: _f,
        builder: (context, d) {
          final list = asList(d['sectors']);
          return ListView.separated(
            padding: const EdgeInsets.all(8),
            itemCount: list.length + 1,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              if (i == 0) {
                return Padding(
                  padding: const EdgeInsets.all(8),
                  child: Text('점수 = 당일·5일 등락, 상승 종목 비율, 거래대금 증가, 외국인+기관 순매수, 고점 돌파 비율을 '
                      '업종끼리 비교한 순위 (0~100)', style: Theme.of(context).textTheme.bodySmall),
                );
              }
              final g = list[i - 1];
              return ListTile(
                leading: SizedBox(width: 28, child: Text('$i', textAlign: TextAlign.center)),
                title: Text('${g['group']}'),
                subtitle: Text('${g['type'] == 'theme' ? '테마' : 'KRX 업종'} · ${g['members']}종목 · '
                    '당일 ${pct(g['ret1_pct'] as num)} · 5일 ${pct(g['ret5_pct'] as num)}'),
                trailing: Text('${g['score']}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => SectorDetailScreen(g: g))),
              );
            },
          );
        },
      ),
    );
  }
}

class SectorDetailScreen extends StatelessWidget {
  const SectorDetailScreen({super.key, required this.g});
  final Json g;

  @override
  Widget build(BuildContext context) {
    final top = asList(g['top']);
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(title: LogoTitle('${g['group']}'), actions: topActions(context)),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(children: [
                _kv('강도 점수', '${g['score']} / 100'),
                _kv('오늘 등락 (거래대금 가중)', pct(g['ret1_pct'] as num)),
                _kv('5일 등락 (중앙값)', pct(g['ret5_pct'] as num)),
                _kv('상승 종목 비율', '${g['breadth_pct']}%'),
                _kv('거래대금 (20일 평균 대비)', '${g['money_ratio']}배'),
              ]),
            ),
          ),
          const SectionTitle('대표 종목 (종합 점수 순)'),
          ...top.map((t) => ListTile(
                title: Text('${t['name']}'),
                subtitle: Text('오늘 ${pct(t['ret1'] as num)}'),
                trailing: Text(t['score'] == null ? '-' : '${(t['score'] as num).toStringAsFixed(0)}점',
                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                onTap: () => Navigator.push(context,
                    MaterialPageRoute(builder: (_) => StockDetailScreen(code: t['code'] as String, name: t['name'] as String))),
              )),
        ],
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [Expanded(child: Text(k)), Text(v, style: const TextStyle(fontWeight: FontWeight.w600))]),
      );
}
