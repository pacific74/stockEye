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

/// 항목 하나를 네모 테두리로 (점 '·' 대신 구분) — 예: [목표 +7.0%] [손절 -7.7%] [손익비 1:0.9]
class InfoBox extends StatelessWidget {
  const InfoBox(this.text, {super.key, this.color, this.bold = false, this.fill = false});
  final String text;
  final Color? color;
  final bool bold;
  final bool fill; // 옅은 배경색까지 (경고 등)

  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
      decoration: BoxDecoration(
        color: fill ? c.withValues(alpha: 0.12) : null,
        border: Border.all(color: c.withValues(alpha: 0.55)),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(text, style: TextStyle(fontSize: 11, color: c, fontWeight: bold ? FontWeight.w600 : null)),
    );
  }
}

/// 네모 박스 여러 개 한 줄 (넘치면 다음 줄)
Widget infoBoxes(List<Widget> boxes) => Wrap(spacing: 4, runSpacing: 3, children: boxes);

/// 종목명 + 현재가·등락률 한 줄 — 좁은 화면(폰)에서는 종목명 아래 줄로 현재가를 내림 (이름이 잘리지 않게)
class NameQuoteRow extends StatelessWidget {
  const NameQuoteRow({super.key, required this.name, required this.quote});
  final Widget name;
  final Widget quote;

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, box) {
        if (box.maxWidth < 520) {
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            name,
            Padding(padding: const EdgeInsets.only(top: 2), child: quote),
          ]);
        }
        return Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Expanded(child: name),
          const SizedBox(width: 6),
          quote,
        ]);
      });
}

/// 점수 옆 [당일] — 오늘 장중에 새로 추천된 종목 표시
class TodayTag extends StatelessWidget {
  const TodayTag({super.key});

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(left: 4),
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
        decoration: BoxDecoration(
            color: Colors.purple.withValues(alpha: 0.16),
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: Colors.purple.shade200.withValues(alpha: 0.7))),
        child: Text('[당일]', style: TextStyle(color: Colors.purple.shade200, fontSize: 11, fontWeight: FontWeight.bold)),
      );
}

/// 종목명 + 코스피/코스닥 + (점수)
class StockName extends StatelessWidget {
  const StockName(this.name, {super.key, this.market, this.score, this.style, this.scoreDigits = 0, this.today = false});
  final String name;
  final String? market;
  final num? score;
  final TextStyle? style;
  final int scoreDigits; // 점수 소수 자리 (관심 탭 점수는 1자리)
  final bool today; // 오늘 장중에 새로 추천된 종목 (전날 저녁 목록에 없었음) → 점수 옆 [당일]

  @override
  Widget build(BuildContext context) => Row(children: [
        Flexible(
            child: Text(name,
                overflow: TextOverflow.ellipsis, style: style ?? const TextStyle(fontWeight: FontWeight.w600))),
        MarketBadge(market),
        if (score != null) ...[const SizedBox(width: 6), ScoreBadge(score, digits: scoreDigits)],
        if (today) const TodayTag(),
      ]);
}

/// 종목 한 줄 정보: [코스피/코스닥] [업종 · 테마] [시총] [외인·기관 5일 순매수] — 당일매매·메인·관심 카드의 종목명 바로 아래 (2026-10-14)
class StockInfoLine extends StatelessWidget {
  const StockInfoLine(this.code, {super.key, this.sectorIdx = true});
  final String code;
  final bool sectorIdx; // 업종 옆에 업종지수(오늘 등락 · 1시간마다) 칩 — 당일매매·메인·추천 모두 (2026-10-15)

  static String flow(num eok) {
    final a = eok.abs();
    final s = a >= 10000 ? '${(a / 10000).toStringAsFixed(1)}조' : (a >= 100 ? '${a.round()}억' : '${a.toStringAsFixed(1)}억');
    return eok > 0 ? '+$s 매수' : (eok < 0 ? '−$s 매도' : '0');
  }

  static Color flowColor(num eok) => eok > 0 ? upColor : (eok < 0 ? downColor : Colors.grey);

  static String cap(num? eok) {
    if (eok == null || eok <= 0) return '';
    if (eok >= 10000) return '시총 ${(eok / 10000).toStringAsFixed(eok >= 100000 ? 0 : 1)}조';
    return '시총 ${eok.round()}억';
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<List<Map<String, dynamic>>>(
        future: Future.wait<Map<String, dynamic>>([Api.stockInfo(), Api.flowLive(), if (sectorIdx) Api.sectorIdx()]),
        builder: (context, snap) {
          final r = snap.data?[0][code] as List?;
          final t = snap.data?[1][code] as List?; // 당일 잠정 [외인 억, 기관 억, '11:20']
          if (r == null || r.length < 4) return const SizedBox.shrink();
          final m = '${r[0]}', sec = '${r[1]}', th = '${r[2]}';
          final st = Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 11, color: Colors.grey.shade400);
          Widget chip(String s, {Color? c}) => Container(
                margin: const EdgeInsets.only(right: 4, top: 2),
                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                decoration: BoxDecoration(
                    border: Border.all(color: (c ?? Colors.grey).withValues(alpha: 0.5)), borderRadius: BorderRadius.circular(4)),
                child: Text(s, style: st?.copyWith(color: c)),
              );
          return Wrap(children: [
            if (m.isNotEmpty)
              chip(m == 'KOSPI' ? '코스피' : (m == 'KOSDAQ' ? '코스닥' : m),
                  c: m == 'KOSPI' ? Colors.blueGrey.shade200 : Colors.purple.shade200),
            if (sec.isNotEmpty || th.isNotEmpty) chip([if (sec.isNotEmpty) sec, if (th.isNotEmpty) th].join(' · ')),
            // 업종지수: 그 업종 전체 시가총액 가중 오늘 등락 (09:10 부터 1시간마다)
            if (sectorIdx && sec.isNotEmpty && snap.data!.length > 2 && asMap(snap.data![2]['map'])[sec] is num)
              () {
                final v = asMap(snap.data![2]['map'])[sec] as num;
                return chip('업종지수 ${v > 0 ? '+' : (v < 0 ? '−' : '')}${v.abs().toStringAsFixed(2)}% (${snap.data![2]['time']})',
                    c: v > 0 ? upColor : (v < 0 ? downColor : null));
              }(),
            if (cap(r[3] as num?).isNotEmpty) chip(cap(r[3] as num?)),
            // 최근 5거래일 순매수 (외국인·기관, 억원) — 매수 빨강 · 매도 파랑
            if (r.length > 4 && r[4] is num) chip('외인 5일 ${flow(r[4] as num)}', c: flowColor(r[4] as num)),
            if (r.length > 5 && r[5] is num) chip('기관 5일 ${flow(r[5] as num)}', c: flowColor(r[5] as num)),
            // 오늘 장중 잠정 (증권사 추정 · 09:30/10:00/11:20/13:20/14:30 갱신) — 마감 후 확정치와 다를 수 있음
            if (t != null && t.length > 2 && t[0] is num) chip('외인 오늘 ${flow(t[0] as num)}', c: flowColor(t[0] as num)),
            if (t != null && t.length > 2 && t[1] is num)
              chip('기관 오늘 ${flow(t[1] as num)} · 잠정 ${t[2]}', c: flowColor(t[1] as num)),
          ]);
        },
      );
}

/// 오늘 등락률 배지 (현재가 옆): ▲ 5.89 빨강 / ▼ 1.20 파랑 / 0.00 회색 — 전일 종가 대비
class ChgBadge extends StatelessWidget {
  const ChgBadge(this.pct, {super.key});
  final num? pct;

  @override
  Widget build(BuildContext context) {
    final p = pct;
    if (p == null) return const SizedBox.shrink();
    final c = p > 0 ? upColor : (p < 0 ? downColor : Colors.grey);
    return Container(
      margin: const EdgeInsets.only(left: 5),
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(4)),
      child: Text('${p > 0 ? '▲' : (p < 0 ? '▼' : '')} ${p.abs().toStringAsFixed(2)}%',
          style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.bold, color: c)),
    );
  }
}

/// 손익비 박스: (1차 − 매수) / (매수 − 손절) · 2차까지 있으면 '1 : 1.5 / 2.3' — 1.5 이상 청록 · 1 미만 빨강 · 그 사이 주황
Widget? rrBox(num? entry, num? stop, num? t1, [num? t2]) {
  if (entry == null || stop == null || t1 == null || entry <= stop) return null;
  final risk = (entry - stop).toDouble();
  final r1 = (t1 - entry) / risk;
  final r2 = t2 == null ? null : (t2 - entry) / risk;
  final c = r1 >= 1.5 ? Colors.teal : (r1 >= 1 ? Colors.orange : downColor);
  return InfoBox('손익비 1 : ${r1.toStringAsFixed(1)}${r2 == null ? '' : ' / ${r2.toStringAsFixed(1)}'}', color: c, bold: true);
}

/// 점수 배지 (V3B 100점 환산) — 80↑ 빨강 / 65↑ 주황 / 50↑ 청록 / 그 아래 회색
class ScoreBadge extends StatelessWidget {
  const ScoreBadge(this.score, {super.key, this.label, this.digits = 0});
  final num? score;
  final String? label; // 예: '오늘'
  final int digits;

  @override
  Widget build(BuildContext context) {
    if (score == null) return const SizedBox.shrink();
    final v = score!.toDouble();
    final color = v >= 80 ? upColor : (v >= 65 ? Colors.orange : (v >= 50 ? Colors.teal : Colors.grey));
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
          color: color.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withValues(alpha: 0.5))),
      child: Text('${label == null ? '' : '$label '}${v.toStringAsFixed(digits)}점',
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
  'v3': 'V3',
  'reversal': '추세전환',
  'early': '상승초기',
  'nextday': '유망주',
  'uplimit': '상파',
  'daytrade': '당일단타',
  'limitcatch': '상한가포착',
  'closingbet': '종가배팅',
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
            Row(mainAxisSize: MainAxisSize.min, children: [
              Text(bigStrategy && ss != null ? '${ss.toStringAsFixed(0)}점' : '${score.toStringAsFixed(0)}점',
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              if (c['today_new'] == true) const TodayTag(),
            ]),
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
  const Sparkline({super.key, required this.values, this.color, this.height = 40, this.width, this.split});
  final List<double> values;
  final Color? color;
  final double height;
  final double? width; // 없으면 가로를 꽉 채움
  final int? split; // 이 위치부터 '그 뒤' (세로 점선 + 연한 색)

  @override
  Widget build(BuildContext context) => SizedBox(
        height: height,
        width: width ?? double.infinity,
        child: CustomPaint(painter: _SparkPainter(values, color ?? Theme.of(context).colorScheme.primary, split)),
      );
}

class _SparkPainter extends CustomPainter {
  _SparkPainter(this.v, this.color, this.split);
  final List<double> v;
  final Color color;
  final int? split;

  @override
  void paint(Canvas canvas, Size size) {
    if (v.length < 2) return;
    final all = [0.0, ...v];
    final lo = all.reduce(math.min), hi = all.reduce(math.max);
    final range = (hi - lo).abs() < 1e-9 ? 1.0 : hi - lo;
    double y(double val) => size.height - (val - lo) / range * size.height;
    double x(int i) => (i + 1) / v.length * size.width;
    canvas.drawLine(Offset(0, y(0)), Offset(size.width, y(0)), Paint()..color = Colors.grey.withValues(alpha: 0.4));
    final sp = (split == null || split! <= 0 || split! >= v.length) ? v.length : split!;
    final a = Path()..moveTo(0, y(0));
    for (var i = 0; i < sp; i++) {
      a.lineTo(x(i), y(v[i]));
    }
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6;
    canvas.drawPath(a, paint);
    if (sp < v.length) {
      final b = Path()..moveTo(x(sp - 1), y(v[sp - 1]));
      for (var i = sp; i < v.length; i++) {
        b.lineTo(x(i), y(v[i]));
      }
      canvas.drawPath(b, paint..color = color.withValues(alpha: 0.45));
      final gx = x(sp - 1);
      final dash = Paint()
        ..color = Colors.grey.withValues(alpha: 0.6)
        ..strokeWidth = 1;
      for (double yy = 0; yy < size.height; yy += 4) {
        canvas.drawLine(Offset(gx, yy), Offset(gx, math.min(yy + 2, size.height)), dash);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _SparkPainter old) => old.v != v;
}

/// 검증 표 한 칸
class StatCell {
  const StatCell(this.text, {this.color, this.bold = false});
  final String text;
  final Color? color;
  final bool bold;
}

/// 손익(%) 칸: +빨강 / −파랑
StatCell pnlCell(num? v, {int d = 2, bool bold = false}) => StatCell(
    v == null ? '-' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}%',
    color: v == null ? null : (v >= 0 ? upColor : downColor),
    bold: bold);

/// 검증용 작은 표 (첫 칸 = 구분, 나머지는 오른쪽 정렬). 첫 데이터 줄(전체)은 굵게
class StatTable extends StatelessWidget {
  const StatTable({super.key, required this.header, required this.rows, this.firstFlex = 1.5, this.boldFirst = true});
  final List<String> header;
  final List<List<StatCell>> rows;
  final double firstFlex;
  final bool boldFirst;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final base = t.bodySmall?.copyWith(fontSize: 11.5);
    final line = Theme.of(context).dividerColor.withValues(alpha: 0.4);
    Widget cell(String s, {TextAlign al = TextAlign.right, TextStyle? st}) =>
        Padding(padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 2), child: Text(s, textAlign: al, style: st ?? base));
    return Table(
      columnWidths: {0: FlexColumnWidth(firstFlex)},
      defaultColumnWidth: const FlexColumnWidth(1),
      defaultVerticalAlignment: TableCellVerticalAlignment.middle,
      children: [
        TableRow(
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: line))),
          children: [
            for (var i = 0; i < header.length; i++)
              cell(header[i], al: i == 0 ? TextAlign.left : TextAlign.right, st: base?.copyWith(color: Colors.grey)),
          ],
        ),
        for (var r = 0; r < rows.length; r++)
          TableRow(
            decoration: BoxDecoration(border: Border(bottom: BorderSide(color: line.withValues(alpha: 0.2)))),
            children: [
              for (var i = 0; i < header.length; i++)
                () {
                  final c = i < rows[r].length ? rows[r][i] : const StatCell('');
                  return cell(c.text,
                      al: i == 0 ? TextAlign.left : TextAlign.right,
                      st: base?.copyWith(
                          color: c.color, fontWeight: (c.bold || (boldFirst && r == 0)) ? FontWeight.bold : null));
                }(),
            ],
          ),
      ],
    );
  }
}
