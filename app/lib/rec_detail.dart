import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';

/// 통계 표의 추천건수를 누르면 → 그 칸에 들어간 종목과 상태 (2026-10-19)
///   이익실현 1·2·3차 · 매수가매도 · 손절 · 손익 · 매수/매도 순간 종합·업종지수
///   데이터: 저녁 배치가 올리는 backtests 'RECS_DETAIL' {rows: [{d 날짜, k 구분, c 코드, n 이름, s 점수, b 점수대, tb 매수시간대,
///           t 포착시각, st 결과, cat 표 칸, p 손익%, dn 끝남, dy 보유일, ix 지수}]} — 눌렀을 때 한 번만 받아 둠
class RecDetail {
  static Future<Json>? _f;
  static Future<Json> load() => _f ??= Api.latestBacktest(strategy: 'RECS_DETAIL').catchError((_) => <String, dynamic>{});
  static void reset() => _f = null; // 끌어서 새로고침할 때
}

const _kindName = {
  'v3': 'V3',
  'nextday': '유망주',
  'early': '상승초기',
  'reversal': '추세전환',
  'uplimit': '상파',
  'closingbet': '종가배팅',
  'daytrade': '단타',
  'limitcatch': '상한가포착',
};

Color _catColor(String c) => switch (c) {
      't1' || 't2' || 't3' => upColor,
      'even' => Colors.orange,
      'stop' => downColor,
      _ => Colors.grey,
    };

/// 아래에서 올라오는 목록 — test 가 참인 종목만
Future<void> showRecDetail(BuildContext context, {required String title, required bool Function(Json r) test}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.8,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (ctx, scroll) => FutureBuilder<Json>(
        future: RecDetail.load(),
        builder: (ctx, snap) {
          if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
          final all = snap.data?['rows'];
          final rows = asList(all).where(test).toList();
          rows.sort((a, b) {
            final c = '${b['d']}'.compareTo('${a['d']}');
            return c != 0 ? c : '${a['t'] ?? ''}'.compareTo('${b['t'] ?? ''}');
          });
          return _Sheet(title: title, rows: rows, scroll: scroll, loaded: all != null);
        },
      ),
    ),
  );
}

class _Sheet extends StatelessWidget {
  const _Sheet({required this.title, required this.rows, required this.scroll, required this.loaded});
  final String title;
  final List<Json> rows;
  final ScrollController scroll;
  final bool loaded;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    int cnt(bool Function(String cat) f) => rows.where((r) => f('${r['cat']}')).length;
    final filled = rows.where((r) => r['p'] is num).toList();
    final sum = filled.fold<double>(0, (a, r) => a + (r['p'] as num).toDouble());
    Widget chip(String s, Color c) => Container(
          margin: const EdgeInsets.only(right: 6, top: 4),
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
          decoration: BoxDecoration(border: Border.all(color: c.withValues(alpha: 0.6)), borderRadius: BorderRadius.circular(4)),
          child: Text(s, style: t.bodySmall?.copyWith(fontSize: 11, color: c)),
        );
    final head = Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$title · ${rows.length}건', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
        Wrap(children: [
          chip('이익실현 ${cnt((c) => c == 't1' || c == 't2' || c == 't3')}', upColor),
          chip('매수가매도 ${cnt((c) => c == 'even')}', Colors.orange),
          chip('손절 ${cnt((c) => c == 'stop')}', downColor),
          if (filled.isNotEmpty)
            chip('평균 ${(sum / filled.length).toStringAsFixed(1)}% · 누적 ${sum.toStringAsFixed(1)}%', sum >= 0 ? upColor : downColor),
        ]),
      ]),
    );
    if (rows.isEmpty) {
      return ListView(controller: scroll, children: [
        head,
        Padding(
          padding: const EdgeInsets.all(24),
          child: Center(
              child: Text(loaded ? '해당하는 종목이 없어요' : '종목별 목록이 아직 없어요 — 오늘 저녁 배치 뒤부터 보여요',
                  style: t.bodySmall?.copyWith(color: Colors.grey))),
        ),
      ]);
    }
    return ListView.separated(
      controller: scroll,
      padding: const EdgeInsets.only(bottom: 32),
      itemCount: rows.length + 1,
      separatorBuilder: (_, i) => i == 0 ? const SizedBox.shrink() : const Divider(height: 1),
      itemBuilder: (_, i) => i == 0 ? head : _RecRow(r: rows[i - 1]),
    );
  }
}

class _RecRow extends StatelessWidget {
  const _RecRow({required this.r});
  final Json r;

  static String _sg(dynamic v) => v is num ? '${v > 0 ? '+' : (v < 0 ? '−' : '')}${v.abs().toStringAsFixed(2)}%' : '-';

  /// 매수 순간 종합·업종지수 → 청산(1·2·3차 · 매수가매도 · 손절 · 마감) 순간
  String? _ixLine() {
    final ix = asMap(r['ix']);
    final buy = ix['buy'];
    if (buy is! List || buy.isEmpty) return null;
    final cat = '${r['cat']}';
    final key = const ['t1', 't2', 't3', 'even', 'stop'].contains(cat) ? cat : 'close';
    final mk = buy.length > 3 && '${buy[3]}'.toUpperCase().contains('KOSDAQ') ? '코스닥' : '코스피';
    final head = '지수 매수 $mk ${_sg(buy[0])} · 업종 ${_sg(buy.length > 1 ? buy[1] : null)}';
    final ev = ix[key];
    if (ev is! List || ev.isEmpty) return head;
    const lab = {'t1': '1차', 't2': '2차', 't3': '3차', 'even': '매수가매도', 'stop': '손절'};
    return '$head → ${lab[key] ?? '마감'} ${_sg(ev[0])} · ${_sg(ev.length > 1 ? ev[1] : null)}${ev.length > 2 ? ' (${ev[2]})' : ''}';
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final cat = '${r['cat']}';
    final p = r['p'] as num?;
    final c = _catColor(cat);
    final st = '${r['st'] ?? ''}'.isEmpty ? '-' : '${r['st']}';
    final ixl = _ixLine();
    final score = (r['s'] as num?)?.toStringAsFixed(0);
    Widget chip(String s, Color col) => Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
          decoration: BoxDecoration(border: Border.all(color: col.withValues(alpha: 0.6)), borderRadius: BorderRadius.circular(4)),
          child: Text(s, style: t.bodySmall?.copyWith(fontSize: 11, color: col)),
        );
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
              child: Text.rich(TextSpan(children: [
            TextSpan(text: '${r['n']}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            TextSpan(text: '  ${r['c']}', style: t.bodySmall?.copyWith(color: Colors.grey)),
          ]))),
          Text(p == null ? '-' : '${p > 0 ? '+' : ''}${p.toStringAsFixed(2)}%',
              style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold, color: p == null ? null : (p >= 0 ? upColor : downColor))),
        ]),
        const SizedBox(height: 3),
        Wrap(spacing: 6, runSpacing: 2, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text(
              '${r['d']}${r['t'] != null ? ' ${r['t']}' : ''} · ${_kindName['${r['k']}'] ?? r['k']}'
              '${score != null ? ' · $score점' : ''}${r['dy'] != null ? ' · ${r['dy']}일' : ''}',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          chip(st, c),
          if (r['dn'] != true) chip('보유중', Colors.teal),
        ]),
        if (ixl != null)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(ixl, style: t.bodySmall?.copyWith(fontSize: 11, color: Colors.grey)),
          ),
      ]),
    );
  }
}
