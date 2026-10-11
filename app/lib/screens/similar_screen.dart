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

  void _select(int i) => setState(() => _sel = i);

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
              // 상위 10개 '그 뒤' 흐름 설명
              if (d['comment'] != null)
                Card(
                  color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      const Icon(Icons.insights, size: 18),
                      const SizedBox(width: 8),
                      Expanded(child: Text('${d['comment']}', style: const TextStyle(height: 1.5))),
                    ]),
                  ),
                ),
              // 차트 비교 (왼쪽) + 패턴 1~10 버튼 (오른쪽 세로)
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    // ① 지금 이 종목
                    _ChartCard(
                      title: widget.name,
                      child: PriceChart(bars: curBars, slots: slots, markIndex: win),
                    ),
                    // ② 고른 과거 패턴 — 차트 위에 패턴 정보(기간·유사도·세부 유사도, 20일 후·최고·최저)까지 한 카드로
                    if (m != null)
                      Builder(builder: (context) {
                        final r20 = ((m['ret20'] as num?) ?? 0).toDouble();
                        return _ChartCard(
                          title: '패턴 ${_sel + 1} · ${m['name']}',
                          subtitle: '${m['start']} ~ ${m['end']} · 유사도 ${m['similarity']}',
                          info: m['sim_price'] == null
                              ? null
                              : '가격 ${m['sim_price']} · 이평선 ${m['sim_ma']} · 거래량 ${m['sim_volume']}',
                          border: orange,
                          right: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                            Text('20일 후', style: t.bodySmall),
                            Text(pct(r20),
                                style: TextStyle(
                                    fontSize: 18, fontWeight: FontWeight.bold, color: r20 >= 0 ? upColor : downColor)),
                            // 20일 동안 장중 최고·최저와 그날
                            if (m['max20'] != null)
                              Text('최고 ${pct(m['max20'] as num?)} (${m['max_day']}일째)',
                                  style: t.bodySmall?.copyWith(color: upColor)),
                            if (m['min20'] != null)
                              Text('최저 ${pct(m['min20'] as num?)} (${m['min_day']}일째)',
                                  style: t.bodySmall?.copyWith(color: downColor)),
                          ]),
                          child: mBars.isEmpty
                              ? const Center(child: Text('차트 데이터 없음 (다음 배치 때 생김)'))
                              : PriceChart(bars: mBars, slots: slots, markIndex: win),
                        );
                      }),
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
                  ]),
                ),
                const SizedBox(width: 6),
                Column(children: [
                  for (var i = 0; i < matches.length; i++)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: _PatternButton(
                        n: i + 1,
                        ret: (matches[i]['ret20'] as num?)?.toDouble(),
                        selected: i == _sel,
                        onTap: () => _select(i),
                      ),
                    ),
                ]),
              ]),
              // 그 뒤 20일 — 유사도 그룹별 (맨 아래)
              if (asList(d['groups']).isNotEmpty)
                _GroupCard(d: d)
              else
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
      {required this.title, this.subtitle, required this.child, this.trailing, this.trailingColor, this.info, this.right, this.border});
  final String title;
  final String? subtitle;
  final String? info; // 회색 한 줄 (세부 유사도)
  final Widget child;
  final String? trailing;
  final Color? trailingColor;
  final Widget? right; // 오른쪽 위 (20일 후 · 최고 · 최저)
  final Color? border;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      shape: border == null
          ? null
          : RoundedRectangleBorder(side: BorderSide(color: border!, width: 2), borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: t.titleSmall),
                if (subtitle != null) Text(subtitle!, style: t.bodySmall),
                if (info != null) Text(info!, style: t.bodySmall?.copyWith(color: Colors.grey)),
              ]),
            ),
            if (trailing != null)
              Text(trailing!, style: TextStyle(fontWeight: FontWeight.bold, color: trailingColor)),
            if (right != null) right!,
          ]),
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


/// 그 뒤 20일 — 유사도 그룹별 대표 봉 차트 + 요약
class _GroupCard extends StatelessWidget {
  const _GroupCard({required this.d});
  final Json d;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final gs = asList(d['groups']);
    final low = (asList(d['matches']).isEmpty ? 0 : ((asList(d['matches']).first['similarity'] as num?) ?? 0)) < 50;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('비슷한 구간 ${d['sample_size']}개', style: t.titleSmall),
          if (low)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: InfoBox('⚠ 많이 비슷한 구간이 없어요 (최고 유사도 50 미만) — 참고만', color: Colors.orange, fill: true),
            ),
          // 상위 20% · 중위 30% · 하위 50% 모두 펼쳐서
          for (final g in gs) _group(context, g),
        ]),
      ),
    );
  }

  Widget _group(BuildContext context, Json g) {
    final t = Theme.of(context).textTheme;
    final candles = (g['candles'] as List? ?? const []).map((e) => (e as List).map((x) => (x as num).toDouble()).toList()).toList();
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text('${g['name']}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(width: 10),
          Text('유사도 ${g['sim_min']} ~ ${g['sim_max']}', style: t.titleSmall?.copyWith(color: Colors.grey)),
        ]),
        const SizedBox(height: 6),
        SizedBox(
          height: 180,
          child: CustomPaint(size: Size.infinite, painter: _GroupCandlePainter(candles, Theme.of(context).colorScheme.onSurface)),
        ),
        const SizedBox(height: 6),
        infoBoxes([
          InfoBox('20일째 종가 중앙 ${pct(g['close_median'] as num?)}',
              color: ((g['close_median'] as num?) ?? 0) >= 0 ? upColor : downColor, bold: true),
          InfoBox('오른 채 끝남 ${g['up_ratio']}%'),
          InfoBox('기간 중 최고 ${pct(g['max_median'] as num?)} (${g['max_day']}일째쯤)', color: upColor),
          InfoBox('최저 ${pct(g['min_median'] as num?)} (${g['min_day']}일째쯤)', color: downColor),
          InfoBox('+10%이상 ${g['hit_up10']}%', color: upColor),
          InfoBox('-10%이하 ${g['hit_dn10']}%', color: downColor),
        ]),
      ]),
    );
  }
}

class _GroupCandlePainter extends CustomPainter {
  _GroupCandlePainter(this.c, this.fg);
  final List<List<double>> c; // [시가, 고가, 저가, 종가] %
  final Color fg;

  @override
  void paint(Canvas canvas, Size size) {
    if (c.isEmpty) return;
    const left = 40.0, bottom = 16.0;
    final w = size.width - left, h = size.height - bottom;
    var hi = 0.0, lo = 0.0;
    for (final k in c) {
      hi = math.max(hi, k[1]);
      lo = math.min(lo, k[2]);
    }
    final pad = (hi - lo) * 0.08 + 0.5;
    hi += pad;
    lo -= pad;
    double y(double v) => (hi - v) / (hi - lo) * h;
    final grid = Paint()
      ..color = fg.withValues(alpha: 0.12)
      ..strokeWidth = 1;
    final tp = TextPainter(textDirection: TextDirection.ltr);
    final step = (hi - lo) > 30 ? 10.0 : (hi - lo) > 12 ? 5.0 : 2.0;
    for (var v = (lo / step).ceil() * step; v <= hi; v += step) {
      canvas.drawLine(Offset(left, y(v)), Offset(size.width, y(v)), v == 0 ? (Paint()..color = fg.withValues(alpha: 0.45)) : grid);
      tp.text = TextSpan(text: '${v > 0 ? '+' : ''}${v.toStringAsFixed(0)}%', style: TextStyle(fontSize: 9, color: fg.withValues(alpha: 0.6)));
      tp.layout();
      tp.paint(canvas, Offset(0, y(v) - tp.height / 2));
    }
    final cw = w / c.length;
    for (var i = 0; i < c.length; i++) {
      final k = c[i];
      final x = left + cw * (i + 0.5);
      final up = k[3] >= k[0];
      final col = up ? upColor : downColor;
      final p = Paint()
        ..color = col
        ..strokeWidth = 1;
      canvas.drawLine(Offset(x, y(k[1])), Offset(x, y(k[2])), p);
      final top = y(math.max(k[0], k[3])), bot = y(math.min(k[0], k[3]));
      canvas.drawRect(Rect.fromLTRB(x - cw * 0.32, top, x + cw * 0.32, math.max(bot, top + 1)), p..style = PaintingStyle.fill);
      if (i == 0 || (i + 1) % 5 == 0) {
        tp.text = TextSpan(text: '${i + 1}일', style: TextStyle(fontSize: 9, color: fg.withValues(alpha: 0.6)));
        tp.layout();
        tp.paint(canvas, Offset(x - tp.width / 2, h + 3));
      }
    }
  }

  @override
  bool shouldRepaint(covariant _GroupCandlePainter old) => old.c != c;
}


/// 오른쪽 세로 패턴 버튼: 번호 + 20일 후 색 (빨강 = 올랐음, 파랑 = 내렸음)
class _PatternButton extends StatelessWidget {
  const _PatternButton({required this.n, required this.ret, required this.selected, required this.onTap});
  final int n;
  final double? ret;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    const orange = Color(0xFFFF9800);
    final col = (ret ?? 0) >= 0 ? upColor : downColor;
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: onTap,
      child: Container(
        width: 40,
        padding: const EdgeInsets.symmetric(vertical: 6),
        decoration: BoxDecoration(
          color: selected ? orange.withValues(alpha: 0.2) : null,
          border: Border.all(color: selected ? orange : Colors.grey.withValues(alpha: 0.4), width: selected ? 2 : 1),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(children: [
          Text('$n', style: TextStyle(fontWeight: FontWeight.bold, color: selected ? orange : null)),
          if (ret != null) Text('${ret! >= 0 ? '+' : ''}${ret!.toStringAsFixed(0)}%', style: TextStyle(fontSize: 9, color: col)),
        ]),
      ),
    );
  }
}
