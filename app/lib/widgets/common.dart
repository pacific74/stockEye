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

/// 시장 표시: 코스피 / 코스닥
class MarketBadge extends StatelessWidget {
  const MarketBadge(this.market, {super.key});
  final String? market;

  @override
  Widget build(BuildContext context) {
    final m = market;
    if (m == null || m.isEmpty) return const SizedBox.shrink();
    final kospi = m == 'KOSPI';
    final label = kospi ? '코스피' : (m == 'KOSDAQ' ? '코스닥' : m);
    final color = kospi ? Colors.blueGrey : Colors.purple;
    return Container(
      margin: const EdgeInsets.only(left: 4),
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 0),
      decoration: BoxDecoration(border: Border.all(color: color.withValues(alpha: 0.6)), borderRadius: BorderRadius.circular(4)),
      child: Text(label, style: TextStyle(fontSize: 10, color: color.shade200)),
    );
  }
}

/// 종목명 + 코스피/코스닥 + (점수)
class StockName extends StatelessWidget {
  const StockName(this.name, {super.key, this.market, this.score, this.style});
  final String name;
  final String? market;
  final num? score;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) => Row(children: [
        Flexible(
            child: Text(name,
                overflow: TextOverflow.ellipsis, style: style ?? const TextStyle(fontWeight: FontWeight.w600))),
        MarketBadge(market),
        if (score != null) ...[const SizedBox(width: 6), ScoreBadge(score)],
      ]);
}

/// 점수 배지 (V3B 60점 만점) — 45↑ 빨강 / 38↑ 주황 / 30↑ 청록 / 그 아래 회색
class ScoreBadge extends StatelessWidget {
  const ScoreBadge(this.score, {super.key, this.label});
  final num? score;
  final String? label; // 예: '오늘'

  @override
  Widget build(BuildContext context) {
    if (score == null) return const SizedBox.shrink();
    final v = score!.toDouble();
    final color = v >= 45 ? upColor : (v >= 38 ? Colors.orange : (v >= 30 ? Colors.teal : Colors.grey));
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
          color: color.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withValues(alpha: 0.5))),
      child: Text('${label == null ? '' : '$label '}${v.toStringAsFixed(0)}점',
          style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.bold)),
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
  'v3': 'V3 기준',
  'now': '지금 매수구간',
  'signal': '매수 신호',
  'buy': '강력·매수 후보',
  'watch': '관심',
  'overall': '전체 후보',
  // (예전 V1 전략 — 과거 기록 표시용)
  'A': '돌파',
  'B': '눌림목',
  'C': '급등 초기',
  'D': '수급',
  'E': '저평가 전환',
};

class CandidateTile extends StatelessWidget {
  const CandidateTile({super.key, required this.c, this.showStrategyScore = false, this.rank, this.bigStrategy = false});
  final Json c;
  final bool showStrategyScore; // 전략 점수도 함께 표시
  final int? rank; // 화면 정렬 순서대로 매긴 순위 (없으면 원래 순위)
  final bool bigStrategy; // 큰 글씨를 전략 점수로

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
        leading: CircleAvatar(child: Text('${rank ?? c['rank']}')),
        title: StockName('${c['name']}', market: c['market'] as String?),
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
            Text(bigStrategy && ss != null ? '${ss.toStringAsFixed(0)}점' : '${score.toStringAsFixed(0)}점',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            if (showStrategyScore && ss != null)
              Text(bigStrategy ? '종합 ${score.toStringAsFixed(0)}' : '전략 ${ss.toStringAsFixed(0)}',
                  style: const TextStyle(fontSize: 11, color: Colors.grey)),
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
