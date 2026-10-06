import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';

class SimilarScreen extends StatelessWidget {
  const SimilarScreen({super.key, required this.code, required this.name});
  final String code;
  final String name;

  List<double> _path(dynamic v) => (v as List).map((e) => (e as num).toDouble()).toList();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('$name 비슷한 과거 패턴')),
      body: Loader<Json>(
        future: Api.similar(code),
        builder: (context, d) {
          final q = _path(d['query_path']);
          final matches = asList(d['matches']);
          final stats = asMap(d['stats']);
          final t = Theme.of(context).textTheme;
          return ListView(
            padding: const EdgeInsets.all(12),
            children: [
              Card(
                color: Colors.orange.withValues(alpha: 0.12),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text('⚠ ${d['disclaimer']}', style: t.bodySmall),
                ),
              ),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('현재 $name 최근 ${d['window']}일 (${pct(q.last * 100)})', style: t.titleSmall),
                    const SizedBox(height: 8),
                    Sparkline(values: q, height: 70, color: Colors.black87),
                  ]),
                ),
              ),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('비슷한 구간 ${d['sample_size']}개, 그 뒤 결과 분포', style: t.titleSmall),
                    const SizedBox(height: 8),
                    ...stats.entries.map((e) {
                      final s = asMap(e.value);
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 3),
                        child: Row(children: [
                          SizedBox(width: 48, child: Text(e.key.replaceAll('d', '일'))),
                          Expanded(child: Text('상승 비율 ${s['up_ratio']}%')),
                          Text('중앙값 ${pct(s['median'] as num)}  (${pct(s['p25'] as num)} ~ ${pct(s['p75'] as num)})',
                              style: t.bodySmall),
                        ]),
                      );
                    }),
                  ]),
                ),
              ),
              const SectionTitle('가장 비슷했던 구간'),
              ...matches.asMap().entries.map((e) {
                final m = e.value;
                final r20 = (m['ret20'] as num).toDouble();
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(children: [
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text('유사 패턴 ${e.key + 1} · ${m['name']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                          Text('${m['start']} ~ ${m['end']} · 유사도 ${m['similarity']}', style: t.bodySmall),
                          const SizedBox(height: 4),
                          Sparkline(values: _path(m['path']), height: 36),
                        ]),
                      ),
                      const SizedBox(width: 12),
                      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                        Text('20일 후', style: t.bodySmall),
                        Text(pct(r20),
                            style: TextStyle(
                                fontSize: 18, fontWeight: FontWeight.bold, color: r20 >= 0 ? upColor : downColor)),
                        Text('5일 ${pct(m['ret5'] as num)}', style: t.bodySmall),
                      ]),
                    ]),
                  ),
                );
              }),
            ],
          );
        },
      ),
    );
  }
}
