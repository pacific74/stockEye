import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';

/// 5단계 반자동 매매: 신호 → 알림 → [여기서 승인] → 주문
class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  late Future<List<Json>> _f = Api.orders();
  final Set<String> _busy = {};

  void _reload() => setState(() => _f = Api.orders());

  Future<void> _act(Json o, bool approve) async {
    final id = o['id'] as String;
    if (approve) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('${o['side'] == 'buy' ? '매수' : '매도'} 주문을 낼까요?'),
          content: Text('${o['name']} ${(o['qty'] as num).toStringAsFixed(0)}주 · 신호가 ${won(o['price'] as num?)}\n'
              '${o['mode'] == 'real' ? '⚠ 실전 계좌 주문입니다.' : '모의 계좌 주문입니다.'}\n'
              '승인 시점의 현재가로 다시 확인한 뒤 지정가로 주문합니다.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('승인')),
          ],
        ),
      );
      if (ok != true) return;
    }
    setState(() => _busy.add(id));
    try {
      final r = approve ? await Api.approveOrder(id) : await Api.rejectOrder(id);
      if (mounted) {
        final msg = r['ok'] == true
            ? (r['queued'] == true
                ? '${r['message']}'
                : (approve ? '체결: ${won(r['price'] as num?)} × ${(r['qty'] as num?)?.toStringAsFixed(0) ?? ''}주' : '거절했습니다'))
            : '${r['message']}';
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      _busy.remove(id);
      _reload();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(title: const LogoTitle('승인 대기 주문'), actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _reload),
      ]),
      body: Loader<List<Json>>(
        future: _f,
        onRetry: _reload,
        builder: (context, rows) {
          if (rows.isEmpty) {
            return const Center(child: Text('승인 대기 중인 주문이 없습니다'));
          }
          return ListView(
            padding: const EdgeInsets.all(12),
            children: rows.map((o) {
              final buy = o['side'] == 'buy';
              final snap = asMap(o['snapshot'] ?? {});
              final plan = snap['plan'] == null ? null : asMap(snap['plan']);
              final id = o['id'] as String;
              return Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Text(buy ? '매수' : '매도',
                          style: TextStyle(color: buy ? upColor : downColor, fontWeight: FontWeight.bold, fontSize: 16)),
                      const SizedBox(width: 8),
                      Expanded(child: Text('${o['name']}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
                      Text('${o['reason'] ?? ''}', style: Theme.of(context).textTheme.bodySmall),
                    ]),
                    const SizedBox(height: 6),
                    Text('${(o['qty'] as num).toStringAsFixed(0)}주 · 신호가 ${won(o['price'] as num?)} · ${o['mode']}'),
                    if (plan != null)
                      Text('손절 ${won(plan['stop'] as num?)} · 1차 ${won(plan['target1'] as num?)} · '
                          '점수 ${(snap['score'] as num?)?.toStringAsFixed(0) ?? '-'}',
                          style: Theme.of(context).textTheme.bodySmall),
                    Text('만료 ${o['expires_at'] ?? '-'}', style: Theme.of(context).textTheme.bodySmall),
                    const SizedBox(height: 8),
                    if (_busy.contains(id))
                      const LinearProgressIndicator()
                    else
                      Row(children: [
                        Expanded(child: OutlinedButton(onPressed: () => _act(o, false), child: const Text('거절'))),
                        const SizedBox(width: 8),
                        Expanded(child: FilledButton(onPressed: () => _act(o, true), child: const Text('승인'))),
                      ]),
                  ]),
                ),
              );
            }).toList(),
          );
        },
      ),
    );
  }
}
