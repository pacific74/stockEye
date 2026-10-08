import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../live.dart';
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
  const StockDetailScreen({super.key, required this.code, required this.name});
  final String code;
  final String name;

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
          final rev = asMap(c['reversal']);
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
              _V3Head(v: v3, price: q?.price, ratio: q?.ratio, basePrice: (p['price'] as num?)?.toDouble()),

              // ---- 설명 (V3 기준) ----
              if (explanation != null) _ExplainCard(code: widget.code, initial: explanation),

              // ---- 매매 계획 ----
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('매매 계획', style: TextStyle(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    if (v3['rank'] != null && v3['entry_day'] == true) ...[
                      _row('매수', '${v3['buy_date']} 시가', bold: true),
                      _row('매도 예정', '${v3['sell_date']} 종가 (20거래일째)', bold: true),
                    ] else if (v3['rank'] != null)
                      _row('매수', '다음 선정일 ${v3['next_entry'] ?? '-'} 에 상위 10 이면 다음 거래일 시가')
                    else
                      _row('매수', 'V3B 상위 10 에 들 때만 (5거래일마다 선정)'),
                    const Divider(),
                    Text('참고 가격 (V3 규칙엔 손절·익절이 없습니다 — 검증에서 손절이 수익을 깎음)',
                        style: Theme.of(context).textTheme.bodySmall),
                    if (pv('entry_low') != null && pv('entry_high') != null)
                      _row('참고 매수구간', '${num0(pv('entry_low'))} ~ ${won(pv('entry_high'))}'),
                    if (pv('target1') != null)
                      _row('참고 1차 목표가', won(pv('target1')), sub: pct(pv('target1_pct')), color: upColor),
                    if (pv('target2') != null)
                      _row('참고 2차 목표가', won(pv('target2')), sub: pct(pv('target2_pct')), color: upColor),
                    if (pv('stop') != null)
                      _row('참고 손절가', won(pv('stop')), sub: pct(pv('loss_pct')), color: downColor),
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
                              ? '최근 ${chart.length}일 · 맨 오른쪽 봉 = 오늘 ${_hm(q!.tradedAt!)} 시세 (장중엔 계속 바뀜)'
                              : '최근 ${chart.length}일 (일봉)',
                          style: Theme.of(context).textTheme.bodySmall),
                      const SizedBox(height: 6),
                      SizedBox(
                        height: 300,
                        child: PriceChart(bars: chart, levels: [
                          if (pv('target1') != null) PriceLevel('참고 목표', pv('target1')!.toDouble(), upColor),
                          if (q?.price != null || p['price'] != null)
                            PriceLevel('현재', q?.price ?? (p['price'] as num).toDouble(), Colors.grey),
                          if (pv('stop') != null) PriceLevel('참고 손절', pv('stop')!.toDouble(), downColor),
                        ]),
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

              // ---- 근거 / 주의 (V3B) ----
              if (reasons.isNotEmpty) ...[
                const SectionTitle('매수 근거'),
                ...reasons.map((r) => _bullet('✓', r, Colors.green)),
              ],
              if (warnings.isNotEmpty) ...[
                const SectionTitle('주의사항'),
                ...warnings.map((w) => _bullet('⚠', w, Colors.orange)),
              ],

              // ---- 점수 구성 ----
              if (v3.isNotEmpty) ...[
                const SectionTitle('점수 구성'),
                _V3Score(v: v3),
              ],

              // ---- 추세전환 점수 (실험 탭 · 관찰용) ----
              if (rev.isNotEmpty) ...[
                const SectionTitle('추세전환 점수'),
                ReversalScore(v: rev),
                ...((rev['reasons'] is List) ? rev['reasons'] as List : const []).map((r) => _bullet('✓', '$r', Colors.indigo)),
                ...((rev['warnings'] is List) ? rev['warnings'] as List : const []).map((w) => _bullet('⚠', '$w', Colors.orange)),
              ],

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


/// 점수 구성: V3B 반영 3항목(변동성·재무·가격위치) + 참고 5항목(추세·거래량·거래대금·수급·공시, 점수 미반영)
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
          SizedBox(
            width: 70,
            child: Text(got == null ? '데이터없음' : '${got.toStringAsFixed(1)}/$max',
                textAlign: TextAlign.right, style: TextStyle(fontSize: 12, color: counted ? null : Colors.grey)),
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final parts = asMap(v['parts']), labels = asMap(v['labels']), maxes = asMap(v['maxes']);
    final rp = asMap(v['ref_parts']), rl = asMap(v['ref_labels']), rm = asMap(v['ref_maxes']);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('V3B ${v['score'] == null ? '-' : (v['score'] as num).toStringAsFixed(0)}점 = (변동성 + 재무 + 가격위치) ÷ 60 × 100'
          '${v['raw'] == null ? '' : '  · 원점수 ${v['raw']}/60'}',
          style: t.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
      for (final k in ['vola15', 'fin25', 'pos20'])
        _bar('${labels[k] ?? k}', parts[k] as num?, (maxes[k] as num?) ?? 1, counted: true),
      if (rp.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text('참고 (점수 미반영) — 검증에서 예측력이 없거나 반대였던 항목', style: t.bodySmall?.copyWith(color: Colors.grey)),
        for (final k in ['trend5', 'vol5', 'value5', 'flow10', 'news15'])
          _bar('${rl[k] ?? k}', rp[k] as num?, (rm[k] as num?) ?? 1, counted: false),
      ],
      Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text('변동성 낮을수록 · 재무 좋을수록 · 20·60일선/지지선 근처 조정일수록 높음. 규칙 고정 ${v['version'] ?? ''}',
            style: t.bodySmall),
      ),
    ]);
  }
}

/// 상단 카드: V3 상태 (상위 10 n위 / 자격 있음 / 자격 없음+사유) · V3B 점수 · 지금 가격 · 매수/매도 예정
class _V3Head extends StatelessWidget {
  const _V3Head({required this.v, this.price, this.ratio, this.basePrice});
  final Json v;
  final double? price, ratio, basePrice;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final top = v['rank'] != null;
    final color = top ? Colors.teal : (v['eligible'] == true ? Colors.blueGrey : Colors.orange);
    final why = (v['why_not'] is List) ? (v['why_not'] as List).map((e) => '$e').toList() : <String>[];
    final score = v['score'] as num?;
    return Card(
      color: color.withValues(alpha: 0.10),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${v['status'] ?? 'V3 점수 없음'}',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: color)),
                const SizedBox(height: 4),
                if (top && v['entry_day'] == true)
                  Text('${v['buy_date']} 시가 매수 → ${v['sell_date']} 종가 매도 예정 (20거래일)', style: t.bodyMedium)
                else if (top)
                  Text('참고 순위 · 다음 선정일 ${v['next_entry'] ?? '-'}', style: t.bodyMedium)
                else if (v['eligible'] == true)
                  Text('V3B 상위 10 에 들면 다음 거래일 시가에 매수 (5거래일마다 선정)', style: t.bodySmall),
                ...why.map((w) => Text('· $w', style: t.bodySmall?.copyWith(color: Colors.orange))),
              ]),
            ),
            Column(children: [
              Text(score == null ? '-' : '${score.toStringAsFixed(0)}점', style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
              if (v['raw'] != null) Text('원점수 ${v['raw']}/60', style: t.bodySmall),
            ]),
          ]),
          const Divider(),
          Row(children: [
            Text(price != null ? '지금 가격' : '분석 기준가', style: t.bodySmall),
            const Spacer(),
            Text(won(price ?? basePrice), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            if (ratio != null) ...[
              const SizedBox(width: 8),
              Text(pct(ratio), style: TextStyle(color: ratio! >= 0 ? upColor : downColor, fontWeight: FontWeight.bold)),
            ],
          ]),
          const SizedBox(height: 4),
          Text('V3 기준: 손절·목표가 없이 20거래일 보유, 보유 중 다시 상위 10 이면 연장 (규칙 고정 ${v['version'] ?? ''})',
              style: t.bodySmall),
        ]),
      ),
    );
  }
}
