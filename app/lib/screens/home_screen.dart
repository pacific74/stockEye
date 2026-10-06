import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import 'candidate_list_screen.dart';
import 'orders_screen.dart';
import 'portfolio_screen.dart';
import 'search_screen.dart';
import 'sector_screen.dart';

/// 메인 화면: 오늘의 시장 → 돈이 몰리는 업종 → TOP 10 → 후보 바로가기
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<Json> _f = Api.dashboard();

  void _reload() => setState(() => _f = Api.dashboard());

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(mainAxisSize: MainAxisSize.min, children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Image.asset('assets/icon/logo_256.png', width: 28, height: 28),
          ),
          const SizedBox(width: 8),
          const Text('StockEye', style: TextStyle(fontWeight: FontWeight.bold)),
        ]),
        actions: [
          IconButton(
              icon: const Icon(Icons.search),
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SearchScreen()))),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _reload),
          if (useCloud)
            PopupMenuButton<String>(
              onSelected: (v) async {
                if (v == 'logout') await Supabase.instance.client.auth.signOut();
              },
              itemBuilder: (_) => [
                PopupMenuItem(
                    enabled: false,
                    child: Text(Supabase.instance.client.auth.currentUser?.email ?? '',
                        style: Theme.of(context).textTheme.bodySmall)),
                const PopupMenuItem(value: 'logout', child: Text('로그아웃')),
              ],
            ),
        ],
      ),
      body: Loader<Json>(
        future: _f,
        onRetry: _reload,
        builder: (context, d) {
          final m = asMap(d['market']);
          final sectors = asList(d['sectors']);
          final top10 = asList(d['top10']);
          final strat = asMap(d['strategies']);
          return RefreshIndicator(
            onRefresh: () async => _reload(),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 32),
              children: [
                Text('${d['date']} 장 마감 기준', style: Theme.of(context).textTheme.bodySmall),
                const _TradingBanner(),
                const SectionTitle('오늘의 시장'),
                _MarketCard(m: m),
                SectionTitle('돈이 몰리는 업종',
                    trailing: TextButton(
                        onPressed: () =>
                            Navigator.push(context, MaterialPageRoute(builder: (_) => const SectorListScreen())),
                        child: const Text('전체'))),
                ...sectors.take(6).toList().asMap().entries.map((e) => _SectorRow(rank: e.key + 1, g: e.value)),
                const SectionTitle('오늘의 TOP 10'),
                ...top10.map((c) => CandidateTile(c: c)),
                const SectionTitle('후보 보기'),
                _ShortcutGrid(strat: strat),
                const SizedBox(height: 16),
                Text('규칙 기반 분석 결과이며 투자 권유가 아닙니다. 최종 판단과 책임은 본인에게 있습니다.',
                    style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _MarketCard extends StatelessWidget {
  const _MarketCard({required this.m});
  final Json m;

  @override
  Widget build(BuildContext context) {
    final idx = asList(m['indices']);
    final mood = m['mood'] as String;
    final moodColor = mood == '강세' ? upColor : (mood == '약세' ? downColor : Colors.orange);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(children: [
          ...idx.map((i) {
            final ch = (i['change_pct'] as num).toDouble();
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                Expanded(child: Text(i['code'] as String, style: const TextStyle(fontWeight: FontWeight.w600))),
                Text(num0(i['close'] as num)),
                const SizedBox(width: 12),
                SizedBox(
                  width: 70,
                  child: Text(pct(ch),
                      textAlign: TextAlign.right,
                      style: TextStyle(color: ch >= 0 ? upColor : downColor, fontWeight: FontWeight.bold)),
                ),
              ]),
            );
          }),
          const Divider(),
          Row(children: [
            const Expanded(child: Text('시장 분위기')),
            Text('${m['mood_icon']} $mood',
                style: TextStyle(color: moodColor, fontWeight: FontWeight.bold, fontSize: 16)),
          ]),
          const SizedBox(height: 4),
          Row(children: [
            Expanded(
                child: Text('상승 ${m['advancers']} · 하락 ${m['decliners']} · 20일선 위 ${m['above_sma20_pct']}%',
                    style: Theme.of(context).textTheme.bodySmall)),
          ]),
        ]),
      ),
    );
  }
}

class _SectorRow extends StatelessWidget {
  const _SectorRow({required this.rank, required this.g});
  final int rank;
  final Json g;

  @override
  Widget build(BuildContext context) {
    final arrows = g['arrows'] as String;
    final up = !arrows.contains('↓');
    return ListTile(
      dense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 8),
      leading: Text('$rank', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
      title: Text('${g['group']}', style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(asList(g['top']).take(3).map((t) => t['name']).join(' · '), maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        Text(arrows, style: TextStyle(color: up ? upColor : downColor, fontSize: 16)),
        const SizedBox(width: 8),
        Text('${g['score']}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
      ]),
      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => SectorDetailScreen(g: g))),
    );
  }
}

class _ShortcutGrid extends StatelessWidget {
  const _ShortcutGrid({required this.strat});
  final Json strat;

  @override
  Widget build(BuildContext context) {
    final items = <(String, String, IconData, int?)>[
      ('overall', '상승 후보', Icons.trending_up, null),
      ('A', '돌파 후보', Icons.rocket_launch, _count('A')),
      ('B', '눌림목 후보', Icons.south_east, _count('B')),
      ('C', '급등 초기 후보', Icons.bolt, _count('C')),
      ('D', '수급 후보', Icons.groups, _count('D')),
      ('E', '저평가 전환', Icons.savings, _count('E')),
    ];
    return Wrap(spacing: 8, runSpacing: 8, children: [
      ...items.map((it) => ActionChip(
            avatar: Icon(it.$3, size: 18),
            label: Text(it.$4 == null ? it.$2 : '${it.$2} ${it.$4}'),
            onPressed: () => Navigator.push(
                context, MaterialPageRoute(builder: (_) => CandidateListScreen(list: it.$1, title: it.$2))),
          )),
      ActionChip(
        avatar: const Icon(Icons.account_balance_wallet, size: 18),
        label: const Text('보유종목 관리'),
        onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const PortfolioScreen())),
      ),
    ]);
  }

  int? _count(String k) => strat[k] == null ? null : (asMap(strat[k])['count'] as int?);
}


/// 매매 모드 + 승인 대기 주문 알림
class _TradingBanner extends StatelessWidget {
  const _TradingBanner();

  static const _modeNames = {'alert': '알림만', 'paper': '모의투자 자동', 'semi_auto': '반자동 (승인 후 주문)'};

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Json>(
      future: Api.tradingStatus(),
      builder: (context, snap) {
        if (!snap.hasData) return const SizedBox.shrink();
        final t = snap.data!;
        final pending = t['pending_orders'] as int? ?? 0;
        return Card(
          color: pending > 0 ? Colors.orange.withValues(alpha: 0.15) : null,
          child: ListTile(
            dense: true,
            leading: Icon(pending > 0 ? Icons.notifications_active : Icons.sensors,
                color: pending > 0 ? Colors.orange : null),
            title: Text(pending > 0 ? '승인 대기 주문 $pending건' : '매매 모드: ${_modeNames[t['mode']] ?? t['mode']}'),
            subtitle: Text('보유 ${t['open_positions']}종목 · 알림 ${List<String>.from(t['notify_channels'] as List).join(', ')}'
                '${t['mode'] == 'paper' ? ' · 모의 현금 ${won(t['paper_cash'] as num?)}' : ''}'),
            trailing: pending > 0 ? const Icon(Icons.chevron_right) : null,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const OrdersScreen())),
          ),
        );
      },
    );
  }
}
