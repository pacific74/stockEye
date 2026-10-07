import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../format.dart';
import '../widgets/common.dart';
import '../widgets/nav.dart';
import 'stock_detail_screen.dart';

class PortfolioScreen extends StatefulWidget {
  const PortfolioScreen({super.key});

  @override
  State<PortfolioScreen> createState() => _PortfolioScreenState();
}

class _PortfolioScreenState extends State<PortfolioScreen> {
  late Future<List<Json>> _f = Api.portfolioReview();

  void _reload() => setState(() => _f = Api.portfolioReview());

  Color _statusColor(String s) {
    switch (s) {
      case '손절 검토':
        return downColor;
      case '익절 검토':
        return upColor;
      case '주의':
      case '확인 필요':
        return Colors.orange;
      default:
        return Colors.green;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const LogoTitle('보유종목 관리'), actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _reload),
      ]),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('추가'),
        onPressed: () async {
          await showAddHoldingDialog(context);
          _reload();
        },
      ),
      body: Loader<List<Json>>(
        future: _f,
        onRetry: _reload,
        builder: (context, rows) {
          if (rows.isEmpty) {
            return const Center(child: Text('보유종목이 없습니다.\n종목 상세 화면이나 + 버튼으로 추가하세요.', textAlign: TextAlign.center));
          }
          return ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 88),
            children: rows.map((h) {
              final alerts = List<String>.from(h['alerts'] as List? ?? []);
              final pnl = (h['pnl_pct'] as num?)?.toDouble();
              final status = h['status'] as String? ?? '';
              return Card(
                child: InkWell(
                  onTap: () => Navigator.push(context,
                      MaterialPageRoute(builder: (_) => StockDetailScreen(code: h['code'] as String, name: '${h['name']}'))),
                  onLongPress: () async {
                    final ok = await showDialog<bool>(
                      context: context,
                      builder: (_) => AlertDialog(
                        title: Text('${h['name']} 삭제할까요?'),
                        actions: [
                          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('취소')),
                          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('삭제')),
                        ],
                      ),
                    );
                    if (ok == true) {
                      await Api.deleteHolding(h['id'].toString());
                      _reload();
                    }
                  },
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        Expanded(child: Text('${h['name']}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(
                              color: _statusColor(status).withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8)),
                          child: Text(status, style: TextStyle(color: _statusColor(status), fontSize: 12)),
                        ),
                      ]),
                      const SizedBox(height: 6),
                      Row(children: [
                        Expanded(child: Text('평단 ${won(h['avg_price'] as num?)} → 현재 ${won(h['price'] as num?)}')),
                        Text(pct(pnl),
                            style: TextStyle(
                                fontWeight: FontWeight.bold, color: (pnl ?? 0) >= 0 ? upColor : downColor)),
                      ]),
                      Text('손절 ${won(h['stop'] as num?)} · 목표 ${won(h['target'] as num?)}'
                          '${h['today_score'] != null ? ' · 오늘 점수 ${(h['today_score'] as num).toStringAsFixed(0)}' : ''}',
                          style: Theme.of(context).textTheme.bodySmall),
                      ...alerts.map((a) => Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text('⚠ $a', style: const TextStyle(color: Colors.orange)),
                          )),
                      Row(children: [
                        Text('${h['mode'] ?? ''}', style: Theme.of(context).textTheme.bodySmall),
                        const Spacer(),
                        TextButton.icon(
                          icon: const Icon(Icons.sell_outlined, size: 18),
                          label: const Text('매도 기록'),
                          onPressed: () async {
                            final done = await _closeDialog(context, h);
                            if (done) _reload();
                          },
                        ),
                      ]),
                    ]),
                  ),
                ),
              );
            }).toList(),
          );
        },
      ),
    );
  }
}

Future<void> showAddHoldingDialog(BuildContext context,
    {String? code, String? name, double? price, double? stop, double? target, String? strategy}) async {
  final codeC = TextEditingController(text: code ?? '');
  final qtyC = TextEditingController();
  final priceC = TextEditingController(text: price?.toStringAsFixed(0) ?? '');
  final stopC = TextEditingController(text: stop?.toStringAsFixed(0) ?? '');
  final targetC = TextEditingController(text: target?.toStringAsFixed(0) ?? '');
  final digits = [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))];
  final saved = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(name == null ? '보유종목 추가' : '$name 보유 추가'),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: codeC, decoration: const InputDecoration(labelText: '종목코드 (6자리)')),
          TextField(controller: qtyC, decoration: const InputDecoration(labelText: '수량'), inputFormatters: digits),
          TextField(controller: priceC, decoration: const InputDecoration(labelText: '평균 매수가'), inputFormatters: digits),
          TextField(controller: stopC, decoration: const InputDecoration(labelText: '손절가'), inputFormatters: digits),
          TextField(controller: targetC, decoration: const InputDecoration(labelText: '목표가'), inputFormatters: digits),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('저장')),
      ],
    ),
  );
  if (saved != true) return;
  final now = DateTime.now().toIso8601String().substring(0, 16).replaceFirst('T', ' ');
  try {
    await Api.addHolding({
      'code': codeC.text.trim(),
      'name': name,
      'qty': double.tryParse(qtyC.text) ?? 0,
      'avg_price': double.tryParse(priceC.text) ?? 0,
      'buy_date': now,
      'stop': double.tryParse(stopC.text),
      'target': double.tryParse(targetC.text),
      'strategy': strategy,
    });
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('보유종목에 추가했습니다')));
    }
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('추가 실패: $e')));
    }
  }
}


Future<bool> _closeDialog(BuildContext context, Json h) async {
  final priceC = TextEditingController(text: (h['price'] as num?)?.toStringAsFixed(0) ?? '');
  String reason = '수동';
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setS) => AlertDialog(
        title: Text('${h['name']} 매도 기록'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              controller: priceC,
              decoration: const InputDecoration(labelText: '매도가'),
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))]),
          const SizedBox(height: 8),
          DropdownButton<String>(
            value: reason,
            isExpanded: true,
            items: const ['수동', '손절', '목표가', '기간만료', '부분익절']
                .map((r) => DropdownMenuItem(value: r, child: Text(r)))
                .toList(),
            onChanged: (v) => setS(() => reason = v ?? '수동'),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('기록')),
        ],
      ),
    ),
  );
  if (ok != true) return false;
  final price = double.tryParse(priceC.text);
  if (price == null) return false;
  try {
    final r = await Api.closePosition(h['id'].toString(), price, reason: reason);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('수익률 ${pct(r['ret_pct'] as num?)} · 보유 ${r['hold_days']}일 · ${r['result']} — 매매일지에 기록됨')));
    }
    return true;
  } catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('실패: $e')));
    return false;
  }
}
