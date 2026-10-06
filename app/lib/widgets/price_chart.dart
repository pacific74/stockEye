import 'dart:math' as math;

import 'package:flutter/material.dart';

class PriceLevel {
  const PriceLevel(this.label, this.price, this.color);
  final String label;
  final double price;
  final Color color;
}

/// 외부 차트 라이브러리 없이 그리는 간단한 캔들 차트 + 목표/손절 수평선.
class PriceChart extends StatelessWidget {
  const PriceChart({super.key, required this.bars, this.levels = const []});
  final List<Map<String, dynamic>> bars;
  final List<PriceLevel> levels;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _ChartPainter(bars, levels, Theme.of(context).colorScheme.onSurface),
      size: Size.infinite,
    );
  }
}

class _ChartPainter extends CustomPainter {
  _ChartPainter(this.bars, this.levels, this.fg);
  final List<Map<String, dynamic>> bars;
  final List<PriceLevel> levels;
  final Color fg;

  double _d(dynamic v) => (v as num).toDouble();

  @override
  void paint(Canvas canvas, Size size) {
    if (bars.isEmpty) return;
    const rightPad = 56.0;
    final w = size.width - rightPad;
    final h = size.height;
    var lo = bars.map((b) => _d(b['low'])).reduce(math.min);
    var hi = bars.map((b) => _d(b['high'])).reduce(math.max);
    for (final l in levels) {
      lo = math.min(lo, l.price);
      hi = math.max(hi, l.price);
    }
    final pad = (hi - lo) * 0.05;
    lo -= pad;
    hi += pad;
    double y(double p) => h - (p - lo) / (hi - lo) * h;

    final step = w / bars.length;
    final bodyW = math.max(1.0, step * 0.6);
    for (var i = 0; i < bars.length; i++) {
      final b = bars[i];
      final o = _d(b['open']), c = _d(b['close']);
      final up = c >= o;
      final paint = Paint()..color = up ? const Color(0xFFD32F2F) : const Color(0xFF1565C0);
      final x = i * step + step / 2;
      canvas.drawLine(Offset(x, y(_d(b['high']))), Offset(x, y(_d(b['low']))), paint..strokeWidth = 1);
      final top = y(math.max(o, c)), bot = y(math.min(o, c));
      canvas.drawRect(Rect.fromLTRB(x - bodyW / 2, top, x + bodyW / 2, math.max(bot, top + 1)), paint);
    }

    for (final l in levels) {
      final yy = y(l.price);
      final p = Paint()
        ..color = l.color
        ..strokeWidth = 1;
      // 점선
      for (double x = 0; x < w; x += 6) {
        canvas.drawLine(Offset(x, yy), Offset(math.min(x + 3, w), yy), p);
      }
      final tp = TextPainter(
        text: TextSpan(text: l.label, style: TextStyle(color: l.color, fontSize: 11)),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(w + 4, yy - tp.height / 2));
    }
  }

  @override
  bool shouldRepaint(covariant _ChartPainter old) => old.bars != bars || old.levels != levels;
}
