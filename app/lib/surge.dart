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
  const SurgeSection({super.key, this.watchOnly = false});
  final bool watchOnly; // true = 당일매매 화면: '오늘 지켜보는 종목' 만 (2026-11-09) · false = 통계 > 급등예상 탭: 지난 결과·검증
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

  /// 오늘 지켜보는 종목 — 종목명·현재가·등락만, 옆으로 이어 붙임 (2026-11-05 사용자: 리스트가 너무 길어서)
  Widget _mini(BuildContext context, Json r) {
    final t = Theme.of(context).textTheme;
    final px = (r['price'] as num?) ?? (r['close'] as num?);
    return SizedBox(
      width: 158,
      child: Card(
        margin: EdgeInsets.zero,
        child: InkWell(
          onTap: () => Navigator.push(
              context, MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${r['code']}', name: '${r['name']}'))),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 6, 8, 6),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              StockName('${r['name']}', style: t.titleSmall),
              const SizedBox(height: 2),
              Row(children: [
                Expanded(child: Text(won(px), style: t.bodyMedium?.copyWith(fontWeight: FontWeight.bold))),
                if (r['chg'] is num) ChgBadge(r['chg'] as num?),
              ]),
            ]),
          ),
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
    if (widget.watchOnly) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(4, 8, 4, 2),
        child: Text(liveToday ? '오늘 지켜보는 종목 ${watch.length}' : '다음 장 관찰 목록 ${watch.length} ($listDate 저녁 기준)',
            style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
      ),
      if (watch.isEmpty) Padding(padding: const EdgeInsets.all(8), child: Text('목록이 없어요', style: t.bodySmall)),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Wrap(spacing: 6, runSpacing: 6, children: [for (final r in watch) _mini(context, r)]),
      ),
      const Divider(height: 16),
      ]);
    }
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
      const SurgeHistogram(),
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

/// 급등예상 목록의 다음 거래일 종가 등락 분포 (2026-11-09) — 하락부터 상한가까지 10% 구간별 종목 수 · 기간 검색
///   자료: system_status 'surge_stats' 의 hist [[기준일, 종가%, 고가%, 상한가 닿음, 종가 상한가], ...] (없으면 rows)
class SurgeHistogram extends StatefulWidget {
  const SurgeHistogram({super.key});
  @override
  State<SurgeHistogram> createState() => _SurgeHistogramState();
}

class _SurgeHistogramState extends State<SurgeHistogram> {
  List<List<dynamic>>? _h; // [date, close, high, reached, closed]
  DateTimeRange? _range;
  int _quick = 0; // 0 전체 · 7 · 30 (일)
  bool _err = false;

  static const _labels = ['-20% 이하', '-20~-10', '-10~0', '0~10', '10~20', '20~상한가 전', '상한가 마감'];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final st = await Api.statusKey('surge_stats');
      var h = <List<dynamic>>[];
      for (final x in (st['hist'] as List? ?? const [])) {
        if (x is List && x.length >= 5) h.add(x);
      }
      if (h.isEmpty) {
        for (final r in asList(st['rows'])) {
          h.add(['${r['date']}', r['close'], r['high'], r['reached'], r['closed']]);
        }
      }
      if (mounted) setState(() => _h = h);
    } catch (_) {
      if (mounted) setState(() => _err = true);
    }
  }

  String _ds(DateTime d) => '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  List<List<dynamic>> _sel() {
    final h = _h ?? const <List<dynamic>>[];
    String? from, to;
    if (_range != null) {
      from = _ds(_range!.start);
      to = _ds(_range!.end);
    } else if (_quick > 0) {
      from = _ds(DateTime.now().subtract(Duration(days: _quick)));
    }
    return h.where((x) {
      final d = '${x[0]}';
      return (from == null || d.compareTo(from) >= 0) && (to == null || d.compareTo(to) <= 0);
    }).toList();
  }

  static int _bin(List<dynamic> x) {
    if (x[4] == true) return 6;
    final c = (x[1] as num?)?.toDouble() ?? 0;
    if (c < -20) return 0;
    if (c < -10) return 1;
    if (c < 0) return 2;
    if (c < 10) return 3;
    if (c < 20) return 4;
    return 5;
  }

  Future<void> _pick() async {
    final now = DateTime.now();
    final r = await showDateRangePicker(
        context: context,
        firstDate: DateTime(2026, 1, 1),
        lastDate: now,
        initialDateRange: _range,
        helpText: '기준일(저녁 목록 날짜) 기간');
    if (r != null) setState(() {
          _range = r;
          _quick = 0;
        });
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    if (_err) return Text('분포를 불러오지 못했어요', style: t.bodySmall?.copyWith(color: Colors.orange));
    if (_h == null) return const Padding(padding: EdgeInsets.all(12), child: LinearProgressIndicator());
    final sel = _sel();
    final cnt = List<int>.filled(7, 0);
    for (final x in sel) {
      cnt[_bin(x)]++;
    }
    final n = sel.length;
    final mx = cnt.fold<int>(1, (a, b) => b > a ? b : a);
    int pct(int k) => n == 0 ? 0 : (k / n * 100).round();
    final hi = sel.where((x) => x[3] == true).length;
    Color col(int i) => i >= 3 ? (i == 6 ? const Color(0xFFD32F2F) : upColor) : downColor;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('종가 등락 분포 (목록 다음 거래일 · 기준일 종가 대비)', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
            for (final (d, lb) in [(0, '전체'), (7, '최근 7일'), (30, '최근 30일')])
              ChoiceChip(
                  visualDensity: VisualDensity.compact,
                  label: Text(lb),
                  selected: _range == null && _quick == d,
                  onSelected: (_) => setState(() {
                        _range = null;
                        _quick = d;
                      })),
            ActionChip(
                visualDensity: VisualDensity.compact,
                avatar: const Icon(Icons.date_range, size: 16),
                label: Text(_range == null ? '기간 선택' : '${_ds(_range!.start)} ~ ${_ds(_range!.end)}'),
                onPressed: _pick),
          ]),
          const SizedBox(height: 8),
          if (n == 0) Text('이 기간에 채점된 종목이 없어요', style: t.bodySmall?.copyWith(color: Colors.grey)),
          for (var i = 0; i < 7; i++)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(children: [
                SizedBox(width: 92, child: Text(_labels[i], style: t.bodySmall)),
                Expanded(
                  child: LayoutBuilder(builder: (context, c) {
                    final w = c.maxWidth * (cnt[i] / mx);
                    return Align(
                      alignment: Alignment.centerLeft,
                      child: Container(
                          height: 16,
                          width: cnt[i] == 0 ? 2 : w.clamp(2, c.maxWidth).toDouble(),
                          decoration: BoxDecoration(color: col(i).withValues(alpha: 0.8), borderRadius: BorderRadius.circular(3))),
                    );
                  }),
                ),
                SizedBox(width: 74, child: Text('${cnt[i]}종목 ${pct(i)}%', textAlign: TextAlign.right, style: t.bodySmall)),
              ]),
            ),
          const SizedBox(height: 4),
          Text('총 $n종목 · 장중 상한가 닿음 ${n == 0 ? '-' : '${(hi / n * 100).toStringAsFixed(1)}%'} ($hi) · 상한가 마감 ${pct(6)}% (${cnt[6]})',
              style: t.bodySmall?.copyWith(color: Colors.teal)),
        ]),
      ),
    );
  }
}
