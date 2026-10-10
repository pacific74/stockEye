import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
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
  late Future<(Json, Json)> _f = _load();
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
      appBar: AppBar(
          title: LogoTitle('${widget.name} 비슷한 과거 패턴'),
          actions: topActions(context, onRefresh: () => setState(() => _f = _load()))),
      body: Loader<(Json, Json)>(
        future: _f,
        builder: (context, data) {
          final d = data.$1;
          if (d['missing'] == true) {
            return _PatternRequest(code: widget.code, onDone: () => setState(() => _f = _load()));
          }
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
              // ① 지금 이 종목
              _ChartCard(
                title: widget.name,
                child: PriceChart(bars: curBars, slots: slots, markIndex: win),
              ),
              // ② 고른 과거 패턴
              if (m != null)
                _ChartCard(
                  title: '패턴 ${_sel + 1} · ${m['name']}  (유사도 ${m['similarity']})',
                  subtitle: '${m['start']} ~ ${m['end']}',
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
                      final hasRange = s['max_median'] != null;
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 5),
                        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          SizedBox(width: 44, child: Text(e.key.replaceAll('d', '일'), style: const TextStyle(fontWeight: FontWeight.w600))),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              // 그날 종가 기준
                              Text('종가  상승 ${s['up_ratio']}% · 중앙 ${pct(s['median'] as num)}'
                                  '  (${pct(s['p25'] as num)} ~ ${pct(s['p75'] as num)})',
                                  style: t.bodySmall),
                              // 그 기간 동안 장중 최고·최저 (중간에 급등·급락했다 빠진 것까지)
                              if (hasRange)
                                Text.rich(TextSpan(style: t.bodySmall, children: [
                                  const TextSpan(text: '기간 중  최고 '),
                                  TextSpan(text: pct(s['max_median'] as num?), style: const TextStyle(color: upColor)),
                                  const TextSpan(text: ' · 최저 '),
                                  TextSpan(text: pct(s['min_median'] as num?), style: const TextStyle(color: downColor)),
                                  TextSpan(text: '  · +10% 닿음 ${s['hit_up10']}% · −10% 닿음 ${s['hit_dn10']}%'),
                                ])),
                            ]),
                          ),
                        ]),
                      );
                    }),
                    if (stats.values.any((v) => asMap(v)['max_median'] != null))
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text('종가 = 그날 종가로 본 수익률 · 기간 중 = 그 기간 동안의 장중 최고가·최저가 (중앙값). '
                            '중간에 급등했다 밀린 경우도 보입니다. 장중 최고가에 팔 수 있었다는 뜻은 아닙니다.',
                            style: t.bodySmall?.copyWith(color: Colors.grey)),
                      ),
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
                            if (mm['sim_price'] != null)
                              Text('가격 ${mm['sim_price']} · 이평선 ${mm['sim_ma']} · 거래량 ${mm['sim_volume']}',
                                  style: t.bodySmall?.copyWith(color: Colors.grey)),
                            const SizedBox(height: 4),
                            Sparkline(values: [..._path(mm['path']), ..._path(mm['future'])], height: 32,
                                color: selected ? orange : null),
                            const SizedBox(height: 2),
                            Text('종가  5일 ${pct(mm['ret5'] as num?)} · 10일 ${pct(mm['ret10'] as num?)} · 20일 ${pct(mm['ret20'] as num?)}',
                                style: t.bodySmall),
                          ]),
                        ),
                        const SizedBox(width: 12),
                        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                          Text('20일 후', style: t.bodySmall),
                          Text(pct(r20),
                              style: TextStyle(
                                  fontSize: 18, fontWeight: FontWeight.bold, color: r20 >= 0 ? upColor : downColor)),
                          // 20일 동안 장중 최고·최저와 그날 (2일째 상한가 후 음봉 같은 경우도 보이게)
                          if (mm['max20'] != null)
                            Text('최고 ${pct(mm['max20'] as num?)} (${mm['max_day']}일째)',
                                style: t.bodySmall?.copyWith(color: upColor)),
                          if (mm['min20'] != null)
                            Text('최저 ${pct(mm['min20'] as num?)} (${mm['min_day']}일째)',
                                style: t.bodySmall?.copyWith(color: downColor)),
                          if (mm['max20'] == null) Text('5일 ${pct(mm['ret5'] as num?)}', style: t.bodySmall),
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
  const _ChartCard({required this.title, this.subtitle, required this.child, this.trailing, this.trailingColor});
  final String title;
  final String? subtitle;
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
          if (subtitle != null) Text(subtitle!, style: t.bodySmall),
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


/// 아직 패턴이 없는 종목: [패턴 찾기 요청] → 상태 표시 · 1분마다 자동 확인
class _PatternRequest extends StatefulWidget {
  const _PatternRequest({required this.code, required this.onDone});
  final String code;
  final VoidCallback onDone;

  @override
  State<_PatternRequest> createState() => _PatternRequestState();
}

class _PatternRequestState extends State<_PatternRequest> {
  Json _st = {};
  bool _busy = false;
  String? _err;
  Timer? _timer;
  int _polls = 0;

  @override
  void initState() {
    super.initState();
    _check();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  bool get _waiting => const ['queued', 'running'].contains(_st['status']);

  Future<void> _check() async {
    final st = await Api.patternStatus(widget.code);
    if (!mounted) return;
    setState(() => _st = st);
    if (st['status'] == 'done') {
      _timer?.cancel();
      widget.onDone();
    } else if (_waiting) {
      _timer ??= Timer.periodic(const Duration(minutes: 1), (_) {
        if (++_polls > 70) _timer?.cancel(); // 최대 약 1시간 10분
        _check();
      });
    }
  }

  Future<void> _request() async {
    setState(() {
      _busy = true;
      _err = null;
    });
    try {
      await Api.requestPattern(widget.code);
      await _check();
    } catch (e) {
      setState(() => _err = '$e'.replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _hm(dynamic v) {
    final d = DateTime.tryParse('${v ?? ''}')?.toLocal();
    return d == null ? '' : '${d.hour}:${d.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final instant = _st['instant'] == true;
    final when = instant
        ? '보통 3~6분 안에 결과가 나옵니다.'
        : '평일 9~21시 매시간 15분 · 장중 11시·14시 · 저녁 배치 때 처리됩니다 (최대 1시간 정도).';
    return ListView(padding: const EdgeInsets.all(16), children: [
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('이 종목은 아직 비슷한 과거 패턴을 계산하지 않았어요', style: t.titleSmall),
            const SizedBox(height: 6),
            const Text('매일 저녁 배치는 후보 메뉴의 모든 탭 종목과 보유종목만 미리 계산합니다. '
                '요청하면 이 종목도 계산해서, 다른 회원도 같이 볼 수 있게 저장합니다. '
                '요청한 종목은 며칠 동안 저녁 배치에서 계속 새로 계산됩니다.'),
            const SizedBox(height: 12),
            if (_waiting) ...[
              Row(children: [
                const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                const SizedBox(width: 10),
                Expanded(
                    child: Text('${_st['status'] == 'running' ? '계산 중' : '요청됨'} (${_hm(_st['created_at'])}) — $when')),
              ]),
              const SizedBox(height: 6),
              Text('이 화면을 열어 두면 1분마다 확인해서 끝나면 바로 보여줍니다.', style: t.bodySmall),
            ] else ...[
              if (_st['status'] == 'failed')
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text('지난 요청 실패: ${_st['message'] ?? ''}', style: const TextStyle(color: Colors.orange)),
                ),
              FilledButton.icon(
                icon: const Icon(Icons.timeline),
                label: Text(_busy ? '요청 중…' : '패턴 찾기'),
                onPressed: _busy ? null : _request,
              ),
            ],
            if (_err != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_err!, style: const TextStyle(color: Colors.red))),
            const SizedBox(height: 8),
            TextButton.icon(icon: const Icon(Icons.refresh), label: const Text('지금 다시 확인'), onPressed: _check),
          ]),
        ),
      ),
    ]);
  }
}
