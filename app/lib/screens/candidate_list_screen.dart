import 'package:flutter/material.dart';

import '../api.dart';
import '../live.dart';
import '../nextday.dart';
import '../reversal.dart';
import '../today_picks.dart';
import '../v3.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';

/// 전략별 후보 목록 (탭으로 전환)
class CandidateListScreen extends StatefulWidget {
  const CandidateListScreen({super.key, this.list = 'overall', this.title = '후보'});
  final String list;
  final String title;

  // v3 = V3 기준 전략 (🔒 고정) / now = 오늘 지금 가격 기준 / signal·buy·watch = 매수후보 V2 (참고)
  // nextday = 익일 유망주 (실험 탭 · 60점 이상) / early = 상승초기 (실험 탭 · 60점 이상) / reversal = 추세전환 (실험 탭 · 70점 이상)
  static const keys = ['v3', 'nextday', 'early', 'reversal']; // V2 목록(지금 매수구간·매수 신호·강력 후보·관심)은 숨김

  @override
  State<CandidateListScreen> createState() => _CandidateListScreenState();
}

class _CandidateListScreenState extends State<CandidateListScreen> {
  int _gen = 0; // 새로고침할 때마다 +1

  @override
  Widget build(BuildContext context) {
    const keys = CandidateListScreen.keys;
    final list = widget.list;
    return DefaultTabController(
      length: keys.length,
      initialIndex: keys.contains(list) ? keys.indexOf(list) : 0,
      child: Scaffold(
        appBar: AppBar(
          title: const LogoTitle('매수 후보'),
          actions: topActions(context, onRefresh: () => setState(() => _gen++)),
          bottom: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: keys.map((k) => Tab(text: strategyLabels[k])).toList(),
          ),
        ),
        body: TabBarView(
            children: keys
                .map((k) => k == 'now'
                    ? _NowTab(key: ValueKey('now$_gen'))
                    : _ListTab(key: ValueKey('$k$_gen'), listKey: k))
                .toList()),
      ),
    );
  }
}

class _ListTab extends StatefulWidget {
  const _ListTab({super.key, required this.listKey});
  final String listKey;

  @override
  State<_ListTab> createState() => _ListTabState();
}

enum _Sort { score, strategy, rank }

/// 목록마다 최대 몇 개까지 보여줄지
const maxShow = 10;

class _ListTabState extends State<_ListTab> with AutomaticKeepAliveClientMixin {
  late Future<Json> _f = _loadQ();

  /// 후보 + 상위 종목 지금 시세 (매수구간 여부·지금 사면 목표/손절 계산용)
  Future<Json> _loadQ() async {
    final d = await Api.candidates(widget.listKey);
    final codes = sortByScore(asList(d['candidates'])).take(maxShow).map((c) => '${c['code']}').toList();
    try {
      d['_quotes'] = (await Live.stocks(codes)).quotes;
    } catch (_) {}
    return d;
  }
  _Sort _sort = _Sort.score; // 기본: 종합 점수 높은 순

  bool get _isStrategy => const ['A', 'B', 'C', 'D', 'E'].contains(widget.listKey); // (예전 V1 전략)

  List<Json> _sorted(List<Json> cands) {
    final out = List<Json>.from(cands);
    double v(Json c, String k) => (c[k] as num?)?.toDouble() ?? -1;
    switch (_sort) {
      case _Sort.score:
        out.sort((a, b) => v(b, 'score').compareTo(v(a, 'score')));
        break;
      case _Sort.strategy:
        out.sort((a, b) => v(b, 'strategy_score').compareTo(v(a, 'strategy_score')));
        break;
      case _Sort.rank:
        out.sort((a, b) => v(a, 'rank').compareTo(v(b, 'rank')));
        break;
    }
    return out;
  }

  static String _md(String ymd) {
    final t = DateTime.tryParse(ymd);
    return t == null ? ymd : '${t.month}/${t.day}';
  }

  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Loader<Json>(
      future: _f,
      onRetry: () => setState(() => _f = _loadQ()),
      builder: (context, d) {
        final rev = widget.listKey == 'reversal';
        final early = widget.listKey == 'early';
        final nextd = widget.listKey == 'nextday';
        final all = widget.listKey == 'v3' || rev || early || nextd ? sortByScore(asList(d['candidates'])) : _sorted(asList(d['candidates']));
        final cands = all.take(maxShow).toList(); // 정렬한 뒤 상위 10개만 (모든 탭)
        final qs = d['_quotes'] is Map ? d['_quotes'] as Map : const {};
        double? px(Json c) => (qs['${c['code']}'] as LiveQuote?)?.price;
        return ListView(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 0, 4, 4),
              child: Text(
                  '${d['date'] == null ? '최근' : _md('${d['date']}')} '
                  '${d['intraday'] != null ? '${d['intraday']} 장중 분석 (지금 가격 반영, 수급은 어제까지)' : '장 마감 분석'} · '
                  '${all.length > cands.length ? '조건 통과 ${all.length}개 중 ' : ''}상위 ${cands.length}개',
                  style: Theme.of(context).textTheme.bodySmall),
            ),
            // (전략 설명 카드 · 선정일/등급 요약 줄은 뺌 — 목록만)
            if (_isStrategy && cands.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: SegmentedButton<_Sort>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: _Sort.score, label: Text('종합점수순')),
                    ButtonSegment(value: _Sort.strategy, label: Text('전략점수순')),
                    ButtonSegment(value: _Sort.rank, label: Text('추천순')),
                  ],
                  selected: {_sort},
                  onSelectionChanged: (v) => setState(() => _sort = v.first),
                ),
              ),
            if (cands.isEmpty)
              Padding(
                  padding: const EdgeInsets.all(32),
                  child: Center(
                      child: Text(
                          widget.listKey == 'signal'
                              ? '오늘은 매수 신호가 없습니다.\n무리해서 살 필요 없는 날일 수 있어요.'
                              : '오늘 조건을 만족한 종목이 없습니다',
                          textAlign: TextAlign.center))),
            if (rev && cands.isNotEmpty && cands.last['reversal'] is Map && ((asMap(cands.last['reversal'])['score'] as num?) ?? 100) < 70)
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 4),
                child: Text('오늘 70점 이상이 적어 60점대(근접)도 같이 보여줍니다.', style: Theme.of(context).textTheme.bodySmall),
              ),
            if (widget.listKey == 'v3')
              ...cands.asMap().entries.map((e) => V3PickTile(c: e.value, rank: e.key + 1, price: px(e.value)))
            else if (rev)
              ...cands.asMap().entries.map((e) => ReversalTile(c: e.value, rank: e.key + 1, price: px(e.value)))
            else if (early)
              ...cands.asMap().entries.map((e) => ReversalTile(c: e.value, rank: e.key + 1, kind: earlyKind, price: px(e.value)))
            else if (nextd)
              ...cands.asMap().entries.map((e) => NextdayTile(c: e.value, rank: e.key + 1, price: px(e.value)))
            else
            ...cands.asMap().entries.map((e) => CandidateTile(
                c: e.value,
                rank: e.key + 1,
                showStrategyScore: _isStrategy,
                bigStrategy: _sort == _Sort.strategy)),
          ],
        );
      },
    );
  }
}


/// 오늘 지금 가격 기준: 어제 분석 후보 중 지금 매수구간 근처인 종목 (최대 10개)
class _NowTab extends StatefulWidget {
  const _NowTab({super.key});

  @override
  State<_NowTab> createState() => _NowTabState();
}

class _NowTabState extends State<_NowTab> with AutomaticKeepAliveClientMixin {
  late Future<(List<Json>, LiveResult, Set<String>)> _f = _load();

  Future<(List<Json>, LiveResult, Set<String>)> _load() async {
    final r = await Future.wait([Api.allCandidates(), Api.dashboard(), Live.indices()]);
    final pool = r[0] as List<Json>;
    final weak = weakMarkets(asMap((r[1] as Json)['market']), (r[2] as LiveResult).quotes);
    final live = await Live.stocks(pool.map((c) => '${c['code']}').toList());
    return (pool, live, weak);
  }

  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final t = Theme.of(context).textTheme;
    return Loader<(List<Json>, LiveResult, Set<String>)>(
      future: _f,
      onRetry: () => setState(() => _f = _load()),
      builder: (context, d) {
        final (pool, live, weak) = d;
        final picks = todayPicks(pool, live.quotes, limit: maxShow, weak: weak);
        final at = live.fetchedAt;
        return RefreshIndicator(
          onRefresh: () async {
            setState(() => _f = _load());
            await _f;
          },
          child: ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('오늘 살 만한 후보 · 지금 가격 기준${at == null ? '' : ' (${at.hour}:${at.minute.toString().padLeft(2, '0')})'}',
                        style: const TextStyle(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 4),
                    const Text('어제 장 마감 분석의 모든 후보(종합·전략별) 중에서 지금 가격이 매수 적정구간 안이거나 '
                        '바로 근처인 종목만 골랐습니다. 구간 안 → 점수 높은 순.'),
                    const SizedBox(height: 4),
                    Text('※ 손절가 아래 · 1차 목표 도달 · 오늘 +15% 이상 급등 · -5% 이상 급락 종목은 뺐습니다. '
                        '점수는 어제 마감 기준이며 장중 거래량·수급은 반영되지 않습니다.',
                        style: t.bodySmall),
                    if (weak.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text('시장 필터: ${weak.map(marketName).join('·')} 지수가 60일선 아래 → 그 시장 종목은 제외했습니다.',
                          style: t.bodySmall?.copyWith(color: Colors.orange)),
                    ],
                  ]),
                ),
              ),
              if (live.quotes.isEmpty)
                Padding(
                    padding: const EdgeInsets.all(24),
                    child: Center(child: Text('지금 시세를 받지 못했습니다.\n${live.error ?? ''}', textAlign: TextAlign.center)))
              else if (picks.isEmpty)
                const Padding(
                    padding: EdgeInsets.all(32),
                    child: Center(child: Text('지금 매수구간에 들어온 후보가 없습니다', textAlign: TextAlign.center)))
              else
                ...picks.asMap().entries.map((e) => TodayPickTile(p: e.value, rank: e.key + 1)),
            ],
          ),
        );
      },
    );
  }
}
