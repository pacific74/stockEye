import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../screens/stock_detail_screen.dart';

/// Future 를 받아 로딩/에러/결과를 그려주는 공통 위젯
class Loader<T> extends StatelessWidget {
  const Loader({super.key, required this.future, required this.builder, this.onRetry});
  final Future<T> future;
  final Widget Function(BuildContext, T) builder;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) return ErrorView(message: '${snap.error}', onRetry: onRetry);
        return builder(context, snap.data as T);
      },
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, this.onRetry});
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.cloud_off, size: 48),
          const SizedBox(height: 12),
          Text('불러오지 못했습니다\n($apiBase)', textAlign: TextAlign.center),
          const SizedBox(height: 8),
          Text(message.replaceFirst('Exception: ', ''),
              style: Theme.of(context).textTheme.bodySmall, textAlign: TextAlign.center),
          if (onRetry != null) ...[
            const SizedBox(height: 16),
            FilledButton(onPressed: onRetry, child: const Text('다시 시도')),
          ],
        ]),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 16, 4, 8),
        child: Row(children: [
          Expanded(child: Text(text, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold))),
          if (trailing != null) trailing!,
        ]),
      );
}

const strategyLabels = {
  'overall': '상승 후보',
  'A': '돌파',
  'B': '눌림목',
  'C': '급등 초기',
  'D': '수급',
  'E': '저평가 전환',
};

class CandidateTile extends StatelessWidget {
  const CandidateTile({super.key, required this.c, this.showStrategyScore = false});
  final Json c;
  final bool showStrategyScore;

  @override
  Widget build(BuildContext context) {
    final plan = asMap(c['plan']);
    final verdict = plan['verdict'] as String;
    final score = (c['score'] as num).toDouble();
    final ss = c['strategy_score'] as num?;
    final tags = List<String>.from(c['tags'] as List? ?? []);
    final theme = c['theme'] as String?;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        leading: CircleAvatar(child: Text('${c['rank']}')),
        title: Text('${c['name']}', style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${stars(c['stars'] as int)}  ${won(plan['price'] as num)}'),
          if (tags.isNotEmpty || theme != null)
            Wrap(spacing: 4, children: [
              if (theme != null) _chip(theme, Colors.indigo),
              ...tags.map((t) => _chip(strategyLabels[t] ?? t, Colors.teal)),
            ]),
        ]),
        isThreeLine: tags.isNotEmpty || theme != null,
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(showStrategyScore && ss != null ? '${ss.toStringAsFixed(0)}점' : '${score.toStringAsFixed(0)}점',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            Text(verdict, style: TextStyle(color: verdictColor(verdict), fontSize: 12)),
          ],
        ),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => StockDetailScreen(code: c['code'] as String, name: c['name'] as String))),
      ),
    );
  }

  Widget _chip(String t, Color color) => Container(
        margin: const EdgeInsets.only(top: 4),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(6)),
        child: Text(t, style: TextStyle(fontSize: 11, color: color)),
      );
}

/// 작은 선 그래프 (패턴 비교용). values 는 0 기준 누적 수익률 (예: 0.05 = +5%)
class Sparkline extends StatelessWidget {
  const Sparkline({super.key, required this.values, this.color, this.height = 40, this.width});
  final List<double> values;
  final Color? color;
  final double height;
  final double? width;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: height,
        width: width,
        child: CustomPaint(painter: _SparkPainter(values, color ?? Theme.of(context).colorScheme.primary)),
      );
}

class _SparkPainter extends CustomPainter {
  _SparkPainter(this.v, this.color);
  final List<double> v;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    if (v.length < 2) return;
    final all = [0.0, ...v];
    final lo = all.reduce(math.min), hi = all.reduce(math.max);
    final range = (hi - lo).abs() < 1e-9 ? 1.0 : hi - lo;
    double y(double val) => size.height - (val - lo) / range * size.height;
    final path = Path()..moveTo(0, y(0));
    for (var i = 0; i < v.length; i++) {
      path.lineTo((i + 1) / v.length * size.width, y(v[i]));
    }
    canvas.drawLine(Offset(0, y(0)), Offset(size.width, y(0)), Paint()..color = Colors.grey.withValues(alpha: 0.4));
    canvas.drawPath(
        path,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.6);
  }

  @override
  bool shouldRepaint(covariant _SparkPainter old) => old.v != v;
}
