import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';

class BacktestScreen extends StatefulWidget {
  const BacktestScreen({super.key});

  @override
  State<BacktestScreen> createState() => _BacktestScreenState();
}

class _BacktestScreenState extends State<BacktestScreen> {
  // 기본 = 예시 전략 (20일선 위 + 거래량 2배 + 20일 고점 돌파 + 외국인 순매수 + RSI 50~70)
  String mode = 'strategy'; // strategy | engine | rules
  String strat = 'A';
  late Future<List<Json>> _strategies = Api.strategies();
  bool closeGtSma20 = true;
  bool breakout20 = true;
  bool foreignBuy = true;
  bool sma20Rising = false;
  bool macdPos = false;
  final volCtl = TextEditingController(text: '2.0');
  final rsiLoCtl = TextEditingController(text: '50');
  final rsiHiCtl = TextEditingController(text: '70');
  final minScoreCtl = TextEditingController(text: '75');
  final startCtl = TextEditingController(text: '2021-01-01');

  bool running = false;
  Map<String, dynamic>? result;
  String? error;
  String? info;
  late Future<List<Json>> _reqs = backtestRequests();

  @override
  void initState() {
    super.initState();
    Api.latestBacktest().then((r) {
      if (mounted) setState(() => result = r);
    }).catchError((_) {});
  }

  List<dynamic> _rules() {
    final r = <dynamic>[];
    if (closeGtSma20) r.add('close_gt_sma20');
    if (sma20Rising) r.add('sma20_rising');
    final v = double.tryParse(volCtl.text);
    if (v != null && v > 0) r.add({'vol_ratio_gte': v});
    if (breakout20) r.add('breakout_20d');
    if (foreignBuy) r.add('foreign_net_positive');
    if (macdPos) r.add('macd_positive');
    final lo = double.tryParse(rsiLoCtl.text), hi = double.tryParse(rsiHiCtl.text);
    if (lo != null && hi != null) r.add({'rsi_between': [lo, hi]});
    r.add({'value_ma20_gte': 2000000000});
    r.add({'price_gte': 1000});
    return r;
  }

  Future<void> _run() async {
    setState(() {
      running = true;
      error = null;
      info = null;
    });
    try {
      final r = await Api.backtest({
        'strategy': mode == 'strategy' ? strat : null,
        'engine': mode == 'engine',
        'rules': mode == 'rules' ? _rules() : null,
        'min_score': double.tryParse(minScoreCtl.text) ?? 75,
        'start': startCtl.text.isEmpty ? null : startCtl.text,
      });
      setState(() {
        if (r['queued'] == true) {
          info = '${r['message']}';   // 클라우드: 배치 서버가 실행 → 결과는 나중에
          _reqs = backtestRequests();
        } else {
          result = r;
        }
        _strategies = Api.strategies();
      });
    } catch (e) {
      setState(() => error = '$e');
    } finally {
      setState(() => running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const LogoTitle('백테스트')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'strategy', label: Text('전략 A~E')),
                    ButtonSegment(value: 'engine', label: Text('종합 엔진')),
                    ButtonSegment(value: 'rules', label: Text('직접 조건')),
                  ],
                  selected: {mode},
                  onSelectionChanged: (v) => setState(() => mode = v.first),
                ),
                const SizedBox(height: 8),
                if (mode == 'strategy')
                  Wrap(spacing: 6, children: [
                    for (final k in ['A', 'B', 'C', 'D', 'E'])
                      ChoiceChip(
                        label: Text('$k ${strategyLabels[k]}'),
                        selected: strat == k,
                        onSelected: (_) => setState(() => strat = k),
                      ),
                  ])
                else if (mode == 'engine')
                  _field('최소 점수', minScoreCtl)
                else ...[
                  _check('현재가 > 20일선', closeGtSma20, (v) => closeGtSma20 = v),
                  _check('20일선 상승', sma20Rising, (v) => sma20Rising = v),
                  _check('최근 20일 고점 돌파', breakout20, (v) => breakout20 = v),
                  _check('외국인 순매수', foreignBuy, (v) => foreignBuy = v),
                  _check('MACD > 시그널', macdPos, (v) => macdPos = v),
                  Row(children: [
                    Expanded(child: _field('거래량 배수 ≥', volCtl)),
                    const SizedBox(width: 8),
                    Expanded(child: _field('RSI 하한', rsiLoCtl)),
                    const SizedBox(width: 8),
                    Expanded(child: _field('RSI 상한', rsiHiCtl)),
                  ]),
                ],
                _field('시작일', startCtl, number: false),
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: running ? null : _run,
                    icon: running
                        ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.play_arrow),
                    label: Text(running
                        ? (useCloud ? '요청 중...' : '실행 중... (수 분 걸릴 수 있음)')
                        : (useCloud ? '백테스트 요청 (서버에서 5년치 실행)' : '백테스트 실행')),
                  ),
                ),
              ]),
            ),
          ),
          _StrategyCompare(future: _strategies),
          if (info != null)
            Card(
              color: Colors.blue.withValues(alpha: 0.12),
              child: Padding(padding: const EdgeInsets.all(12), child: Text(info!)),
            ),
          if (useCloud) _Requests(future: _reqs, onRefresh: () => setState(() => _reqs = backtestRequests())),
          if (error != null) Padding(padding: const EdgeInsets.all(8), child: Text(error!, style: const TextStyle(color: Colors.red))),
          if (result != null) _Result(r: result!),
        ],
      ),
    );
  }

  Widget _check(String t, bool v, void Function(bool) set) => CheckboxListTile(
        dense: true,
        contentPadding: EdgeInsets.zero,
        title: Text(t),
        value: v,
        onChanged: (x) => setState(() => set(x ?? false)),
      );

  Widget _field(String label, TextEditingController c, {bool number = true}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: TextField(
          controller: c,
          keyboardType: number ? const TextInputType.numberWithOptions(decimal: true) : TextInputType.datetime,
          decoration: InputDecoration(labelText: label, isDense: true, border: const OutlineInputBorder()),
        ),
      );
}

class _Result extends StatelessWidget {
  const _Result({required this.r});
  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final m = Map<String, dynamic>.from(r['metrics'] as Map);
    final mi = Map<String, dynamic>.from(r['metrics_is'] as Map);
    final mo = Map<String, dynamic>.from(r['metrics_oos'] as Map);
    final yearly = List<Map<String, dynamic>>.from((r['yearly'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
    final warnings = List<String>.from(r['warnings'] as List);
    final audit = r['audit'] == null ? null : Map<String, dynamic>.from(r['audit'] as Map);
    final equity = List<Map<String, dynamic>>.from((r['equity'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
    final t = Theme.of(context).textTheme;

    String v(Map<String, dynamic> mm, String k, [String suf = '']) =>
        mm[k] == null ? '-' : '${mm[k]}$suf';

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 12),
      if (audit != null)
        Card(
          color: (audit['passed'] == true ? Colors.green : Colors.red).withValues(alpha: 0.12),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(audit['passed'] == true ? '미래참조 감사 통과 ✅' : '미래참조 감사 실패 ❌ — 결과 신뢰 불가',
                  style: t.titleMedium),
              ...List<Map<String, dynamic>>.from((audit['checks'] as List).map((e) => Map<String, dynamic>.from(e as Map)))
                  .map((c) => Text('${c['passed'] == true ? '✓' : '✗'} ${c['check']}', style: t.bodySmall)),
            ]),
          ),
        ),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${r['strategy']}', style: t.titleSmall),
            Text('기간: ${r['start']} ~ ${r['end']}  (수수료·세금·슬리피지 반영)', style: t.bodySmall),
            const Divider(),
            _kv('총 매매', v(m, 'trades', '회')),
            _kv('승률', v(m, 'win_rate', '%')),
            _kv('평균 수익', pct(m['avg_win_pct'] as num?)),
            _kv('평균 손실', pct(m['avg_loss_pct'] as num?)),
            _kv('1회 기대값', pct(m['expectancy_pct'] as num?)),
            _kv('Profit Factor', v(m, 'profit_factor')),
            _kv('최대 연속손실', v(m, 'max_consec_losses', '회')),
            _kv('최대 낙폭', pct(m['mdd_pct'] as num?)),
            _kv('최종 수익률', pct(m['total_return_pct'] as num?), bold: true),
            _kv('연평균(CAGR)', pct(m['cagr_pct'] as num?)),
            _kv('KOSPI 대비', pct(m['benchmark_return_pct'] as num?)),
          ]),
        ),
      ),
      if (equity.length > 2)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: SizedBox(height: 160, child: CustomPaint(painter: _EquityPainter(equity), size: Size.infinite)),
          ),
        ),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('표본 내 vs 표본 외', style: t.titleSmall),
            Text('표본 외(최근 구간) 성과가 크게 나쁘면 과최적화 의심', style: t.bodySmall),
            const SizedBox(height: 8),
            _kv('표본 내 ${mi['period'] ?? ''}', '${pct(mi['total_return_pct'] as num?)} / 승률 ${v(mi, 'win_rate', '%')}'),
            _kv('표본 외 ${mo['period'] ?? ''}', '${pct(mo['total_return_pct'] as num?)} / 승률 ${v(mo, 'win_rate', '%')}'),
            const Divider(),
            Text('연도별', style: t.titleSmall),
            ...yearly.map((y) => _kv('${y['year']}',
                '${pct(y['return_pct'] as num?)}  ·  ${y['trades']}회  ·  승률 ${y['win_rate'] ?? '-'}%  ·  MDD ${y['mdd_pct']}%')),
          ]),
        ),
      ),
      ...warnings.map((w) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Text('⚠ $w', style: t.bodySmall),
          )),
    ]);
  }

  Widget _kv(String k, String v, {bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(k)),
          Text(v, style: TextStyle(fontWeight: bold ? FontWeight.bold : FontWeight.normal)),
        ]),
      );
}

class _EquityPainter extends CustomPainter {
  _EquityPainter(this.eq);
  final List<Map<String, dynamic>> eq;

  @override
  void paint(Canvas canvas, Size size) {
    final vals = eq.map((e) => (e['equity'] as num).toDouble()).toList();
    final lo = vals.reduce(math.min), hi = vals.reduce(math.max);
    final range = (hi - lo) == 0 ? 1 : hi - lo;
    final path = Path();
    for (var i = 0; i < vals.length; i++) {
      final x = i / (vals.length - 1) * size.width;
      final y = size.height - (vals[i] - lo) / range * size.height;
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    final up = vals.last >= vals.first;
    canvas.drawPath(
        path,
        Paint()
          ..color = up ? upColor : downColor
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5);
    final base = size.height - (vals.first - lo) / range * size.height;
    canvas.drawLine(Offset(0, base), Offset(size.width, base), Paint()..color = Colors.grey.withValues(alpha: 0.5));
  }

  @override
  bool shouldRepaint(covariant _EquityPainter old) => old.eq != eq;
}


/// 전략별 백테스트 결과 비교 (실행해 둔 전략만 표시)
class _StrategyCompare extends StatelessWidget {
  const _StrategyCompare({required this.future});
  final Future<List<Json>> future;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Json>>(
      future: future,
      builder: (context, snap) {
        if (!snap.hasData) return const SizedBox.shrink();
        final rows = snap.data!.where((s) => s['backtest'] != null).toList();
        if (rows.isEmpty) return const SizedBox.shrink();
        final t = Theme.of(context).textTheme;
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('전략별 백테스트 비교 (비용 반영)', style: t.titleSmall),
              const SizedBox(height: 6),
              const Row(children: [
                Expanded(flex: 3, child: Text('전략', style: TextStyle(fontSize: 12))),
                Expanded(flex: 2, child: Text('승률', textAlign: TextAlign.right, style: TextStyle(fontSize: 12))),
                Expanded(flex: 2, child: Text('기대값', textAlign: TextAlign.right, style: TextStyle(fontSize: 12))),
                Expanded(flex: 2, child: Text('MDD', textAlign: TextAlign.right, style: TextStyle(fontSize: 12))),
                Expanded(flex: 2, child: Text('표본외', textAlign: TextAlign.right, style: TextStyle(fontSize: 12))),
              ]),
              const Divider(),
              ...rows.map((s) {
                final b = asMap(s['backtest']);
                final m = asMap(b['metrics']);
                final o = asMap(b['metrics_oos']);
                final audited = b['audit_passed'];
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(children: [
                    Expanded(flex: 3, child: Text('${s['key']}. ${s['short']}${audited == false ? ' ❌' : ''}')),
                    Expanded(flex: 2, child: Text('${m['win_rate'] ?? '-'}%', textAlign: TextAlign.right)),
                    Expanded(flex: 2, child: Text(pct(m['expectancy_pct'] as num?), textAlign: TextAlign.right)),
                    Expanded(flex: 2, child: Text(pct(m['mdd_pct'] as num?), textAlign: TextAlign.right)),
                    Expanded(flex: 2, child: Text(pct(o['total_return_pct'] as num?), textAlign: TextAlign.right)),
                  ]),
                );
              }),
            ]),
          ),
        );
      },
    );
  }
}


/// 클라우드: 내가 요청한 백테스트 진행 상태
class _Requests extends StatelessWidget {
  const _Requests({required this.future, required this.onRefresh});
  final Future<List<Json>> future;
  final VoidCallback onRefresh;

  static const _label = {'queued': '대기', 'running': '실행 중', 'done': '완료', 'failed': '실패'};

  String _spec(Json s) {
    if (s['strategy'] != null) return '전략 ${s['strategy']} ${strategyLabels[s['strategy']] ?? ''}';
    if (s['engine'] == true) return '종합 엔진 (${s['min_score'] ?? 75}점 이상)';
    return '직접 조건 ${(s['rules'] as List?)?.length ?? 0}개';
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Json>>(
      future: future,
      builder: (context, snap) {
        final rows = snap.data ?? const <Json>[];
        if (rows.isEmpty) return const SizedBox.shrink();
        return Card(
          child: Column(children: [
            ListTile(
              dense: true,
              title: const Text('내 백테스트 요청'),
              subtitle: const Text('완료되면 아래에 가장 최근 결과가 표시됩니다'),
              trailing: IconButton(icon: const Icon(Icons.refresh), onPressed: onRefresh),
            ),
            ...rows.map((r) => ListTile(
                  dense: true,
                  title: Text(_spec(asMap(r['spec']))),
                  subtitle: Text('${r['created_at']}'.replaceFirst('T', ' ').split('.').first +
                      (r['message'] != null ? '\n${r['message']}' : '')),
                  trailing: Text(_label[r['status']] ?? '${r['status']}'),
                )),
          ]),
        );
      },
    );
  }
}
