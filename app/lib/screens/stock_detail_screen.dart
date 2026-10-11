import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../live.dart';
import '../nextday.dart';
import '../plan_line.dart';
import '../reversal.dart';
import '../widgets/common.dart';
import '../widgets/price_chart.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'portfolio_screen.dart';
import 'similar_screen.dart';

const _labels = {
  'trend': '추세',
  'volume': '거래량',
  'trading_value': '거래대금',
  'supply': '수급',
  'breakout': '가격위치',
  'volatility': '변동성·위험',
  'financial': '재무',
  'news': '공시',
};

class StockDetailScreen extends StatefulWidget {
  const StockDetailScreen({super.key, required this.code, required this.name, this.source});
  final String code;
  final String name;
  /// 어느 후보 탭에서 열었는지 (nextday·early·reversal·v3) → 맨 위에 그 탭 점수를 보여줌 (목록 점수와 같게)
  final String? source;

  @override
  State<StockDetailScreen> createState() => _StockDetailScreenState();
}

class _StockDetailScreenState extends State<StockDetailScreen> {
  late Future<Json> _f = Api.stock(widget.code);
  LiveQuote? _q; // 지금 시세 (오늘 봉)

  @override
  void initState() {
    super.initState();
    _loadLive();
  }

  Future<void> _loadLive() async {
    final r = await Live.stocks([widget.code]);
    if (mounted) setState(() => _q = r.quotes[widget.code]);
  }

  void _refresh() {
    setState(() => _f = Api.stock(widget.code));
    _loadLive();
  }

  static String _hm(DateTime t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  /// 저녁 배치 차트(어제까지) + 오늘 시세로 만든 봉 1개
  static List<Json> _withToday(List<Json> chart, LiveQuote? q) {
    if (q == null || q.tradedAt == null || chart.isEmpty) return chart;
    final today = q.tradedAt!.toIso8601String().substring(0, 10);
    if (today.compareTo('${chart.last['date']}') <= 0) return chart; // 이미 들어 있음
    final o = q.open ?? q.price;
    return [
      ...chart,
      {
        'date': today,
        'open': o,
        'high': q.high ?? (o > q.price ? o : q.price),
        'low': q.low ?? (o < q.price ? o : q.price),
        'close': q.price,
        'volume': q.volume ?? 0,
        'live': true,
      },
    ];
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(
          title: LogoTitle('${widget.name} (${widget.code})'),
          actions: topActions(context, onRefresh: _refresh)),
      body: Loader<Json>(
        future: _f,
        onRetry: _refresh,
        builder: (context, d) {
          final c = asMap(d['candidate']);
          final q = _q;
          final chart = _withToday(asList(d['chart']), q);
          final hasToday = chart.isNotEmpty && chart.last['live'] == true;
          final p = asMap(c['plan']);
          final disc = asList(d['disclosures']);
          final reasons = (c['reasons'] is List) ? (c['reasons'] as List).map((e) => '$e').toList() : <String>[];
          final warnings = (c['warnings'] is List) ? (c['warnings'] as List).map((e) => '$e').toList() : <String>[];
          final explanation = d['explanation'] == null ? null : asMap(d['explanation']);
          final v3 = asMap(c['v3']);
          final nextd = asMap(c['nextday']);
          final upl = asMap(c['uplimit']);
          // 어느 탭에서 열었는지 → 그 탭의 근거·주의·점수표만 (없으면 V3)
          const kinds = {'nextday': nextdayKind, 'early': earlyKind, 'reversal': reversalKind, 'uplimit': uplimitKind};
          final selKey = (widget.source != null && kinds.containsKey(widget.source) && asMap(c[widget.source]).isNotEmpty)
              ? widget.source!
              : null;
          final sel = selKey == null ? <String, dynamic>{} : asMap(c[selKey]);
          final selKind = selKey == null ? null : kinds[selKey];
          List<String> strs(dynamic v) => v is List ? v.map((e) => '$e').toList() : <String>[];
          final selR = selKey == null ? reasons : strs(sel['reasons']);
          final selW = selKey == null ? warnings : strs(sel['warnings']);
          final watchLines = selKey == 'nextday'
              ? strs(asMap(nextd['watch'])['lines'])
              : selKey == 'uplimit'
                  ? strs(asMap(upl['watch'])['lines'])
                  : <String>[];
          num? pv(String k) => p[k] as num?;

          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
            children: [
              // ---- 기업 개요 ----
              _ProfileCard(
                profile: {
                  'market': d['market'] ?? c['market'],
                  'sector': d['sector'] ?? c['sector'],
                  ...asMap(c['profile']),
                },
                theme: c['theme'] as String?,
              ),

              // ---- V3 기준 전략: 오늘 상태 · 점수 · 매수/매도 예정 ----
              // 후보 탭에서 열면: '탭 점수 (V3 점수)' 한 장, 아니면 V3 카드
              if (widget.source != null && widget.source != 'v3' && asMap(c[widget.source]).isNotEmpty)
                _TabHead(source: widget.source!, v: asMap(c[widget.source]), v3score: v3['score'] as num?, c: c)
              else
                _V3Head(v: v3),

              // ---- 설명 (V3 기준) ----
              if (explanation != null) _ExplainCard(code: widget.code, initial: explanation),

              // ---- 주의사항 (요약 설명 바로 아래) ----
              if (selW.isNotEmpty) ...[
                const SectionTitle('주의사항'),
                ...selW.map((w) => _bullet('⚠', _clean(w), Colors.orange)),
              ],

              // ---- 매매 계획 ----
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    // 제목 줄 오른쪽에 지금 가격 (장중이면 실시간, 아니면 분석 기준가)
                    Row(children: [
                      const Text('매매 계획', style: TextStyle(fontWeight: FontWeight.bold)),
                      const Spacer(),
                      Text(q?.price != null ? '현재가 ' : '기준가 ', style: Theme.of(context).textTheme.bodyMedium),
                      Text(won(q?.price ?? (p['price'] as num?)?.toDouble()),
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                      if (q != null) ...[
                        const SizedBox(width: 6),
                        Text(pct(q.ratio),
                            style: TextStyle(color: q.ratio >= 0 ? upColor : downColor, fontWeight: FontWeight.bold)),
                      ],
                    ]),
                    const SizedBox(height: 8),
                    // 분할 매수 구간 1·2·3차 (지지·이평선·매물대 기준)
                    if (p['zones'] is List && (p['zones'] as List).isNotEmpty) ...[
                      for (final z in asList(p['zones'])) ...[
                        _row('${z['name']} 매수구간 (${z['weight']}%)', '${num0(z['low'] as num?)} ~ ${won(z['high'] as num?)}'),
                        _note(context, '${z['note'] ?? ''}'),
                      ],
                      if (asMap(p['notes'])['zones'] != null) _note(context, '${asMap(p['notes'])['zones']}'),
                    ] else if (pv('entry_low') != null && pv('entry_high') != null)
                      _row('매수구간', '${num0(pv('entry_low'))} ~ ${won(pv('entry_high'))}'),
                    const Divider(),
                    if (pv('target1') != null) ...[
                      _row('1차 목표가', won(pv('target1')), sub: pct(pv('target1_pct')), color: upColor),
                      _note(context, asMap(p['notes'])['target1'] as String?),
                    ],
                    if (pv('target2') != null) ...[
                      _row('2차 목표가', won(pv('target2')), sub: pct(pv('target2_pct')), color: upColor),
                      _note(context, asMap(p['notes'])['target2'] as String?),
                    ],
                    if (pv('target3') != null) ...[
                      _row('3차 목표가', won(pv('target3')), sub: pct(pv('target3_pct')), color: upColor),
                      _note(context, asMap(p['notes'])['target3'] as String?),
                    ],
                    if (pv('stop') != null) ...[
                      _row('손절가', won(pv('stop')), sub: pct(pv('loss_pct')), color: downColor),
                      _note(context, asMap(p['notes'])['stop'] as String?),
                    ],
                    // 손익비 (계산 근거는 각 목표·손절 설명에 있으므로 따로 안 보임)
                    if (p['rr1'] != null) _row('손익비 (1차 목표 / 손절)', '1 : ${p['rr1']}'),
                    for (final w in (p['level_warn'] is List ? p['level_warn'] as List : const []))
                      Text('⚠ $w', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.orange)),
                    if (!(p['basis'] is List && (p['basis'] as List).isNotEmpty))
                      Text('※ 예전 방식 (목표 +8%·+15%, 손절 20일 저점/2ATR) — 다음 배치부터 차트 기준으로 바뀝니다',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey)),
                  ]),
                ),
              ),

              // ---- 차트 ----
              if (chart.isNotEmpty)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(
                          hasToday
                              ? '일봉 · 맨 오른쪽 봉 = 오늘 ${_hm(q!.tradedAt!)} 시세 (장중엔 계속 바뀜)'
                              : '일봉 (최근 ${chart.length}일)',
                          style: Theme.of(context).textTheme.bodySmall),
                      const SizedBox(height: 6),
                      ZoomableChart(
                        height: 300,
                        bars: chart,
                        levels: [
                          if (pv('target1') != null) PriceLevel('1차 목표', pv('target1')!.toDouble(), upColor),
                          if (q?.price != null || p['price'] != null)
                            PriceLevel('현재', q?.price ?? (p['price'] as num).toDouble(), Colors.grey),
                          if (pv('stop') != null) PriceLevel('손절', pv('stop')!.toDouble(), downColor),
                          if (pv('target2') != null && p['method'] == 'chart')
                            PriceLevel('2차 목표', pv('target2')!.toDouble(), upColor.withValues(alpha: 0.6)),
                          // 3차 목표가 너무 멀면(현재가 +30% 초과) 캔들이 납작해지므로 선은 생략 (표에는 표시)
                          if (pv('target3') != null && pv('price') != null && pv('target3')! <= pv('price')! * 1.3)
                            PriceLevel('3차 목표', pv('target3')!.toDouble(), upColor.withValues(alpha: 0.35)),
                        ],
                      ),
                    ]),
                  ),
                ),

              Row(children: [
                Expanded(
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.timeline),
                    label: const Text('비슷한 과거 패턴'),
                    onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => SimilarScreen(code: widget.code, name: widget.name))),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.add_card),
                    label: const Text('보유종목 추가'),
                    onPressed: () => showAddHoldingDialog(context,
                        code: widget.code,
                        name: widget.name,
                        price: (q?.price ?? (p['price'] as num?)?.toDouble()),
                        strategy: c['strategy'] as String?),
                  ),
                ),
              ]),

              // ---- 근거 / 주의: 연 탭(익일유망주·상승초기·추세전환·상파) 기준, 아니면 V3 ----
              // (문장 끝의 '→ 변동성 9/15' 같은 점수 표시는 빼고 보여줌)
              if (selR.isNotEmpty) ...[
                const SectionTitle('매수 근거'),
                ...selR.map((r) => _bullet('✓', _clean(r), Colors.green)),
              ],
              // 다음 거래일 확인 (익일유망주·상파만)
              if (watchLines.isNotEmpty) ...[
                const SectionTitle('다음 거래일 확인'),
                ...watchLines.map((l) => _bullet('→', l, Colors.teal)),
              ],

              // ---- 항목별 점수 (연 탭 하나만) ----
              const SizedBox(height: 8),
              if (selKind != null)
                ReversalScore(v: sel, kind: selKind, detail: true)
              else if (v3.isNotEmpty)
                _V3Score(v: v3),

              if (disc.isNotEmpty) ...[
                const SectionTitle('최근 공시 (30일)'),
                ...disc.map((x) => ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      title: Text(x['title'] as String),
                      subtitle: Text(x['published_at'] as String),
                    )),
              ],
              const SizedBox(height: 24),
              Text('본 정보는 규칙 기반 분석 결과이며 투자 권유가 아닙니다. 최종 판단과 책임은 본인에게 있습니다.',
                  style: Theme.of(context).textTheme.bodySmall),
            ],
          );
        },
      ),
    );
  }

  Widget _pill(String t, Color color) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(8)),
        child: Text(t, style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600)),
      );

  /// '근거 → 변동성 9/15' 처럼 끝에 붙은 점수 표시를 뗌
  String _clean(String s) => s.split(' → ').first;

  /// 목표·손절·매수구간 아래 작은 설명 줄
  Widget _note(BuildContext context, String? s) => (s == null || s.isEmpty)
      ? const SizedBox.shrink()
      : Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(s, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey)),
        );

  Widget _row(String k, String v, {String? sub, Color? color, bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Expanded(child: Text(k)),
          Text(v, style: TextStyle(fontWeight: bold ? FontWeight.bold : FontWeight.w500, color: color, fontSize: 15)),
          if (sub != null)
            SizedBox(width: 64, child: Text(sub, textAlign: TextAlign.right, style: TextStyle(color: color, fontSize: 12))),
        ]),
      );

  Widget _bullet(String icon, String text, Color color) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$icon ', style: TextStyle(color: color, fontWeight: FontWeight.bold)),
          Expanded(child: Text(text)),
        ]),
      );
}

/// 기업 개요: 시장 · 업종 · 주요제품 · 시가총액 · PER/PBR · 상장일 등
class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.profile, this.theme});
  final Json profile;
  final String? theme;

  static String _cap(num v) {
    if (v >= 1e12) return '${(v / 1e12).toStringAsFixed(v >= 1e13 ? 0 : 1)}조원';
    return '${num0((v / 1e8).round())}억원';
  }

  static String _x(num? v, {String unit = '배'}) => v == null ? '-' : '${v.toStringAsFixed(v.abs() >= 100 ? 0 : 1)}$unit';

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final p = profile;
    String? s(String k) {
      final v = p[k];
      return v == null || '$v'.trim().isEmpty ? null : '$v'.trim();
    }

    final market = s('market');
    final chips = <(String, MaterialColor)>[
      if (market != null) (market == 'KOSPI' ? '코스피' : (market == 'KOSDAQ' ? '코스닥' : market), Colors.blueGrey),
      if (s('sector') != null) (s('sector')!, Colors.indigo),
      if (theme != null && theme!.isNotEmpty) ('테마 · $theme', Colors.deepPurple),
    ];
    final info = <(String, String)>[
      if (s('industry') != null) ('업종', s('industry')!),
      if (s('products') != null) ('주요제품', s('products')!),
    ];
    final nums = <(String, String)>[
      if (p['market_cap'] is num) ('시가총액', _cap(p['market_cap'] as num)),
      if (p['per'] is num) ('PER', _x(p['per'] as num)),
      if (p['pbr'] is num) ('PBR', _x(p['pbr'] as num)),
      if (p['div'] is num) ('배당', _x(p['div'] as num, unit: '%')),
    ];
    final etc = [
      if (s('listed') != null) '상장 ${s('listed')}',
      if (s('fiscal_month') != null) '결산 ${s('fiscal_month')}',
      if (s('ceo') != null) '대표 ${s('ceo')}',
      if (s('region') != null) s('region')!,
    ];
    if (chips.isEmpty && info.isEmpty && nums.isEmpty) return const SizedBox.shrink();

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Icon(Icons.business, size: 18),
            const SizedBox(width: 6),
            Text('기업 개요', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          ]),
          if (chips.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(spacing: 6, runSpacing: 4, children: [
              for (final (label, color) in chips)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration:
                      BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8)),
                  child: Text(label, style: TextStyle(fontSize: 12, color: color.shade200)),
                ),
            ]),
          ],
          for (final (k, v) in info)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(width: 64, child: Text(k, style: t.bodySmall)),
                Expanded(child: Text(v, style: const TextStyle(fontWeight: FontWeight.w500))),
              ]),
            ),
          if (nums.isNotEmpty) ...[
            const SizedBox(height: 10),
            Row(children: [
              for (final (k, v) in nums)
                Expanded(
                  child: Column(children: [
                    Text(k, style: t.bodySmall),
                    const SizedBox(height: 2),
                    Text(v, style: const TextStyle(fontWeight: FontWeight.bold)),
                  ]),
                ),
            ]),
          ],
          if (etc.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(etc.join(' · '), style: t.bodySmall),
          ],
          if (s('homepage') != null) SelectableText(s('homepage')!, style: t.bodySmall?.copyWith(color: Colors.lightBlue)),
          if (info.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('주요제품·시가총액 등은 오늘 저녁 배치 뒤부터 나옵니다.', style: t.bodySmall),
            ),
        ]),
      ),
    );
  }
}

/// AI 설명 카드: 리포트에 미리 만든 설명이 없으면 버튼으로 요청
class _ExplainCard extends StatefulWidget {
  const _ExplainCard({required this.code, this.initial});
  final String code;
  final Json? initial;

  @override
  State<_ExplainCard> createState() => _ExplainCardState();
}

class _ExplainCardState extends State<_ExplainCard> {
  Json? _e;
  bool _loading = false;
  String? _err;

  @override
  void initState() {
    super.initState();
    _e = widget.initial;
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final r = await Api.explain(widget.code);
      setState(() => _e = r);
    } catch (e) {
      setState(() => _err = '$e');
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Icon(Icons.auto_awesome, size: 18),
            const SizedBox(width: 6),
            Text(_e == null ? '설명' : (_e!['source'] == 'ai' ? 'AI 설명' : '요약 설명'),
                style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 8),
          if (_e != null) ...[
            Text('${_e!['text']}', style: const TextStyle(height: 1.5)),
            const SizedBox(height: 6),
            Text('${_e!['disclaimer'] ?? ''}', style: t.bodySmall),
          ] else if (_loading)
            const LinearProgressIndicator()
          else ...[
            if (_err != null) Text(_err!, style: const TextStyle(color: Colors.red)),
            TextButton(onPressed: _load, child: const Text('이 종목 설명 보기')),
          ],
        ]),
      ),
    );
  }
}


/// 점수 구성: V3B-2.0 8항목 (변동성·재무·가격위치·추세·거래량·거래대금·수급·공시 = 100점)
///   예전 리포트(V3B-1.0)는 3항목 + 참고 5항목(ref_parts)이라 그 경우 참고 항목을 회색으로 같이 보여줌
class _V3Score extends StatelessWidget {
  const _V3Score({required this.v});
  final Json v;

  Widget _bar(String label, num? got, num max, {required bool counted}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          SizedBox(
              width: 96,
              child: Text(label, style: TextStyle(color: counted ? null : Colors.grey))),
          Expanded(
            child: LinearProgressIndicator(
              value: got == null ? 0 : (got / max).clamp(0, 1).toDouble(),
              minHeight: 8,
              color: counted ? Colors.teal : Colors.grey,
              borderRadius: BorderRadius.circular(4),
            ),
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final parts = asMap(v['parts']), labels = asMap(v['labels']), maxes = asMap(v['maxes']);
    final rp = asMap(v['ref_parts']), rl = asMap(v['ref_labels']), rm = asMap(v['ref_maxes']);
    const order = ['vola15', 'fin25', 'pos20', 'trend5', 'vol5', 'value5', 'flow10', 'news15'];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final k in order.where(parts.containsKey)) ...[
        _bar('${labels[k] ?? k}', parts[k] as num?, (maxes[k] as num?) ?? 1, counted: true),
        if (partDescs[k] != null)
          Padding(
            padding: const EdgeInsets.only(left: 2, bottom: 4),
            child: Text(partDescs[k]!, style: t.bodySmall?.copyWith(color: Colors.grey)),
          ),
      ],
      if (rp.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text('참고 (점수 미반영)', style: t.bodySmall?.copyWith(color: Colors.grey)),
        for (final k in ['trend5', 'vol5', 'value5', 'flow10', 'news15'])
          _bar('${rl[k] ?? k}', rp[k] as num?, (rm[k] as num?) ?? 1, counted: false),
      ],
      Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text('규칙 ${v['version'] ?? ''}', style: t.bodySmall),
      ),
    ]);
  }
}

/// 상단 카드: 다른 탭 상세처럼 '상태 + 점수' 한 줄 (V3 선정 n위 / V3 관심 / V3 보류)
class _V3Head extends StatelessWidget {
  const _V3Head({required this.v});
  final Json v;

  @override
  Widget build(BuildContext context) {
    final rank = v['rank'] as num?;
    final eligible = v['eligible'] == true;
    final score = v['score'] as num?;
    final label = rank != null ? 'V3 선정 (${rank.toInt()}위)' : (eligible ? 'V3 관심' : 'V3 보류');
    final color = rank != null ? Colors.teal : (eligible ? Colors.indigo : Colors.blueGrey);
    return Card(
      color: color.withValues(alpha: 0.10),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(children: [
          Expanded(
            child: Text(label, style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: color)),
          ),
          Text(score == null ? '-' : '${score.toStringAsFixed(0)}점',
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: color)),
        ]),
      ),
    );
  }
}


/// 후보 탭(익일유망주·상승초기·추세전환)에서 열었을 때: 그 탭 점수·등급 (목록에 보이던 점수와 같음)
class _TabHead extends StatelessWidget {
  const _TabHead({required this.source, required this.v, this.v3score, this.c = const {}});
  final String source;
  final Json v;
  final Json c; // 후보 전체 (유형·태그 칩, 확인 가격 줄)
  final num? v3score;

  static const _titles = {'nextday': '익일유망주', 'early': '상승초기', 'reversal': '추세전환', 'uplimit': '상파'};

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final score = v['score'] as num?;
    final label = '${v['label'] ?? ''}';
    final type = v['type'] as String?;
    return Card(
      color: Colors.indigo.withValues(alpha: 0.10),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${_titles[source] ?? source} ${label.isEmpty ? '' : label}',
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.indigo)),
              if (type != null && tabChipTexts(c, source).isEmpty) ...[const SizedBox(height: 4), Text(type, style: t.bodySmall)],
              // 관심 목록과 같은 유형·태그 칩 + 확인 가격 (익일유망주·상파)
              if (tabChipTexts(c, source).isNotEmpty) ...[
                const SizedBox(height: 6),
                infoBoxes([for (final x in tabChipTexts(c, source)) planChip(x.$1, x.$2)]),
              ],
              if (tabWatch(context, c, source) != null) ...[const SizedBox(height: 4), tabWatch(context, c, source)!],
            ]),
          ),
          Text.rich(TextSpan(children: [
            TextSpan(
                text: score == null ? '-' : '${score.toStringAsFixed(1)}점',
                style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.indigo)),
            if (v3score != null)
              TextSpan(text: '  (V3 ${v3score!.toStringAsFixed(0)}점)', style: t.bodyMedium?.copyWith(color: Colors.grey)),
          ])),
        ]),
      ),
    );
  }
}
