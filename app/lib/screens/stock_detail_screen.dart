import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../live.dart';
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
          final reasons = List<String>.from(c['reasons'] as List);
          final sreasons = List<String>.from(c['strategy_reasons'] as List? ?? []);
          final warnings = List<String>.from(c['warnings'] as List);
          final missing = List<String>.from(c['missing'] as List);
          final parts = asMap(c['parts']);
          final maxParts = asMap(c['max_parts']);
          final tags = List<String>.from(c['tags'] as List? ?? []);
          final disc = asList(d['disclosures']);
          final verdict = p['verdict'] as String;
          final explanation = d['explanation'] == null ? null : asMap(d['explanation']);

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

              // ---- 판정 ----
              Card(
                color: verdictColor(verdict).withValues(alpha: 0.12),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(verdict,
                            style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: verdictColor(verdict))),
                        const SizedBox(height: 4),
                        Text(p['verdict_reason'] as String),
                        if (tags.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Text('해당 전략: ${tags.map((t) => strategyLabels[t] ?? t).join(', ')}',
                              style: Theme.of(context).textTheme.bodySmall),
                        ],
                        if (c['engine'] == 'v2') ...[
                          const SizedBox(height: 8),
                          Wrap(spacing: 6, runSpacing: 4, children: [
                            if (c['grade'] != null) _pill('${c['grade_icon'] ?? ''} ${c['grade']}', verdictColor('${c['grade']}')),
                            if (c['market_state_label'] != null)
                              _pill(
                                  '시장 ${c['market_state'] == 'A' ? '🟢' : c['market_state'] == 'C' ? '🔴' : '🟡'} ${c['market_state_label']}',
                                  c['market_state'] == 'A'
                                      ? Colors.green
                                      : (c['market_state'] == 'C' ? downColor : Colors.orange)),
                            if (c['sector_score'] != null)
                              _pill('업종 ${c['sector'] ?? ''} ${(c['sector_score'] as num).toStringAsFixed(0)}/15',
                                  (c['sector_score'] as num) >= 5 ? Colors.indigo : Colors.grey),
                          ]),
                          if ((c['blocks'] as List? ?? const []).isNotEmpty) ...[
                            const SizedBox(height: 6),
                            Text('⛔ 매수 차단: ${(c['blocks'] as List).join(', ')}',
                                style: const TextStyle(color: Colors.redAccent, fontWeight: FontWeight.w600)),
                          ],
                        ],
                      ]),
                    ),
                    Column(children: [
                      Text('${(c['score'] as num).toStringAsFixed(0)}점',
                          style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
                      Text(stars(c['stars'] as int), style: const TextStyle(color: Colors.amber)),
                    ]),
                  ]),
                ),
              ),

              // ---- AI 설명 (판단 보조) ----
              _ExplainCard(code: widget.code, initial: explanation),

              // ---- 매매 계획 ----
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(children: [
                    if (q != null)
                      _row('지금 가격', won(q.price),
                          sub: '오늘 ${pct(q.ratio)}', color: q.ratio >= 0 ? upColor : downColor, bold: true),
                    _row(q != null ? '분석 기준가' : '현재가', won(p['price'] as num), bold: q == null),
                    const Divider(),
                    _row('매수 적정구간', '${num0(p['entry_low'] as num)} ~ ${won(p['entry_high'] as num)}'),
                    _row('1차 목표가', won(p['target1'] as num), sub: pct(p['target1_pct'] as num), color: upColor),
                    _row('2차 목표가', won(p['target2'] as num), sub: pct(p['target2_pct'] as num), color: upColor),
                    _row('손절가격', won(p['stop'] as num), sub: pct(p['loss_pct'] as num), color: downColor),
                    const Divider(),
                    _row('예상 손실', pct(p['loss_pct'] as num), color: downColor),
                    _row('1차 목표 수익', pct(p['target1_pct'] as num), color: upColor),
                    _row('위험/보상', '1 : ${(p['rr1'] as num).toStringAsFixed(2)}', bold: true),
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
                          PriceLevel('2차', (p['target2'] as num).toDouble(), upColor.withValues(alpha: 0.5)),
                          PriceLevel('1차', (p['target1'] as num).toDouble(), upColor),
                          PriceLevel('현재', q?.price ?? (p['price'] as num).toDouble(), Colors.grey),
                          PriceLevel('손절', (p['stop'] as num).toDouble(), downColor),
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
                        price: (p['price'] as num).toDouble(),
                        stop: (p['stop'] as num).toDouble(),
                        target: (p['target1'] as num).toDouble(),
                        strategy: c['strategy'] as String?),
                  ),
                ),
              ]),

              // ---- 근거 / 주의 ----
              const SectionTitle('매수 근거'),
              ...reasons.map((r) => _bullet('✓', r, Colors.green)),
              if (sreasons.isNotEmpty) ...[
                const SectionTitle('전략 근거'),
                ...sreasons.map((r) => _bullet('✓', r, Colors.teal)),
              ],
              if (warnings.isNotEmpty) ...[
                const SectionTitle('주의사항'),
                ...warnings.map((w) => _bullet('⚠', w, Colors.orange)),
              ],

              // ---- 점수 구성 ----
              const SectionTitle('점수 구성'),
              ..._labels.entries.map((e) {
                final got = parts[e.key] as num?;
                final max = (maxParts[e.key] as num?) ?? 1;
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(children: [
                    SizedBox(width: 96, child: Text(e.value)),
                    Expanded(
                      child: LinearProgressIndicator(
                        value: got == null ? 0 : (got / max).clamp(0, 1).toDouble(),
                        minHeight: 8,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                    SizedBox(
                      width: 70,
                      child: Text(got == null ? '데이터없음' : '${got.toStringAsFixed(1)}/$max',
                          textAlign: TextAlign.right, style: const TextStyle(fontSize: 12)),
                    ),
                  ]),
                );
              }),
              if (missing.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text('※ ${missing.map((m) => _labels[m] ?? m).join(', ')} 데이터가 없어 나머지 항목으로 100점 환산',
                      style: Theme.of(context).textTheme.bodySmall),
                ),

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
