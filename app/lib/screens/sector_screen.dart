import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../live.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';
import 'stock_detail_screen.dart';

class SectorListScreen extends StatefulWidget {
  const SectorListScreen({super.key});

  @override
  State<SectorListScreen> createState() => _SectorListScreenState();
}

class _SectorListScreenState extends State<SectorListScreen> {
  late Future<Json> _f = Api.sectors();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(
          title: const LogoTitle('업종 · 테마 강도'),
          actions: topActions(context, onRefresh: () => setState(() => _f = Api.sectors()))),
      body: Loader<Json>(
        future: _f,
        builder: (context, d) {
          final list = asList(d['sectors']);
          return ListView.separated(
            padding: const EdgeInsets.all(8),
            itemCount: list.length + 1,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              if (i == 0) {
                return Padding(
                  padding: const EdgeInsets.all(8),
                  child: Text('당일 = 업종 전체 종목의 시가총액 가중 등락 (HTS 업종지수와 같은 방식). '
                      '점수 = 당일·5일 등락, 상승 종목 비율, 거래대금 증가, 외국인+기관 순매수, 고점 돌파 비율을 '
                      '업종끼리 비교한 순위 (0~100)', style: Theme.of(context).textTheme.bodySmall),
                );
              }
              final g = list[i - 1];
              return ListTile(
                leading: SizedBox(width: 28, child: Text('$i', textAlign: TextAlign.center)),
                title: Text('${g['group']}'),
                subtitle: Text('${g['type'] == 'theme' ? '테마' : 'KRX 업종'} · ${g['members']}종목'
                    '${g['up'] != null ? ' (상승 ${g['up']} · 하락 ${g['down']})' : ''} · '
                    '당일 ${pct(g['ret1_pct'] as num)} · 5일 ${pct(g['ret5_pct'] as num)}'),
                trailing: Text('${g['score']}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => SectorDetailScreen(g: g))),
              );
            },
          );
        },
      ),
    );
  }
}

/// 업종(테마) 상세: 오늘(1시간마다) · 전일 마감 요약 + 업종 전체 종목 (지금 시세 · 전일 등락 · 시가총액)
class SectorDetailScreen extends StatefulWidget {
  const SectorDetailScreen({super.key, required this.g});
  final Json g;

  @override
  State<SectorDetailScreen> createState() => _SectorDetailScreenState();
}

class _SectorDetailScreenState extends State<SectorDetailScreen> {
  List<List<dynamic>> _members = const [];
  String? _basisDate;
  Map<String, LiveQuote> _q = const {};
  bool _loading = true;
  String? _err;
  bool _byToday = true; // 정렬: 지금 등락 / 전일 등락

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final d = await Api.sectorMembers();
      final rows = (asMap(d['groups'])['${widget.g['group']}'] as List? ?? const []).map((e) => List<dynamic>.from(e as List)).toList();
      Map<String, LiveQuote> q = const {};
      if (rows.isNotEmpty) {
        try {
          q = (await Live.stocks([for (final r in rows) '${r[0]}'])).quotes;
        } catch (_) {}
      }
      if (!mounted) return;
      setState(() {
        _members = rows;
        _basisDate = d['date'] as String?;
        _q = q;
        _loading = false;
        _err = rows.isEmpty ? '전체 종목 목록이 아직 없어요 (오늘 저녁 배치 뒤부터 나와요)' : null;
      });
    } catch (e) {
      if (mounted) setState(() {
        _loading = false;
        _err = '$e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final g = widget.g;
    final t = Theme.of(context).textTheme;
    final today = asMap(g['today']);
    final top = asList(g['top']);
    final rows = List<List<dynamic>>.from(_members);
    double? nowChg(List r) => _q['${r[0]}']?.ratio;
    double prevChg(List r) => (r[2] as num?)?.toDouble() ?? -999;
    if (_byToday && _q.isNotEmpty) {
      rows.sort((a, b) => (nowChg(b) ?? -999).compareTo(nowChg(a) ?? -999));
    } else {
      rows.sort((a, b) => prevChg(b).compareTo(prevChg(a)));
    }
    // 지금 시세로 다시 계산한 업종 전체 (시가총액 가중 · 단순 평균 · 상승/하락)
    double sw = 0, sr = 0, se = 0;
    int n = 0, up = 0, down = 0;
    for (final r in _members) {
      final c = nowChg(r);
      if (c == null) continue;
      final w = (r[4] as num?)?.toDouble() ?? 0;
      n++;
      se += c;
      if (c > 0) up++;
      if (c < 0) down++;
      if (w > 0) {
        sw += w;
        sr += w * c;
      }
    }
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(title: LogoTitle('${g['group']}'), actions: topActions(context, onRefresh: _load)),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(children: [
                  if (n > 0) ...[
                    _kv('지금 (업종 전체 $n종목 · 시가총액 가중)', sw > 0 ? pct(sr / sw) : '-', bold: true),
                    _kv('지금 단순 평균 · 상승/하락', '${pct(se / n)} · $up / $down'),
                  ] else if (today.isNotEmpty) ...[
                    _kv('오늘 ${g['today_time'] ?? ''} (시가총액 가중)', pct(today['chg_pct'] as num), bold: true),
                    if (today['eq_pct'] != null)
                      _kv('오늘 단순 평균 · 상승/하락', '${pct(today['eq_pct'] as num)} · ${today['up'] ?? '-'} / ${today['down'] ?? '-'}'),
                  ],
                  if (g['ret1_pct'] != null) ...[
                    const Divider(),
                    _kv('전일 마감 (${g['basis'] == 'eq' ? '단순 평균' : '시가총액 가중'})', pct(g['ret1_pct'] as num)),
                    if (g['ret1_eq_pct'] != null)
                      _kv('전일 단순 평균 · 상승/하락', '${pct(g['ret1_eq_pct'] as num)} · ${g['up'] ?? '-'} / ${g['down'] ?? '-'}'),
                    _kv('5일 등락 (중앙값)', pct(g['ret5_pct'] as num)),
                    _kv('거래대금 (20일 평균 대비)', '${g['money_ratio']}배'),
                    if (g['score'] != null) _kv('강도 점수', '${g['score']} / 100'),
                  ],
                ]),
              ),
            ),
            SectionTitle('업종 전체 종목 ${_members.isEmpty ? '' : '${_members.length}'}',
                trailing: _q.isEmpty
                    ? null
                    : TextButton(
                        onPressed: () => setState(() => _byToday = !_byToday),
                        child: Text(_byToday ? '지금 등락순' : '전일 등락순'))),
            if (_loading)
              const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()))
            else if (_err != null) ...[
              Padding(padding: const EdgeInsets.all(8), child: Text(_err!, style: t.bodySmall)),
              // 목록이 아직 없으면 예전 대표 종목이라도
              ...top.map((m) => ListTile(
                    dense: true,
                    title: Text('${m['name']}'),
                    subtitle: Text('전일 ${pct(m['ret1'] as num)}'),
                    onTap: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${m['code']}', name: '${m['name']}'))),
                  )),
            ] else ...[
              Text('${_basisDate ?? ''} 기준 업종 분류 · 지금 = 네이버 시세 · 시가총액(억)',
                  style: t.bodySmall?.copyWith(color: Colors.grey)),
              for (final r in rows)
                ListTile(
                  dense: true,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                  title: Text('${r[1]}', overflow: TextOverflow.ellipsis),
                  subtitle: Text('${r[0]} · 시총 ${r[4] == null ? '-' : num0(r[4] as num)}억'
                      ' · 전일 ${r[2] == null ? '-' : pct(r[2] as num)}'),
                  trailing: nowChg(r) == null
                      ? null
                      : Text(pct(nowChg(r)!),
                          style: TextStyle(fontWeight: FontWeight.bold, color: nowChg(r)! >= 0 ? upColor : downColor)),
                  onTap: () => Navigator.push(context,
                      MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${r[0]}', name: '${r[1]}'))),
                ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _kv(String k, String v, {bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(k)),
          Text(v, style: TextStyle(fontWeight: bold ? FontWeight.bold : FontWeight.w600)),
        ]),
      );
}
