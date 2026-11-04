import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'limitcatch.dart' show lcWindow;
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 급등예상 (SG-1.0, 2026-11-02) — 상한가포착을 대체.
///   저녁 배치(system_status 'surge') 가 학습 모델로 '다음 거래일 상한가 갈 만한' 20종목을 뽑아 둠
///   → PC 가 다음날 09:00~15:20 1분마다 지켜봄 ('surge_live') → 아침에 어제 결과 채점 ('surge'.prev · 'surge_stats')
///   ⚠ 매수 신호가 아니라 관찰 목록. 목록이 얼마나 맞는지 쌓아 보는 중.

String _today() {
  final n = DateTime.now();
  return '${n.year}-${n.month.toString().padLeft(2, '0')}-${n.day.toString().padLeft(2, '0')}';
}

Color surgeStatusColor(String? s) => switch (s) {
      '상한가' => const Color(0xFFD32F2F),
      '상한가 풀림' => Colors.orange,
      '+20% 돌파' => Colors.deepOrange,
      '+15% 돌파' => Colors.deepOrange,
      '+10% 돌파' => Colors.deepOrange,
      '하락' => Colors.blueGrey,
      '상승 중' => Colors.teal,
      _ => Colors.grey,
    };

class SurgeSection extends StatefulWidget {
  const SurgeSection({super.key});
  @override
  State<SurgeSection> createState() => _SurgeSectionState();
}

class _SurgeSectionState extends State<SurgeSection> {
  Json? _sg, _lv, _st;
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _load();
    _t = Timer.periodic(const Duration(seconds: 60), (_) {
      if (lcWindow()) _load();
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final r = await Future.wait([
      Api.statusKey('surge').catchError((_) => <String, dynamic>{}),
      Api.statusKey('surge_live').catchError((_) => <String, dynamic>{}),
      Api.statusKey('surge_stats').catchError((_) => <String, dynamic>{}),
    ]);
    if (!mounted) return;
    setState(() {
      _sg = r[0];
      _lv = r[1];
      _st = r[2];
    });
  }

  Widget _chip(TextTheme t, String s, Color c) => Container(
        margin: const EdgeInsets.only(right: 4, top: 3),
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
        decoration: BoxDecoration(border: Border.all(color: c.withValues(alpha: 0.5)), borderRadius: BorderRadius.circular(4)),
        child: Text(s, style: t.bodySmall?.copyWith(fontSize: 11, color: c)),
      );

  Widget _tile(BuildContext context, Json r) {
    final t = Theme.of(context).textTheme;
    final live = r['status'] != null;
    final st = '${r['status'] ?? ''}';
    final first = asMap(r['first']);
    final px = (r['price'] as num?) ?? (r['close'] as num?);
    const labels = [('lu', '상한가'), ('h20', '+20%'), ('h15', '+15%'), ('h10', '+10%')];
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 3),
      child: InkWell(
        onTap: () => Navigator.push(
            context, MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${r['code']}', name: '${r['name']}'))),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('${r['rank'] ?? ''}  ', style: t.bodySmall?.copyWith(color: Colors.grey)),
              Expanded(child: StockName('${r['name']}', style: t.titleSmall)),
              Text(won(px), style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              if (live) ChgBadge(r['chg'] as num?),
            ]),
            Wrap(children: [
              if (live && st.isNotEmpty) _chip(t, st, surgeStatusColor(st)),
              if (r['src'] != null) _chip(t, r['src'] == 'gap' ? '아침 갭 보강' : '아침 보강', Colors.purple),
              if (r['pre'] is num) _chip(t, '프리마켓 ${(r['pre'] as num) >= 0 ? '+' : ''}${r['pre']}%', Colors.purple),
              if (r['score'] is num) _chip(t, '점수 ${(r['score'] as num).toStringAsFixed(1)}', Colors.grey),
              if (live && r['high'] is num) _chip(t, '고가 ${(r['high'] as num) >= 0 ? '+' : ''}${r['high']}%', Colors.grey),
              for (final (k, lb) in labels)
                if (first[k] != null) _chip(t, '$lb ${first[k]}', Colors.deepOrange),
              for (final s in (r['reasons'] as List? ?? const []).map((e) => '$e')) _chip(t, s, Colors.teal),
            ]),
          ]),
        ),
      ),
    );
  }

  Widget _prevCard(BuildContext context, Json sg) {
    final t = Theme.of(context).textTheme;
    final p = asMap(sg['prev']);
    final all = asMap(asMap(sg['stats'])['all']);
    if (p.isEmpty) {
      return Text('지난 결과는 아직 없어요 — 저녁 목록이 하루 지나면 아침에 여기 채점돼요', style: t.bodySmall?.copyWith(color: Colors.grey));
    }
    final miss = asList(p['missed']).where((m) => m['rank'] == null || (m['rank'] as num) > 20).take(3);
    String f(dynamic v) => v == null ? '-' : '$v';
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('지난 결과 · ${f(p['date'])} 저녁 목록 → ${f(p['next'])}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          Text('${f(p['n'])}종목 중 상한가 닿음 ${f(p['reached'])}% · 종가 잠김 ${f(p['closed'])}% · +15% ${f(p['h15'])}% · +20% ${f(p['h20'])}%',
              style: t.bodySmall),
          Text('종가 평균 ${f(p['close_avg'])}% (전체 종목 평균 ${f(p['base_close'])}%) · 아무 종목이 상한가 갈 확률 ${f(p['base_lu'])}%',
              style: t.bodySmall),
          Text('그날 상한가 마감 ${f(p['lu_total'])}종목 중 목록 ${f(p['lu_in20'])} · 점수 상위 100 ${f(p['lu_in100'])}', style: t.bodySmall),
          if (miss.isNotEmpty)
            Text('놓친 예: ${miss.map((m) => '${m['name']}(${m['rank'] ?? '100위 밖'})').join(' / ')}',
                style: t.bodySmall?.copyWith(color: Colors.orange)),
          if ((all['n'] as num? ?? 0) > 0)
            Text('누적 ${asMap(sg['stats'])['days'] ?? '-'}일 ${all['n']}건 · 상한가 닿음 ${f(all['reached'])}% · 종가 잠김 ${f(all['closed'])}% '
                '· 종가 평균 ${f(all['close_avg'])}% (기준선 ${f(asMap(sg['stats'])['base_lu'])}%)',
                style: t.bodySmall?.copyWith(color: Colors.teal)),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    if (_sg == null) return const Padding(padding: EdgeInsets.all(12), child: LinearProgressIndicator());
    final sg = _sg!;
    final lv = _lv ?? const <String, dynamic>{};
    final today = _today();
    final listDate = '${sg['date'] ?? ''}';
    final liveToday = '${lv['date'] ?? ''}' == today;
    final items = asList(sg['items']);
    final watch = liveToday ? asList(lv['rows']) : (listDate.isNotEmpty && listDate.compareTo(today) < 0 ? items : <Json>[]);
    final next = listDate.isNotEmpty && listDate.compareTo(today) >= 0 ? items : <Json>[];
    final days = asList(_st?['days']).reversed.take(10).toList();
    String f(dynamic v) => v == null ? '-' : '$v';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 4, 2),
        child: Text.rich(TextSpan(children: [
          TextSpan(text: '급등예상', style: t.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
          TextSpan(text: '  어젯밤 학습 모델이 고른 관찰 목록 · 매수 신호 아님 (검증 중)', style: t.bodySmall?.copyWith(color: Colors.grey)),
        ])),
      ),
      if (liveToday)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Text(
              '${f(lv['time'])} 기준 · ${f(lv['n'])}종목 중 상한가 닿음 ${f(lv['reached'])} · +20% ${f(lv['h20'])} · +15% ${f(lv['h15'])} · +10% ${f(lv['h10'])}',
              style: t.bodySmall?.copyWith(color: Colors.green)),
        ),
      if (liveToday && (lv['n_extra'] as num? ?? 0) > 0)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Text('아침 보강 ${lv['n_extra']}종목(프리마켓 갭) 중 상한가 닿음 ${f(lv['extra_reached'])}',
              style: t.bodySmall?.copyWith(color: Colors.purple)),
        ),
      _prevCard(context, sg),
      Padding(
        padding: const EdgeInsets.fromLTRB(4, 8, 4, 2),
        child: Text(liveToday ? '오늘 지켜보는 종목 ${watch.length}' : '다음 장 관찰 목록 ${watch.length} ($listDate 저녁 기준)',
            style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
      ),
      if (watch.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text('목록이 없어요', style: t.bodySmall)),
      for (final r in watch) _tile(context, r),
      if (next.isNotEmpty)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            dense: true,
            initiallyExpanded: !liveToday,
            tilePadding: const EdgeInsets.symmetric(horizontal: 4),
            title: Text('다음 거래일 관찰 목록 ${next.length} ($listDate 종가 기준)', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            children: [for (final r in next) _tile(context, r)],
          ),
        ),
      if (days.isNotEmpty)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            dense: true,
            tilePadding: const EdgeInsets.symmetric(horizontal: 4),
            title: Text('날짜별 검증 (최근 ${days.length}일)', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            children: [
              for (final d in days)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  child: Text(
                      '${f(d['next'])} · 상한가 ${f(d['reached'])}% · +15% ${f(d['h15'])}% · 종가 ${f(d['close_avg'])}% (전체 ${f(d['base_close'])}%) '
                      '· 상한가 마감 ${f(d['lu_total'])}개 중 목록 ${f(d['lu_in20'])}',
                      style: t.bodySmall),
                ),
            ],
          ),
        ),
      const Divider(height: 16),
    ]);
  }
}
