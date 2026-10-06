import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import 'stock_detail_screen.dart';

class SectorListScreen extends StatelessWidget {
  const SectorListScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('업종 · 테마 강도')),
      body: Loader<Json>(
        future: Api.sectors(),
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
              final up = !(g['arrows'] as String).contains('↓');
              return ListTile(
                leading: SizedBox(width: 28, child: Text('$i', textAlign: TextAlign.center)),
                title: Text('${g['group']}'),
                subtitle: Text('${g['type'] == 'theme' ? '테마' : 'KRX 업종'} · ${g['members']}종목 · '
                    '오늘 ${pct(g['ret1_pct'] as num)} · 5일 ${pct(g['ret5_pct'] as num)}'),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  Text('${g['arrows']}', style: TextStyle(color: up ? upColor : downColor)),
                  const SizedBox(width: 8),
                  Text('${g['score']}', style: const TextStyle(fontWeight: FontWeight.bold)),
                ]),
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
      appBar: AppBar(title: Text('${g['group']}  ${g['arrows']}')),
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
