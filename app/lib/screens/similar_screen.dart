import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/price_chart.dart';

/// 비슷한 과거 패턴: 지금 종목 차트 ↔ 고른 과거 패턴 차트(+그 뒤 20일)를 나란히 비교
class SimilarScreen extends StatefulWidget {
  const SimilarScreen({super.key, required this.code, required this.name});
  final String code;
  final String name;

  @override
  State<SimilarScreen> createState() => _SimilarScreenState();
}

class _SimilarScreenState extends State<SimilarScreen> {
  late final Future<(Json, Json)> _f = _load();
  final _scroll = ScrollController();
  int _sel = 0;

  Future<(Json, Json)> _load() async {
    final r = await Future.wait([Api.similar(widget.code), Api.stock(widget.code)]);
    return (r[0], r[1]);
  }

  List<double> _path(dynamic v) => (v as List? ?? []).map((e) => (e as num).toDouble()).toList();

  void _select(int i) {
    setState(() => _sel = i);
    _scroll.animateTo(0, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(title: LogoTitle('${widget.name} 비슷한 과거 패턴')),
      body: Loader<(Json, Json)>(
        future: _f,
        builder: (context, data) {
          final d = data.$1;
          final win = (d['window'] as num?)?.toInt() ?? 20;
          final q = _path(d['query_path']);
          final matches = asList(d['matches']);
          final stats = asMap(d['stats']);
          final cur = asList(data.$2['chart']);
          final curBars = cur.length > win ? cur.sublist(cur.length - win) : cur;
          final t = Theme.of(context).textTheme;
          final m = matches.isEmpty ? null : matches[math.min(_sel, matches.length - 1)];
          final mBars = m == null ? <Json>[] : asList(m['bars']);
          final fut = m == null ? <double>[] : _path(m['future']);
          final slots = win + (fut.isEmpty ? 20 : fut.length);
          const orange = Color(0xFFFF9800);
          return ListView(
            controller: _scroll,
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
            children: [
              Text('⚠ ${d['disclaimer']}', style: t.bodySmall?.copyWith(color: Colors.orange)),
              const SizedBox(height: 8),
              // ① 지금 이 종목
              _ChartCard(
                title: '지금 ${widget.name} · 최근 $win일',
                subtitle: '오른쪽 빈칸 = 앞으로의 $slots일 중 남은 기간 (아직 모름)',
                trailing: pct(q.isEmpty ? 0 : q.last * 100),
                child: PriceChart(bars: curBars, slots: slots, markIndex: win),
              ),
              // ② 고른 과거 패턴
              if (m != null)
                _ChartCard(
                  title: '패턴 ${_sel + 1} · ${m['name']}  (유사도 ${m['similarity']})',
                  subtitle: '${m['start']} ~ ${m['end']} · 점선 오른쪽 = 그 뒤 ${fut.length}일 실제 흐름',
                  trailing: '20일 후 ${pct(m['ret20'] as num?)}',
                  trailingColor: ((m['ret20'] as num?) ?? 0) >= 0 ? upColor : downColor,
                  child: mBars.isEmpty
                      ? const Center(child: Text('차트 데이터 없음 (다음 배치 때 생김)'))
                      : PriceChart(bars: mBars, slots: slots, markIndex: win),
                ),
              // ③ 수익률 겹쳐 보기
              if (m != null)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('수익률 겹쳐 보기 (시작일 = 0%)', style: t.titleSmall),
                      const SizedBox(height: 4),
                      Wrap(spacing: 12, children: [
                        _legend(Theme.of(context).colorScheme.primary, '지금 ${widget.name}'),
                        _legend(orange, '패턴 ${_sel + 1}'),
                        _legend(orange, '그 뒤', dashed: true),
                      ]),
                      const SizedBox(height: 8),
                      SizedBox(
                        height: 160,
                        child: CustomPaint(
                          size: Size.infinite,
                          painter: _ComparePainter(q, _path(m['path']), fut, Theme.of(context).colorScheme.primary,
                              orange, Theme.of(context).colorScheme.onSurface),
                        ),
                      ),
                    ]),
                  ),
                ),
              // ④ 결과 분포
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('비슷한 구간 ${d['sample_size']}개, 그 뒤 결과 분포', style: t.titleSmall),
                    const SizedBox(height: 6),
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
              const SectionTitle('비슷했던 구간 (눌러서 위에서 비교)'),
              ...matches.asMap().entries.map((e) {
                final mm = e.value;
                final r20 = ((mm['ret20'] as num?) ?? 0).toDouble();
                final selected = e.key == _sel;
                return Card(
                  shape: selected
                      ? RoundedRectangleBorder(
                          side: const BorderSide(color: orange, width: 2), borderRadius: BorderRadius.circular(12))
                      : null,
                  child: InkWell(
                    borderRadius: BorderRadius.circular(12),
                    onTap: () => _select(e.key),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Row(children: [
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text('패턴 ${e.key + 1} · ${mm['name']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                            Text('${mm['start']} ~ ${mm['end']} · 유사도 ${mm['similarity']}', style: t.bodySmall),
                            const SizedBox(height: 4),
                            Sparkline(values: [..._path(mm['path']), ..._path(mm['future'])], height: 32,
                                color: selected ? orange : null),
                          ]),
                        ),
                        const SizedBox(width: 12),
                        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                          Text('20일 후', style: t.bodySmall),
                          Text(pct(r20),
                              style: TextStyle(
                                  fontSize: 18, fontWeight: FontWeight.bold, color: r20 >= 0 ? upColor : downColor)),
                          Text('5일 ${pct(mm['ret5'] as num?)}', style: t.bodySmall),
                        ]),
                      ]),
                    ),
                  ),
                );
              }),
            ],
          );
        },
      ),
    );
  }

  Widget _legend(Color c, String label, {bool dashed = false}) => Row(mainAxisSize: MainAxisSize.min, children: [
        Container(width: 16, height: 3, color: dashed ? c.withValues(alpha: 0.5) : c),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(fontSize: 12)),
      ]);
}

class _ChartCard extends StatelessWidget {
  const _ChartCard(
      {required this.title, required this.subtitle, required this.child, this.trailing, this.trailingColor});
  final String title;
  final String subtitle;
  final Widget child;
  final String? trailing;
  final Color? trailingColor;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(title, style: t.titleSmall)),
            if (trailing != null)
              Text(trailing!, style: TextStyle(fontWeight: FontWeight.bold, color: trailingColor)),
          ]),
          Text(subtitle, style: t.bodySmall),
          const SizedBox(height: 8),
          SizedBox(height: 230, child: child),
        ]),
      ),
    );
  }
}

/// 지금(실선) vs 과거 패턴(주황 실선) + 그 뒤(주황 점선), 시작일 = 0%
class _ComparePainter extends CustomPainter {
  _ComparePainter(this.q, this.p, this.f, this.cq, this.cp, this.fg);
  final List<double> q, p, f;
  final Color cq, cp, fg;

  @override
  void paint(Canvas canvas, Size size) {
    final cur = [0.0, ...q];
    final pat = [0.0, ...p];
    final all = [...cur, ...pat, ...f];
    if (all.length < 2) return;
    const rightPad = 44.0;
    final w = size.width - rightPad, h = size.height;
    var lo = all.reduce(math.min), hi = all.reduce(math.max);
    final pad = (hi - lo) * 0.08 + 1e-6;
    lo -= pad;
    hi += pad;
    final n = pat.length + f.length; // 전체 칸
    double x(int i) => i / math.max(1, n - 1) * w;
    double y(double v) => h - (v - lo) / (hi - lo) * h;

    final grid = Paint()
      ..color = fg.withValues(alpha: 0.25)
      ..strokeWidth = 1;
    canvas.drawLine(Offset(0, y(0)), Offset(w, y(0)), grid); // 0% 기준선
    final mx = x(pat.length - 1);
    for (double yy = 0; yy < h; yy += 6) {
      canvas.drawLine(Offset(mx, yy), Offset(mx, math.min(yy + 3, h)), grid); // 패턴 끝
    }

    void line(List<double> v, int offset, Color c, {bool dashed = false, double width = 2}) {
      final paint = Paint()
        ..color = c
        ..strokeWidth = width
        ..style = PaintingStyle.stroke;
      for (var i = 1; i < v.length; i++) {
        if (dashed && i.isOdd) continue;
        canvas.drawLine(Offset(x(offset + i - 1), y(v[i - 1])), Offset(x(offset + i), y(v[i])), paint);
      }
    }

    line(pat, 0, cp);
    if (f.isNotEmpty) line([pat.last, ...f], pat.length - 1, cp.withValues(alpha: 0.7), dashed: true);
    line(cur, 0, cq, width: 2.5);

    void label(double v, Color c) {
      final tp = TextPainter(
        text: TextSpan(text: '${(v * 100).toStringAsFixed(1)}%', style: TextStyle(color: c, fontSize: 10)),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(w + 4, y(v) - tp.height / 2));
    }

    label(cur.last, cq);
    if (f.isNotEmpty) label(f.last, cp);
  }

  @override
  bool shouldRepaint(covariant _ComparePainter old) => old.p != p || old.q != q || old.f != f;
}
