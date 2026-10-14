import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets/common.dart';

/// 관심종목 적중률 (HIT-1.0) — 검증 탭 맨 위
///   탭마다 매일 점수 상위 3 → 다음 날 시가 매수 → 20거래일 안에 1·2·3차 목표 / 손절 / 보합
///   연도별 표(승률 · 평균 손익) → 연도를 누르면 분기, 칸(1·2·3차·손절)을 누르면 며칠째에 닿았는지 1~20일 분포
Future<Json> loadHitRate() => Api.latestBacktest(strategy: 'HIT');

const _cols = [('t1', '1차'), ('t2', '2차'), ('t3', '3차'), ('stop', '손절'), ('flat', '보합')];
const _tabList = [('v3', 'V3'), ('nextday', '유망주'), ('early', '상승초기'), ('reversal', '추세전환'), ('uplimit', '상파')];

Color _colOf(String k) => switch (k) {
      't1' || 't2' || 't3' => const Color(0xFFD32F2F),
      'stop' => const Color(0xFF1565C0),
      _ => Colors.grey,
    };

class HitRateSection extends StatefulWidget {
  const HitRateSection({super.key, required this.future});
  final Future<Json> future;

  @override
  State<HitRateSection> createState() => _HitRateSectionState();
}

class _HitRateSectionState extends State<HitRateSection> {
  String _tab = 'v3';
  final Set<String> _open = {}; // 펼친 연도

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return FutureBuilder<Json>(
      future: widget.future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
        }
        final r = snap.data;
        final tabs = asMap(r?['tabs']);
        if (r == null || tabs.isEmpty) {
          return Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text('아직 적중률 결과가 없어요. 위의 [전체 계산 요청]을 누르면 계산해요 (약 45분). '
                  '(GitHub Actions → weekly-backtest → Run workflow 에서 직접 돌려도 돼요)',
                  style: t.bodySmall),
            ),
          );
        }
        if (!tabs.containsKey(_tab)) _tab = tabs.keys.first;
        final v = asMap(tabs[_tab]);
        final years = asMap(v['years']);
        final ys = years.keys.toList()..sort((a, b) => b.compareTo(a)); // 최근 연도 먼저
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SectionTitle('관심종목 적중률', trailing: Text('${r['end'] ?? ''} 기준', style: t.bodySmall)),
          Text('탭마다 매일 상위 3종목을 앱 매매 계획대로 샀다면: 1차 매수구간이면 다음 날 시가에 30%, '
              '2차·3차 매수구간 상단까지 내려오면 30%·40% 추가 → 20거래일 안에 목표가·손절가 중 어디에 닿았나. '
              '승률 = 목표 ÷ (목표 + 손절). '
              '손익 = 1차 50% · 2차 30% · 3차 20% 나눠 팔고, 1차를 판 뒤 남은 몫은 평균 매수가까지 밀리면 본전에, '
              '1차 전에는 손절가에, 끝까지 남으면 20일째 종가에 판 평균 수익 (산 금액 기준, 수수료·세금 0.25% 뺌). '
              '매수구간까지 안 내려와 못 산 건 미체결로 따로 셌어요. '
              '승률이 높아도 손익이 마이너스면 손절 한 번이 목표 여러 번을 까먹는다는 뜻이에요. '
              '연도를 누르면 분기, 숫자를 누르면 며칠째에 닿았는지 보여요.',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 4, children: [
            for (final x in _tabList)
              if (tabs.containsKey(x.$1))
                ChoiceChip(label: Text(x.$2), selected: _tab == x.$1, onSelected: (_) => setState(() => _tab = x.$1)),
          ]),
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 6, 8, 10),
              child: Column(children: [
                _header(context),
                _row(context, '전체', asMap(v['total']), bold: true, title: '${v['name']} 전체'),
                const Divider(height: 8),
                for (final y in ys) ...[
                  _row(context, y, asMap(years[y]),
                      title: '${v['name']} $y년',
                      expand: () => setState(() => _open.contains(y) ? _open.remove(y) : _open.add(y)),
                      expanded: _open.contains(y)),
                  if (_open.contains(y))
                    for (final q in const ['Q1', 'Q2', 'Q3', 'Q4'])
                      if (asMap(asMap(years[y])['quarters'])[q] != null)
                        _row(context, '  ${q.substring(1)}분기', asMap(asMap(asMap(years[y])['quarters'])[q]),
                            title: '${v['name']} $y년 ${q.substring(1)}분기', sub: true),
                  const Divider(height: 6),
                ],
              ]),
            ),
          ),
        ]);
      },
    );
  }

  Widget _header(BuildContext context) {
    final s = Theme.of(context).textTheme.labelSmall?.copyWith(fontWeight: FontWeight.bold);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        SizedBox(width: 52, child: Text('년도', style: s)),
        for (final c in _cols) Expanded(flex: 5, child: Text(c.$2, textAlign: TextAlign.right, style: s)),
        Expanded(flex: 5, child: Text('승률', textAlign: TextAlign.right, style: s)),
        Expanded(flex: 6, child: Text('손익', textAlign: TextAlign.right, style: s)),
      ]),
    );
  }

  /// 한 줄: 연도(또는 분기) · 1·2·3차 · 손절 · 보합 · 승률, 아래에 코스피 등락·이슈
  Widget _row(BuildContext context, String label, Json s,
      {bool bold = false, bool sub = false, String title = '', VoidCallback? expand, bool expanded = false}) {
    final t = Theme.of(context).textTheme;
    if ((s['n'] ?? 0) == 0) return const SizedBox.shrink();
    final base = t.bodySmall?.copyWith(fontSize: sub ? 11 : 12.5, fontWeight: bold ? FontWeight.bold : null);
    final pnl = s['pnl'] as num?;
    final issue = s['issue'] as String?;
    final kospi = s['kospi'] as num?;
    return InkWell(
      onTap: expand,
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: sub ? 3 : 5),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            SizedBox(
              width: 52,
              child: Row(children: [
                Flexible(child: Text(label, style: base, overflow: TextOverflow.ellipsis)),
                if (expand != null) Icon(expanded ? Icons.expand_less : Icons.expand_more, size: 14, color: Colors.grey),
              ]),
            ),
            for (final c in _cols)
              Expanded(
                flex: 5,
                child: InkWell(
                  onTap: c.$1 == 'flat' ? null : () => _showDays(context, title, c.$1, c.$2, s),
                  child: Text('${(s[c.$1] as num?)?.toStringAsFixed(0) ?? '-'}%',
                      textAlign: TextAlign.right,
                      style: base?.copyWith(
                          color: _colOf(c.$1),
                          decoration: c.$1 == 'flat' ? null : TextDecoration.underline,
                          decorationStyle: TextDecorationStyle.dotted)),
                ),
              ),
            Expanded(
              flex: 5,
              child: Text(s['win'] == null ? '-' : '${(s['win'] as num).toStringAsFixed(0)}%',
                  textAlign: TextAlign.right, style: base?.copyWith(fontWeight: FontWeight.bold)),
            ),
            // 평균 손익 (30·30·40% 분할 매수 → 50·30·20% 분할 매도 + 1차 뒤 본전 손절, 비용 뺀 뒤)
            Expanded(
              flex: 6,
              child: Text(pnl == null ? '-' : '${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(1)}%',
                  textAlign: TextAlign.right,
                  style: base?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: pnl == null ? null : (pnl >= 0 ? const Color(0xFFD32F2F) : const Color(0xFF1565C0)))),
            ),
          ]),
          Padding(
              padding: const EdgeInsets.only(left: 4, top: 1),
              child: Text(
                  [
                    if (kospi != null) '코스피 ${kospi >= 0 ? '+' : ''}${kospi.toStringAsFixed(1)}%',
                    if (issue != null && issue.isNotEmpty) issue,
                    '${s['n']}건',
                    if ((s['unfilled'] as num? ?? 0) > 0) '미체결 ${s['unfilled']}',
                    if (s['filled_w'] != null && !sub) '평균 매수 ${(s['filled_w'] as num).toStringAsFixed(0)}%',
                  ].join(' · '),
                  style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: sub ? 10 : 11)),
            ),
        ]),
      ),
    );
  }

  /// 칸을 누르면: 그 결과(1·2·3차 목표 / 손절)에 처음 닿은 날 1~20일 분포
  void _showDays(BuildContext context, String title, String key, String name, Json s) {
    final days = (asMap(s['days'])[key] as List? ?? const []).map((e) => (e as num).toInt()).toList();
    final total = days.fold<int>(0, (a, b) => a + b);
    final n = (s['n'] as num?)?.toInt() ?? 0;
    final mx = days.isEmpty ? 1 : days.reduce((a, b) => a > b ? a : b).clamp(1, 1 << 30);
    final col = _colOf(key);
    final cums = <int>[];
    for (final d in days) {
      cums.add((cums.isEmpty ? 0 : cums.last) + d);
    }
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('$title · $name 에 처음 닿은 날', style: Theme.of(ctx).textTheme.titleSmall),
            Text('$n건 중 $total건 (${n == 0 ? 0 : (total / n * 100).toStringAsFixed(1)}%)',
                style: Theme.of(ctx).textTheme.bodySmall),
            const SizedBox(height: 10),
            for (var i = 0; i < days.length; i++)
              Builder(builder: (_) {
                final cum = cums[i];
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(children: [
                    SizedBox(width: 42, child: Text('${i + 1}일째', style: const TextStyle(fontSize: 12))),
                    Expanded(
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: FractionallySizedBox(
                          widthFactor: days[i] / mx,
                          child: Container(height: 12, color: col.withValues(alpha: 0.7)),
                        ),
                      ),
                    ),
                    SizedBox(
                      width: 96,
                      child: Text('${days[i]}건 · 누적 ${total == 0 ? 0 : (cum / total * 100).toStringAsFixed(0)}%',
                          textAlign: TextAlign.right, style: const TextStyle(fontSize: 11)),
                    ),
                  ]),
                );
              }),
          ]),
        ),
      ),
    );
  }
}

/// 적중률 계산 요청 (관리자) — 전체 · 탭별 · 연도별. Supabase → GitHub 'weekly-backtest' 작업에 바로 신호.
///   전체는 약 45분 (V3 를 매일 다시 계산하는 데 대부분). 일부만 돌리면 나머지 탭·연도는 이전 결과에 합쳐짐.
class HitRunCard extends StatefulWidget {
  const HitRunCard({super.key, required this.onDone});
  final VoidCallback onDone; // 계산이 끝나면 표 새로고침
  @override
  State<HitRunCard> createState() => _HitRunCardState();
}

class _HitRunCardState extends State<HitRunCard> {
  final Set<String> _tabs = {};
  final Set<int> _years = {};
  Json _job = {};
  bool _busy = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _poll();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  bool get _active => _job['status'] == 'queued' || _job['status'] == 'running';

  Future<void> _poll() async {
    final was = _active;
    final j = await Api.hitRateJob();
    if (!mounted) return;
    setState(() => _job = j);
    if (was && j['status'] == 'done') widget.onDone();
    _timer?.cancel();
    if (_active) _timer = Timer(const Duration(seconds: 30), _poll); // 계산 중이면 30초마다 상태 확인
  }

  String get _only {
    final parts = ['HIT'];
    if (_tabs.isNotEmpty) parts.add(_tabs.join(','));
    if (_years.isNotEmpty) parts.add((_years.toList()..sort()).join(','));
    return parts.join(':');
  }

  Future<void> _request() async {
    setState(() => _busy = true);
    try {
      final r = await Api.requestHitRate(_only);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(r['ok'] == true
              ? '계산을 요청했어요 (${r['only']}). 시작까지 1~2분, 전체는 45분쯤 걸려요.'
              : '${r['message'] ?? '요청하지 못했어요'} (${r['only'] ?? ''})')));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'.replaceFirst('Exception: ', ''))));
    } finally {
      if (mounted) setState(() => _busy = false);
      _poll();
    }
  }

  String _status() {
    final s = _job['status'];
    final only = _job['only'] ?? '';
    return switch (s) {
      'queued' => '대기 중 ($only) — 다른 배치가 돌고 있으면 끝난 뒤 시작해요',
      'running' => '계산 중 ($only) · ${_job['started'] ?? ''} 시작',
      'done' => '마지막 계산: $only · ${_job['finished'] ?? ''} 끝 (${_job['minutes'] ?? '-'}분)',
      'failed' => '실패 ($only): ${_job['message'] ?? ''}',
      _ => '',
    };
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final now = DateTime.now().year;
    final years = [for (var y = now - 5; y <= now; y++) y];
    final st = _status();
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Icon(Icons.play_circle_outline, size: 18),
            const SizedBox(width: 6),
            Text('적중률 다시 계산', style: t.titleSmall),
          ]),
          const SizedBox(height: 4),
          Text('아무것도 안 고르면 전체(5개 탭 × 5년, 약 45분). 탭이나 연도를 고르면 그 부분만 다시 계산해서 기존 결과에 합쳐요.',
              style: t.bodySmall?.copyWith(color: Colors.grey)),
          const SizedBox(height: 8),
          Text('탭', style: t.labelSmall),
          Wrap(spacing: 6, runSpacing: 2, children: [
            for (final x in _tabList)
              FilterChip(
                visualDensity: VisualDensity.compact,
                label: Text(x.$2),
                selected: _tabs.contains(x.$1),
                onSelected: (v) => setState(() => v ? _tabs.add(x.$1) : _tabs.remove(x.$1)),
              ),
          ]),
          const SizedBox(height: 4),
          Text('연도', style: t.labelSmall),
          Wrap(spacing: 6, runSpacing: 2, children: [
            for (final y in years)
              FilterChip(
                visualDensity: VisualDensity.compact,
                label: Text('$y'),
                selected: _years.contains(y),
                onSelected: (v) => setState(() => v ? _years.add(y) : _years.remove(y)),
              ),
          ]),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: _busy || _active ? null : _request,
              icon: _busy || _active
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.play_arrow),
              label: Text(_active
                  ? '계산 중이에요'
                  : (_tabs.isEmpty && _years.isEmpty
                      ? '전체 계산 요청'
                      : '${[
                          if (_tabs.isNotEmpty) _tabList.where((x) => _tabs.contains(x.$1)).map((x) => x.$2).join('·'),
                          if (_years.isNotEmpty) (_years.toList()..sort()).join('·'),
                        ].join(' / ')} 계산 요청')),
            ),
          ),
          if (st.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(children: [
                Expanded(child: Text(st, style: t.bodySmall?.copyWith(color: _job['status'] == 'failed' ? Colors.red : Colors.grey))),
                if (_active) IconButton(visualDensity: VisualDensity.compact, icon: const Icon(Icons.refresh, size: 18), onPressed: _poll),
              ]),
            ),
        ]),
      ),
    );
  }
}
