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
            return const Center(child: Text('보유종목이 없습니다.\n아래 [추가] 버튼에서 종목명이나 코드로 추가하세요.', textAlign: TextAlign.center));
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
                    if (await _deleteHolding(context, h)) _reload();
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
                          icon: const Icon(Icons.delete_outline, size: 18),
                          label: const Text('삭제'),
                          style: TextButton.styleFrom(foregroundColor: Colors.grey),
                          onPressed: () async {
                            if (await _deleteHolding(context, h)) _reload();
                          },
                        ),
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

/// 보유종목 삭제 (잘못 넣은 종목 지우기 — 매매일지에도 남지 않음)
Future<bool> _deleteHolding(BuildContext context, Json h) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('${h['name']} 삭제할까요?'),
      content: const Text('보유 목록과 매매일지에서 완전히 지워집니다.\n'
          '실제로 팔았다면 [삭제] 대신 [매도 기록]을 쓰세요 (수익률이 일지에 남습니다).'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
        FilledButton(
            style: FilledButton.styleFrom(backgroundColor: downColor),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('삭제')),
      ],
    ),
  );
  if (ok != true) return false;
  try {
    await Api.deleteHolding(h['id'].toString());
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${h['name']} 삭제했습니다')));
    }
    return true;
  } catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('삭제 실패: $e')));
    return false;
  }
}

final _codeRe = RegExp(r'^[0-9A-Za-z]{6}$');

Future<void> showAddHoldingDialog(BuildContext context,
    {String? code, String? name, double? price, double? stop, double? target, String? strategy}) async {
  final qtyC = TextEditingController();
  final priceC = TextEditingController(text: price?.toStringAsFixed(0) ?? '');
  final stopC = TextEditingController(text: stop?.toStringAsFixed(0) ?? '');
  final targetC = TextEditingController(text: target?.toStringAsFixed(0) ?? '');
  final digits = [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))];
  TextEditingController? stockC; // 종목명/코드 입력칸
  Json? picked = code == null ? null : {'code': code, 'name': name ?? code};
  String? err;

  String label(Json o) => '${o['name']} (${o['code']})';

  final saved = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setS) => AlertDialog(
        title: Text(name == null ? '보유종목 추가' : '$name 보유 추가'),
        content: SizedBox(
          width: 360,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (code != null)
                ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(name ?? code),
                    subtitle: Text(code),
                    leading: const Icon(Icons.check_circle, color: Colors.green))
              else
                Autocomplete<Json>(
                  displayStringForOption: label,
                  optionsBuilder: (v) async {
                    final q = v.text.trim();
                    if (q.isEmpty || (picked != null && v.text == label(picked!))) return const <Json>[];
                    try {
                      return await Api.search(q);
                    } catch (_) {
                      return const <Json>[];
                    }
                  },
                  onSelected: (o) => setS(() {
                    picked = o;
                    err = null;
                  }),
                  fieldViewBuilder: (ctx, c, focus, onSubmit) {
                    stockC = c;
                    return TextField(
                      controller: c,
                      focusNode: focus,
                      autofocus: true,
                      decoration: InputDecoration(
                        labelText: '종목명 또는 종목코드',
                        hintText: '예: 삼성전자 / 005930',
                        prefixIcon: const Icon(Icons.search),
                        helperText: picked != null && c.text == label(picked!) ? '선택됨 ✓' : '입력하면 아래에 목록이 나옵니다',
                        errorText: err,
                      ),
                      onChanged: (_) => setS(() {
                        if (picked != null && c.text != label(picked!)) picked = null;
                        err = null;
                      }),
                      onSubmitted: (_) => onSubmit(),
                    );
                  },
                ),
              TextField(
                  controller: qtyC,
                  decoration: const InputDecoration(labelText: '수량'),
                  keyboardType: TextInputType.number,
                  inputFormatters: digits),
              TextField(
                  controller: priceC,
                  decoration: const InputDecoration(labelText: '평균 매수가'),
                  keyboardType: TextInputType.number,
                  inputFormatters: digits),
              TextField(
                  controller: stopC,
                  decoration: const InputDecoration(labelText: '손절가 (비우면 자동)'),
                  keyboardType: TextInputType.number,
                  inputFormatters: digits),
              TextField(
                  controller: targetC,
                  decoration: const InputDecoration(labelText: '목표가 (비우면 자동)'),
                  keyboardType: TextInputType.number,
                  inputFormatters: digits),
            ]),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
          FilledButton(
            onPressed: () async {
              // 종목 확정: 목록에서 골랐으면 그대로, 아니면 입력한 글자로 찾아본다
              if (picked == null) {
                final q = (stockC?.text ?? '').trim();
                if (q.isEmpty) {
                  setS(() => err = '종목명이나 종목코드를 입력하세요');
                  return;
                }
                List<Json> found = [];
                try {
                  found = await Api.search(q);
                } catch (_) {}
                final exact = found.where((r) => r['code'] == q.toUpperCase() || r['name'] == q).toList();
                if (exact.length == 1) {
                  picked = exact.first;
                } else if (found.length == 1) {
                  picked = found.first;
                } else if (found.isEmpty && _codeRe.hasMatch(q)) {
                  picked = {'code': q.toUpperCase(), 'name': null};
                } else {
                  setS(() => err = found.isEmpty ? '"$q" 종목을 찾지 못했습니다' : '목록에서 종목을 하나 골라 주세요');
                  return;
                }
              }
              if ((double.tryParse(qtyC.text) ?? 0) <= 0 || (double.tryParse(priceC.text) ?? 0) <= 0) {
                setS(() => err = '수량과 평균 매수가를 입력하세요');
                return;
              }
              if (ctx.mounted) Navigator.pop(ctx, true);
            },
            child: const Text('저장'),
          ),
        ],
      ),
    ),
  );
  if (saved != true || picked == null) return;
  final now = DateTime.now().toIso8601String().substring(0, 16).replaceFirst('T', ' ');
  try {
    await Api.addHolding({
      'code': picked!['code'],
      'name': picked!['name'] ?? name,
      'qty': double.tryParse(qtyC.text) ?? 0,
      'avg_price': double.tryParse(priceC.text) ?? 0,
      'buy_date': now,
      'stop': double.tryParse(stopC.text),
      'target': double.tryParse(targetC.text),
      'strategy': strategy,
    });
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('${picked!['name'] ?? picked!['code']} 보유종목에 추가했습니다')));
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
