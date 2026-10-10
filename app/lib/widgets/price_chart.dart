import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart' show NumberFormat;

class PriceLevel {
  const PriceLevel(this.label, this.price, this.color);
  final String label;
  final double price;
  final Color color;
}

/// 이동평균선 (기간, 색) — 증권사 HTS 와 비슷한 색
const maLines = <(int, Color)>[
  (5, Color(0xFFE91E63)),
  (20, Color(0xFFFFA000)),
  (60, Color(0xFF43A047)),
  (120, Color(0xFF7E57C2)),
];

const _upC = Color(0xFFD32F2F);
const _downC = Color(0xFF1565C0);

/// 외부 라이브러리 없이 그리는 캔들 차트
///  - 위: 캔들 + 이동평균선(5·20·60·120) + 목표/손절 수평선
///  - 아래: 거래량
///  - 오른쪽 세로축: 가격 눈금
class PriceChart extends StatelessWidget {
  const PriceChart({
    super.key,
    required this.bars,
    this.levels = const [],
    this.slots,
    this.markIndex,
    this.showVolume = true,
    this.showMa = true,
  });
  final List<Map<String, dynamic>> bars;
  final List<PriceLevel> levels;
  final int? slots; // 가로 칸 수 (bars 보다 크면 오른쪽이 비어 있음 → 다른 차트와 같은 폭으로 비교)
  final int? markIndex; // 이 위치에 세로 점선 (예: 패턴 끝)
  final bool showVolume;
  final bool showMa;

  @override
  Widget build(BuildContext context) {
    final fg = Theme.of(context).colorScheme.onSurface;
    final chart = CustomPaint(
      painter: _ChartPainter(bars, levels, fg, slots, markIndex, showVolume, showMa),
      size: Size.infinite,
    );
    if (!showMa) return chart;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Wrap(spacing: 10, children: [
        for (final (n, c) in maLines)
          Row(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 12, height: 2, color: c),
            const SizedBox(width: 3),
            Text('$n일', style: TextStyle(fontSize: 10, color: fg.withValues(alpha: 0.75))),
          ]),
      ]),
      const SizedBox(height: 4),
      Expanded(child: chart),
    ]);
  }
}

final _fmt = NumberFormat('#,###');
final _fmt2 = NumberFormat('#,##0.##');

String _price(double v) => v.abs() >= 1000 ? _fmt.format(v) : _fmt2.format(v);

/// 거래량 짧게: 1234만 / 1.2억
String _vol(double v) {
  if (v >= 1e8) return '${(v / 1e8).toStringAsFixed(v >= 1e9 ? 0 : 1)}억';
  if (v >= 1e4) return '${_fmt.format((v / 1e4).round())}만';
  return _fmt.format(v);
}

/// 보기 좋은 눈금 간격 (1·2·2.5·5 × 10^n)
double _niceStep(double range, int target) {
  if (range <= 0) return 1;
  final raw = range / target;
  final mag = math.pow(10, (math.log(raw) / math.ln10).floor()).toDouble();
  for (final m in [1.0, 2.0, 2.5, 5.0, 10.0]) {
    if (raw <= m * mag) return m * mag;
  }
  return 10 * mag;
}

class _ChartPainter extends CustomPainter {
  _ChartPainter(this.bars, this.levels, this.fg, this.slots, this.markIndex, this.showVolume, this.showMa);
  final List<Map<String, dynamic>> bars;
  final List<PriceLevel> levels;
  final Color fg;
  final int? slots;
  final int? markIndex;
  final bool showVolume;
  final bool showMa;

  double _d(dynamic v) => (v as num).toDouble();

  /// 이평선 값: 서버가 계산해 둔 ma5… 를 쓰고, 없으면 받은 봉으로 직접 계산 (앞쪽은 비어 있음)
  List<double?> _ma(int n) {
    final closes = bars.map((b) => _d(b['close'])).toList();
    final out = List<double?>.filled(bars.length, null);
    double sum = 0;
    for (var i = 0; i < bars.length; i++) {
      sum += closes[i];
      if (i >= n) sum -= closes[i - n];
      final given = bars[i]['ma$n'];
      if (given is num) {
        out[i] = given.toDouble();
      } else if (i >= n - 1) {
        out[i] = sum / n;
      }
    }
    return out;
  }

  TextPainter _text(String s, Color c, {double size = 10, FontWeight? weight}) => TextPainter(
        text: TextSpan(text: s, style: TextStyle(color: c, fontSize: size, fontWeight: weight)),
        textDirection: TextDirection.ltr,
      )..layout();

  /// 오른쪽 축에 색 상자 + 글자 (현재가·목표·손절)
  void _tag(Canvas canvas, double x, double y, String s, Color bg) {
    final tp = _text(s, Colors.white, size: 10, weight: FontWeight.bold);
    final r = RRect.fromRectAndRadius(
        Rect.fromLTWH(x, y - tp.height / 2 - 1, tp.width + 6, tp.height + 2), const Radius.circular(3));
    canvas.drawRRect(r, Paint()..color = bg);
    tp.paint(canvas, Offset(x + 3, y - tp.height / 2));
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (bars.isEmpty) return;
    final axisW = levels.isEmpty ? 54.0 : 72.0; // 오른쪽 가격 축 (목표/손절 표시가 있으면 넓게)
    final w = size.width - axisW;
    final volH = showVolume ? size.height * 0.2 : 0.0;
    const gap = 6.0;
    final h = size.height - volH - (showVolume ? gap : 0); // 가격 영역 높이

    final mas = showMa ? [for (final (n, c) in maLines) (_ma(n), c)] : <(List<double?>, Color)>[];

    var lo = bars.map((b) => _d(b['low'])).reduce(math.min);
    var hi = bars.map((b) => _d(b['high'])).reduce(math.max);
    for (final (vals, _) in mas) {
      for (final v in vals) {
        if (v != null) {
          lo = math.min(lo, v);
          hi = math.max(hi, v);
        }
      }
    }
    for (final l in levels) {
      lo = math.min(lo, l.price);
      hi = math.max(hi, l.price);
    }
    if (hi - lo < 1e-9) {
      hi += 1;
      lo -= 1;
    }
    final pad = (hi - lo) * 0.05;
    lo -= pad;
    hi += pad;
    double y(double p) => h - (p - lo) / (hi - lo) * h;

    final cols = math.max(slots ?? bars.length, bars.length);
    final step = w / cols;
    final grid = Paint()
      ..color = fg.withValues(alpha: 0.10)
      ..strokeWidth = 1;
    final axisColor = fg.withValues(alpha: 0.6);

    // ---- 가격 눈금 (오른쪽 축) + 가로 격자. 목표/손절/현재가 표시와 겹치는 눈금 글자는 생략
    final last = _d(bars.last['close']);
    final tagYs = [...levels.map((l) => y(l.price)), y(last)];
    final st = _niceStep(hi - lo, 4);
    for (var v = (lo / st).ceil() * st; v <= hi; v += st) {
      final yy = y(v);
      canvas.drawLine(Offset(0, yy), Offset(w, yy), grid);
      if (tagYs.any((t) => (t - yy).abs() < 11)) continue;
      final tp = _text(_price(v), axisColor);
      tp.paint(canvas, Offset(w + 4, yy - tp.height / 2));
    }
    canvas.drawLine(Offset(w, 0), Offset(w, size.height), grid);

    // ---- 패턴 끝 세로 점선
    if (markIndex != null) {
      final mx = markIndex! * step;
      final mp = Paint()
        ..color = fg.withValues(alpha: 0.5)
        ..strokeWidth = 1;
      for (double yy = 0; yy < size.height; yy += 6) {
        canvas.drawLine(Offset(mx, yy), Offset(mx, math.min(yy + 3, size.height)), mp);
      }
    }

    // ---- 캔들
    final bodyW = math.max(1.0, step * 0.6);
    for (var i = 0; i < bars.length; i++) {
      final b = bars[i];
      final o = _d(b['open']), c = _d(b['close']);
      final paint = Paint()..color = c >= o ? _upC : _downC;
      final x = i * step + step / 2;
      canvas.drawLine(Offset(x, y(_d(b['high']))), Offset(x, y(_d(b['low']))), paint..strokeWidth = 1);
      final top = y(math.max(o, c)), bot = y(math.min(o, c));
      canvas.drawRect(Rect.fromLTRB(x - bodyW / 2, top, x + bodyW / 2, math.max(bot, top + 1)), paint);
    }

    // ---- 이동평균선
    for (final (vals, color) in mas) {
      final p = Paint()
        ..color = color
        ..strokeWidth = 1.2
        ..style = PaintingStyle.stroke;
      Path? path;
      for (var i = 0; i < vals.length; i++) {
        final v = vals[i];
        if (v == null) continue;
        final pt = Offset(i * step + step / 2, y(v));
        if (path == null) {
          path = Path()..moveTo(pt.dx, pt.dy);
        } else {
          path.lineTo(pt.dx, pt.dy);
        }
      }
      if (path != null) canvas.drawPath(path, p);
    }

    // ---- 목표/손절 수평선 + 오른쪽 축 표시
    for (final l in levels) {
      final yy = y(l.price);
      final p = Paint()
        ..color = l.color
        ..strokeWidth = 1;
      for (double x = 0; x < w; x += 6) {
        canvas.drawLine(Offset(x, yy), Offset(math.min(x + 3, w), yy), p);
      }
      _tag(canvas, w + 2, yy, '${l.label} ${_price(l.price)}', l.color.withValues(alpha: 0.9));
    }

    // ---- 마지막 종가 표시 (수평선에 '현재'가 따로 없으면)
    if (!levels.any((l) => (y(l.price) - y(last)).abs() < 11)) {
      final up = last >= _d(bars.last['open']);
      _tag(canvas, w + 2, y(last), _price(last), up ? _upC : _downC);
    }

    // ---- 거래량
    if (showVolume) {
      final top = h + gap;
      final vols = bars.map((b) => b['volume'] is num ? _d(b['volume']) : 0.0).toList();
      final vmax = vols.reduce(math.max);
      canvas.drawLine(Offset(0, top), Offset(w, top), grid);
      if (vmax > 0) {
        for (var i = 0; i < bars.length; i++) {
          final up = _d(bars[i]['close']) >= _d(bars[i]['open']);
          final bh = vols[i] / vmax * volH;
          final x = i * step + step / 2;
          canvas.drawRect(Rect.fromLTRB(x - bodyW / 2, size.height - bh, x + bodyW / 2, size.height),
              Paint()..color = (up ? _upC : _downC).withValues(alpha: 0.55));
        }
        final tp = _text(_vol(vmax), axisColor, size: 9);
        tp.paint(canvas, Offset(w + 4, top));
        final tp2 = _text('거래량', axisColor, size: 9);
        tp2.paint(canvas, Offset(w + 4, size.height - tp2.height));
      }
    }
  }

  @override
  bool shouldRepaint(covariant _ChartPainter old) =>
      old.bars != bars || old.levels != levels || old.slots != slots || old.markIndex != markIndex || old.fg != fg;
}

/// 확대·축소되는 캔들 차트 (종목 상세)
///  - 두 손가락 벌리기/오므리기: 보이는 기간을 줄이고/늘림 (최소 15일 ~ 받은 전체)
///  - 한 손가락 좌우 밀기: 과거 ↔ 최근 이동
///  - 두 번 탭 또는 [전체]: 처음 상태로
class ZoomableChart extends StatefulWidget {
  const ZoomableChart({super.key, required this.bars, this.levels = const [], this.height = 300});
  final List<Map<String, dynamic>> bars;
  final List<PriceLevel> levels;
  final double height;

  @override
  State<ZoomableChart> createState() => _ZoomableChartState();
}

class _ZoomableChartState extends State<ZoomableChart> {
  static const _minBars = 15;
  late int _n = widget.bars.length; // 보이는 봉 수
  int _end = 0; // 오른쪽 끝에서 몇 봉 과거로 옮겼는지 (0 = 최신)
  int _baseN = 0;
  double _drag = 0;

  int get _len => widget.bars.length;

  void _set(int n, int end) {
    final lo = math.min(_minBars, _len);
    final nn = n.clamp(lo, _len);
    setState(() {
      _n = nn;
      _end = end.clamp(0, _len - nn);
    });
  }

  @override
  void didUpdateWidget(covariant ZoomableChart old) {
    super.didUpdateWidget(old);
    if (old.bars.length != widget.bars.length) _set(widget.bars.length, 0);
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    if (_len == 0) return SizedBox(height: widget.height);
    final to = _len - _end;
    final view = widget.bars.sublist(math.max(0, to - _n), to);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Text(_end == 0 ? '최근 ${view.length}일' : '${view.length}일 · 최신에서 $_end일 전까지', style: t.bodySmall),
        const Spacer(),
        IconButton(
            visualDensity: VisualDensity.compact,
            tooltip: '확대',
            icon: const Icon(Icons.zoom_in, size: 20),
            onPressed: _n > _minBars ? () => _set((_n * 0.7).round(), _end) : null),
        IconButton(
            visualDensity: VisualDensity.compact,
            tooltip: '축소',
            icon: const Icon(Icons.zoom_out, size: 20),
            onPressed: _n < _len ? () => _set((_n / 0.7).round(), _end) : null),
        TextButton(onPressed: (_n < _len || _end > 0) ? () => _set(_len, 0) : null, child: const Text('전체')),
      ]),
      SizedBox(
        height: widget.height,
        child: LayoutBuilder(builder: (context, box) {
          final per = (box.maxWidth - 72) / math.max(_n, 1); // 봉 하나의 폭 (오른쪽 가격축 제외)
          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onDoubleTap: () => _set(_len, 0),
            onScaleStart: (_) {
              _baseN = _n;
              _drag = 0;
            },
            onScaleUpdate: (d) {
              if (d.pointerCount >= 2) {
                final s = d.horizontalScale.clamp(0.2, 5.0);
                _set((_baseN / s).round(), _end);
              } else {
                _drag += d.focalPointDelta.dx;
                final shift = (_drag / per).truncate(); // 오른쪽으로 밀면 과거로
                if (shift != 0) {
                  _drag -= shift * per;
                  _set(_n, _end + shift);
                }
              }
            },
            child: PriceChart(bars: view, levels: widget.levels),
          );
        }),
      ),
      Text('두 손가락으로 확대·축소 · 좌우로 밀어 기간 이동 · 두 번 탭하면 전체', style: t.bodySmall?.copyWith(color: Colors.grey)),
    ]);
  }
}
