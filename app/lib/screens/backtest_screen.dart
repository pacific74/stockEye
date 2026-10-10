import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../v3.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'validation_screen.dart';

class BacktestScreen extends StatefulWidget {
  const BacktestScreen({super.key});

  @override
  State<BacktestScreen> createState() => _BacktestScreenState();
}

class _BacktestScreenState extends State<BacktestScreen> {
  late Future<List<Json>> _strategies = Api.strategies();
  final startCtl = TextEditingController(text: '2021-01-01');

  bool running = false;
  Map<String, dynamic>? result;
  String? error;
  String? info;
  late Future<List<Json>> _reqs = backtestRequests();
  late Future<Json> _val = loadValidation();

  @override
  void initState() {
    super.initState();
    Api.latestBacktest().then((r) {
      if (mounted) setState(() => result = r);
    }).catchError((_) {});
  }

  Future<void> _run() async {
    setState(() {
      running = true;
      error = null;
      info = null;
    });
    try {
      final r = await Api.backtest({
        'v2': true, // 매수후보 V2 엔진
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
      appBar: AppBar(
          title: const LogoTitle('검증'),
          actions: topActions(context, onRefresh: () {
            setState(() {
              _strategies = Api.strategies();
              _reqs = backtestRequests();
              _val = loadValidation();
            });
            Api.latestBacktest().then((r) {
              if (mounted) setState(() => result = r);
            }).catchError((_) {});
          })),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
        children: [
          // ---- 관심종목 검증 (5개 탭 공통 기준) ----
          ValidationList(future: _val),
          const SectionTitle('직접 백테스트'),
          Card(
            color: Colors.teal.withValues(alpha: 0.08),
            child: ListTile(
              leading: const Icon(Icons.lock_outline, color: Colors.teal),
              title: const Text('V3 기준 전략 검증', style: TextStyle(fontWeight: FontWeight.bold)),
              subtitle: const Text('① 종목 선정력 (상위10 · 후보 전체 · 랜덤10)과 ② 실제 매매 (PF · 기대값 · MDD · CAGR)를 나눠서'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const V3Screen())),
            ),
          ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('매수후보 V2 엔진', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text('시장 → 업종 → 재무·공시 위험 → 기술 → 100점 → 가격위치 → 과열 → 매수 신호. '
                    '분할 매수 30/30/40, 익절 +8%(절반)·+15%·20일선 이탈, 하락장 신규 매수 중단. '
                    '매주 토요일 자동으로 다시 검증합니다.',
                    style: Theme.of(context).textTheme.bodySmall),
                const SizedBox(height: 8),
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
            _kv('같은 기간 KOSPI', pct(m['benchmark_return_pct'] as num?)),
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
    if (s['v2'] == true) return 'V2 엔진 (${s['start'] ?? '처음'}부터)';
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
